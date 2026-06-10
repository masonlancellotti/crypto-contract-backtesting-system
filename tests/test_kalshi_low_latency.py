"""Low-latency Kalshi hot path — config, local book, hot-path state, scorer, EV
gates, latency, order planning, WS fallback, smoke/benchmark, and safety.

All offline (synthetic); no network, no credentials, no orders.
"""

import json

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.hotpath_state import HotPathState
from btc5m.venues.kalshi.latency import LatencyTracker, percentile
from btc5m.venues.kalshi.local_book import KalshiLocalBook
from btc5m.venues.kalshi.low_latency_runtime import (
    evaluate_ev, run_hotpath_smoke, run_latency_benchmark,
)
from btc5m.venues.kalshi.order_planner import PlannedOrder, plan_order
from btc5m.venues.kalshi.scorer import KalshiScorer, ScoreResult
from btc5m.venues.kalshi.ws_client import KalshiWSClient


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_low_latency_safe_defaults(monkeypatch):
    for v in ("KALSHI_LOW_LATENCY_ENABLED", "KALSHI_USE_WEBSOCKET",
              "KALSHI_ORDER_PLANNING_ENABLED", "KALSHI_HOTPATH_PAPER_ONLY"):
        monkeypatch.delenv(v, raising=False)
    ll = load_config(mode="paper", load_env=False).low_latency
    assert ll.enabled is False
    assert ll.use_websocket is False
    assert ll.rest_fallback_enabled is True
    assert ll.paper_only is True
    assert ll.order_planning_enabled is False
    assert ll.live_submission_allowed is False  # always, regardless of settings
    assert ll.market_duration_seconds == 900


def test_low_latency_env_overrides(monkeypatch):
    monkeypatch.setenv("KALSHI_LOW_LATENCY_ENABLED", "true")
    monkeypatch.setenv("KALSHI_HOTPATH_SCORE_INTERVAL_MS", "500")
    monkeypatch.setenv("KALSHI_MAX_BOOK_AGE_MS", "750")
    monkeypatch.setenv("KALSHI_ALLOWED_TIME_IN_FORCE", "immediate_or_cancel")
    ll = load_config(mode="paper").low_latency
    assert ll.enabled is True
    assert ll.hotpath_score_interval_ms == 500
    assert ll.max_book_age_ms == 750
    assert ll.allowed_time_in_force == ("immediate_or_cancel",)


# --------------------------------------------------------------------------- #
# Local book
# --------------------------------------------------------------------------- #
def _raw(yes, no):
    return {"orderbook_fp": {"yes_dollars": yes, "no_dollars": no}}


def test_local_book_snapshot_and_complement_asks():
    b = KalshiLocalBook(ticker="KX-T", close_ms=2_000_000, max_book_age_ms=1000)
    b.apply_snapshot(_raw([["0.40", "500"]], [["0.58", "300"]]), recv_ms=1_000)
    assert b.best_yes_bid() == 0.40 and b.best_no_bid() == 0.58
    assert b.yes_ask() == 0.42   # 1 - best_no_bid (Decimal-exact)
    assert b.no_ask() == 0.60    # 1 - best_yes_bid
    assert b.top_depth() == 800.0  # no_bid_size(300)=yes_ask_size + yes_bid_size(500)=no_ask_size
    assert b.is_valid() is True


def test_local_book_age_and_staleness():
    b = KalshiLocalBook(ticker="KX-T", max_book_age_ms=1000)
    b.apply_snapshot(_raw([["0.40", "500"]], [["0.58", "300"]]), recv_ms=1_000)
    assert b.book_age_ms(1_500) == 500 and b.is_stale(1_500) is False
    assert b.is_stale(2_500) is True  # age 1500 > 1000


def test_local_book_crossed_flagged_invalid():
    b = KalshiLocalBook(ticker="KX-T")
    # yes bid 0.60, no bid 0.50 -> yes_ask=0.50 < yes_bid 0.60 -> crossed/invalid
    b.apply_snapshot(_raw([["0.60", "100"]], [["0.50", "100"]]), recv_ms=1)
    assert b.is_valid() is False


def test_local_book_delta_updates_best():
    b = KalshiLocalBook(ticker="KX-T")
    b.apply_snapshot(_raw([["0.40", "500"]], [["0.58", "300"]]), recv_ms=1)
    b.apply_delta("no", 0.59, 400, recv_ms=2)
    assert b.best_no_bid() == 0.59 and b.yes_ask() == 0.41


# --------------------------------------------------------------------------- #
# Hot-path state
# --------------------------------------------------------------------------- #
def _spot(ts, px):
    return {"source": "coinbase", "event_type": "ticker", "recv_ms": ts,
            "price": px, "best_bid": px - 0.5, "best_ask": px + 0.5}


def test_hotpath_state_snapshot_fields_and_bounded():
    cfg = load_config(mode="paper")
    st = HotPathState(cfg, fee_model=KalshiFeeModel(), deribit_enabled=False, spot_sample_cap=128)
    st.set_market({"ticker": "KX-T", "yes_sub_title": "Target Price: $70,000.00",
                   "close_ms": 2_000_000, "window_start_ms": 1_000_000, "status": "active"})
    base = 1_900_000
    for i in range(20):
        st.ingest_underlying(_spot(base + i * 1000, 70_000.0 + i))
    st.update_book("KX-T", _raw([["0.40", "500"]], [["0.58", "300"]]), recv_ms=1_920_000)
    row = st.feature_snapshot("KX-T", as_of_ms=1_920_050)
    assert row["feature_set_version"] == 3
    assert row["yes_ask"] == 0.42 and row["reference_start_price"] == 70_000.0
    assert "deribit_enabled" in row and row["deribit_enabled"] is False
    assert "hotpath_book_age_ms" in row and "hotpath_underlying_age_ms" in row
    assert st.spot_samples.maxlen == 128  # bounded deque (no unbounded growth)


# --------------------------------------------------------------------------- #
# Scorer
# --------------------------------------------------------------------------- #
def test_scorer_neutral_uncalibrated_no_artifact():
    sc = KalshiScorer(load_config(mode="paper"))
    assert sc.calibrated is False
    assert sc.calibration_status == "uncalibrated"
    assert sc.feature_schema_version == 3
    model_id = id(sc.model)
    snap = {"reference_price": 70_010.0, "reference_start_price": 70_000.0,
            "seconds_to_close": 300.0, "spot_sigma_per_sqrt_s": 1e-4}
    r1 = sc.score(snap)
    r2 = sc.score(snap)
    assert 0.0 <= r1.p_yes <= 1.0
    assert id(sc.model) == model_id  # model not reloaded per score


def test_scorer_reports_insufficient_inputs():
    sc = KalshiScorer(load_config(mode="paper"))
    r = sc.score({"reference_price": None, "reference_start_price": None})
    assert r.reason == "INSUFFICIENT_INPUTS"


# --------------------------------------------------------------------------- #
# Executable EV + gates
# --------------------------------------------------------------------------- #
def _ev_row(**over):
    row = {"market_ticker": "KX-T", "series_ticker": "KXBTC15M",
           "yes_ask": 0.42, "no_ask": 0.60, "book_ok": True, "seconds_to_close": 300.0,
           "hotpath_book_age_ms": 100, "hotpath_underlying_age_ms": 100,
           "reference_start_price": 70_000.0, "top_depth": 500.0}
    row.update(over)
    return row


def _score(p, calibrated=False):
    return ScoreResult(p_yes=p, p_yes_lower=None, p_yes_upper=None, calibrated=calibrated,
                       calibration_status=("calibrated" if calibrated else "uncalibrated"),
                       model_version="baseline-normal", feature_schema_version=3)


def test_ev_uses_executable_asks_and_edges():
    cfg = load_config(mode="paper")
    ev = evaluate_ev(_ev_row(), _score(0.60), fee_model=KalshiFeeModel(), cfg=cfg)
    assert ev["executable_yes_price"] == 0.42  # not midpoint
    assert abs(ev["raw_edge_yes"] - (0.60 - 0.42)) < 1e-9
    assert abs(ev["raw_edge_no"] - ((1 - 0.60) - 0.60)) < 1e-9
    assert ev["selected_side"] == "BUY_YES"
    assert ev["decision_state"] == "MANUAL_REVIEW"  # uncalibrated cap


def test_ev_uncalibrated_blocks_paper_candidate_but_calibrated_allows():
    cfg = load_config(mode="paper")
    base = _ev_row()
    assert evaluate_ev(base, _score(0.60, calibrated=False),
                       fee_model=KalshiFeeModel(), cfg=cfg)["decision_state"] == "MANUAL_REVIEW"
    assert evaluate_ev(base, _score(0.60, calibrated=True),
                       fee_model=KalshiFeeModel(), cfg=cfg)["decision_state"] == "PAPER_CANDIDATE"


def test_ev_rejects_stale_book_underlying_depth_and_missing_line():
    cfg = load_config(mode="paper")
    fm = KalshiFeeModel()
    assert evaluate_ev(_ev_row(hotpath_book_age_ms=5000), _score(0.6), fee_model=fm, cfg=cfg)["decision_state"] == "REJECTED"
    assert "STALE_BOOK" in evaluate_ev(_ev_row(hotpath_book_age_ms=5000), _score(0.6), fee_model=fm, cfg=cfg)["reason_codes"]
    assert "STALE_UNDERLYING" in evaluate_ev(_ev_row(hotpath_underlying_age_ms=9000), _score(0.6), fee_model=fm, cfg=cfg)["reason_codes"]
    assert "INSUFFICIENT_DEPTH" in evaluate_ev(_ev_row(top_depth=0.0), _score(0.6), fee_model=fm, cfg=cfg)["reason_codes"]
    assert "MISSING_START_REFERENCE" in evaluate_ev(_ev_row(reference_start_price=None), _score(0.6), fee_model=fm, cfg=cfg)["reason_codes"]


def test_ev_no_model_prob_is_watch():
    cfg = load_config(mode="paper")
    ev = evaluate_ev(_ev_row(), _score(None), fee_model=KalshiFeeModel(), cfg=cfg)
    assert ev["decision_state"] == "WATCH" and "NO_MODEL_PROB" in ev["reason_codes"]


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #
def test_latency_tracker_percentiles_and_stopwatch():
    assert percentile([10, 20, 30], 0.5) == 20
    t = LatencyTracker()
    for v in (10, 20, 30, 40):
        t.record("x", v)
    s = t.summary()["x"]
    assert s["count"] == 4 and s["max"] == 40
    with t.stopwatch("y") as sw:
        sum(range(100))
    assert sw.ms >= 0 and "y" in t.summary()
    t.reject("STALE_BOOK")
    assert t.rejections["STALE_BOOK"] == 1


# --------------------------------------------------------------------------- #
# Order planner
# --------------------------------------------------------------------------- #
def test_order_planner_fok_no_chase_and_live_disabled():
    cfg = load_config(mode="paper")
    dec = {"side": "BUY_YES", "executable_price": 0.42, "order_size": 5, "reason_codes": []}
    po = plan_order(decision=dec, row=_ev_row(), fee_model=KalshiFeeModel(), config=cfg,
                    mode="paper_fok_sim", size=5)
    assert isinstance(po, PlannedOrder)
    assert po.live_submission_allowed is False
    assert po.time_in_force == "fill_or_kill"
    assert po.max_acceptable_price == 0.42 and po.no_chase is True
    assert po.side == "YES" and po.size == 5


def test_order_planner_ioc_mode_and_none_when_no_side():
    cfg = load_config(mode="paper")
    po = plan_order(decision={"side": "BUY_NO", "executable_price": 0.60, "reason_codes": []},
                    row=_ev_row(), fee_model=KalshiFeeModel(), config=cfg, mode="paper_ioc_sim")
    assert po.time_in_force == "immediate_or_cancel" and po.side == "NO"
    assert plan_order(decision={"side": None, "executable_price": None}, row=_ev_row(),
                      fee_model=KalshiFeeModel(), config=cfg) is None


def test_order_planner_rejects_unknown_mode():
    import pytest
    with pytest.raises(ValueError):
        plan_order(decision={"side": "BUY_YES", "executable_price": 0.42}, row=_ev_row(),
                   fee_model=KalshiFeeModel(), config=load_config(mode="paper"), mode="LIVE_NOW")


# --------------------------------------------------------------------------- #
# WS fallback
# --------------------------------------------------------------------------- #
def test_ws_unavailable_reports_rest_fallback(monkeypatch):
    monkeypatch.delenv("KALSHI_USE_WEBSOCKET", raising=False)
    a = KalshiWSClient(load_config(mode="paper", load_env=False)).availability()
    assert a["available"] is False and "REST fallback" in a["reason"]


def test_ws_enabled_without_auth_reports_auth_blocker(monkeypatch):
    monkeypatch.setenv("KALSHI_USE_WEBSOCKET", "true")
    monkeypatch.delenv("KALSHI_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    a = KalshiWSClient(load_config(mode="paper", load_env=False)).availability()
    assert a["available"] is False and "auth" in a["reason"].lower()


# --------------------------------------------------------------------------- #
# Smoke + benchmark (offline synthetic)
# --------------------------------------------------------------------------- #
def test_hotpath_smoke_synthetic_no_paper_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    res = run_hotpath_smoke(cfg, series="KXBTC15M", seconds=0.0, max_markets=1,
                            sources="coinbase,binance", synthetic=True, emit=lambda *_: None)
    assert res["synthetic"] is True and res["decisions"] >= 1
    assert "PAPER_CANDIDATE" not in res["decisions_by_state"]  # uncalibrated model
    files = list((tmp_path / "decisions").glob("kalshi_hotpath_decisions-*.jsonl"))
    assert files, "smoke must write buffered decision events"
    ev = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert ev["live_order_submitted"] is False
    assert "end_to_end_latency_ms" in ev and "feature_latency_ms" in ev


def test_latency_benchmark_offline_reports_percentiles():
    res = run_latency_benchmark(load_config(mode="paper"), samples=50, emit=lambda *_: None)
    assert res["samples"] == 50
    assert res["latency"]["feature"]["p50"] is not None
    assert res["latency"]["score"]["p99"] is not None


def test_hotpath_commands_registered_and_run(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert "kalshi-hotpath-smoke" in _COMMANDS
    assert "kalshi-latency-benchmark" in _COMMANDS
    assert main(["kalshi-latency-benchmark", "--series", "KXBTC15M", "--samples", "20"]) == 0


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_live_still_disabled_and_hotpath_paper_only(monkeypatch):
    monkeypatch.setenv("KALSHI_LOW_LATENCY_ENABLED", "true")  # even enabled...
    cfg = load_config(mode="paper")
    assert cfg.live_permitted is False           # ...live remains impossible
    assert cfg.low_latency.live_submission_allowed is False
    assert main(["check-live-disabled"]) == 0
