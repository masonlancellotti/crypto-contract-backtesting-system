"""Source freshness — LIVENESS vs DECISION freshness, fallback, and the strict
PAPER_CANDIDATE freshness gate.

Verifies (offline) that a collector can be ALIVE while DECISION-stale; that Binance
fallback engages only when allowed + itself fresh; that both-stale / primary-required
reject; and that stale data can NEVER become a PAPER_CANDIDATE in the paper runtime.
Nothing trades; live stays disabled.
"""

import json
from collections import Counter

import pytest

from btc5m.config import load_config

WIN = 15 * 60 * 1000


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_freshness_config_defaults_and_env(monkeypatch):
    for k in ("COINBASE_DECISION_MAX_AGE_MS", "KALSHI_BOOK_DECISION_MAX_AGE_MS",
              "UNDERLYING_ALLOW_BINANCE_FALLBACK", "COINBASE_LIVENESS_THRESHOLD_MS"):
        monkeypatch.delenv(k, raising=False)
    f = load_config(mode="paper").freshness
    # liveness is LOOSE, decision is STRICT, and they are SEPARATE numbers
    assert f.coinbase_liveness_ms == 60_000 and f.coinbase_decision_max_age_ms == 5_000
    assert f.kalshi_book_liveness_ms == 60_000 and f.kalshi_book_decision_max_age_ms == 1_000
    assert f.underlying_allow_binance_fallback is True
    monkeypatch.setenv("COINBASE_DECISION_MAX_AGE_MS", "3000")
    monkeypatch.setenv("UNDERLYING_ALLOW_BINANCE_FALLBACK", "false")
    f2 = load_config(mode="paper").freshness
    assert f2.coinbase_decision_max_age_ms == 3000 and f2.underlying_allow_binance_fallback is False


# --------------------------------------------------------------------------- #
# Central freshness module
# --------------------------------------------------------------------------- #
def test_alive_but_decision_stale():
    from btc5m.venues.kalshi import freshness as F
    # 33s old: ALIVE under the 60s liveness window, but DECISION-stale under 5s.
    s = F.source_freshness("coinbase", 33_000, liveness_ms=60_000, decision_ms=5_000)
    assert s["liveness_stale"] is False and s["decision_stale"] is True
    assert s["fresh_for_collection"] is True
    assert s["fresh_for_decision"] is False and s["fresh_for_paper_candidate"] is False


def test_no_data_is_stale_for_everything():
    from btc5m.venues.kalshi import freshness as F
    s = F.source_freshness("coinbase", None, liveness_ms=60_000, decision_ms=5_000)
    assert s["liveness_stale"] is True and s["decision_stale"] is True
    assert s["fresh_for_collection"] is False and s["fresh_for_paper_candidate"] is False


def test_underlying_fallback_used_when_allowed(monkeypatch):
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    u = F.resolve_underlying(coinbase_age_ms=33_000, binance_age_ms=1_000, fcfg=f)
    assert u["coinbase_decision_stale"] is True and u["binance_decision_stale"] is False
    assert u["fallback_used"] is True and u["reference_source"] == "binance"
    assert u["fresh_for_paper_candidate"] is True and u["both_stale"] is False


def test_underlying_both_stale_rejects():
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    u = F.resolve_underlying(coinbase_age_ms=33_000, binance_age_ms=40_000, fcfg=f)
    assert u["both_stale"] is True and u["fresh_for_paper_candidate"] is False
    assert u["reason"] == "BOTH_STALE"


def test_underlying_fallback_disabled_rejects(monkeypatch):
    from btc5m.venues.kalshi import freshness as F
    monkeypatch.setenv("UNDERLYING_ALLOW_BINANCE_FALLBACK", "false")
    f = load_config(mode="paper").freshness
    u = F.resolve_underlying(coinbase_age_ms=33_000, binance_age_ms=1_000, fcfg=f)
    assert u["fresh_for_paper_candidate"] is False and u["fallback_used"] is False
    assert u["reason"] == "PRIMARY_STALE_FALLBACK_DISABLED"


def test_underlying_require_primary_for_entry(monkeypatch):
    from btc5m.venues.kalshi import freshness as F
    monkeypatch.setenv("UNDERLYING_REQUIRE_PRIMARY_FOR_ENTRY", "true")
    f = load_config(mode="paper").freshness
    # binance fresh but primary required -> coinbase staleness decides
    u = F.resolve_underlying(coinbase_age_ms=33_000, binance_age_ms=1_000, fcfg=f)
    assert u["require_primary_for_entry"] is True and u["fallback_used"] is False
    assert u["fresh_for_paper_candidate"] is False


def test_paper_candidate_freshness_gate():
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    # fresh book + underlying via fallback -> OK
    g = F.paper_candidate_freshness(book_age_ms=500, coinbase_age_ms=33_000,
                                    binance_age_ms=1_000, fcfg=f)
    assert g["ok"] is True and g["reasons"] == []
    # stale book -> reject
    g2 = F.paper_candidate_freshness(book_age_ms=2_000, coinbase_age_ms=1_000,
                                     binance_age_ms=1_000, fcfg=f)
    assert g2["ok"] is False and "BOOK_DECISION_STALE" in g2["reasons"]
    # both underlying stale -> reject
    g3 = F.paper_candidate_freshness(book_age_ms=500, coinbase_age_ms=33_000,
                                     binance_age_ms=40_000, fcfg=f)
    assert g3["ok"] is False and "UNDERLYING_BOTH_STALE" in g3["reasons"]
    # live feature-row wall-clock age too old -> reject (only when provided)
    g4 = F.paper_candidate_freshness(book_age_ms=500, coinbase_age_ms=1_000, binance_age_ms=1_000,
                                     fcfg=f, feature_row_age_ms=10_000)
    assert g4["ok"] is False and "FEATURE_ROW_STALE" in g4["reasons"]


def test_rest_book_freshness_uses_recv_when_source_ts_missing():
    from btc5m.venues.kalshi.book_freshness import effective_book_age
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    row = {"as_of_ms": 10_200, "recv_ms": 10_000, "source_ts_ms": None, "quote_age_ms": None}
    b = effective_book_age(row, as_of_ms=row["as_of_ms"])
    assert b["book_age_ms"] == 200
    assert b["book_age_basis"] == "recv_ms"
    assert b["book_age_source"] == "kalshi_rest_recv_ms"
    g = F.paper_candidate_freshness(book_age_ms=b["book_age_ms"], coinbase_age_ms=1_000,
                                    binance_age_ms=1_000, fcfg=f)
    assert g["ok"] is True and "BOOK_DECISION_STALE" not in g["reasons"]


def test_rest_book_old_recv_is_stale():
    from btc5m.venues.kalshi.book_freshness import effective_book_age
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    row = {"as_of_ms": 12_500, "recv_ms": 10_000, "source_ts_ms": None, "quote_age_ms": None}
    b = effective_book_age(row, as_of_ms=row["as_of_ms"])
    assert b["book_age_ms"] == 2_500 and b["book_age_basis"] == "recv_ms"
    g = F.paper_candidate_freshness(book_age_ms=b["book_age_ms"], coinbase_age_ms=1_000,
                                    binance_age_ms=1_000, fcfg=f)
    assert g["ok"] is False and "BOOK_DECISION_STALE" in g["reasons"]


def test_quote_age_null_does_not_make_fresh_rest_live_row_stale():
    from btc5m.venues.kalshi import freshness as F
    from btc5m.venues.kalshi.paper_runtime import _live_row
    f = load_config(mode="paper").freshness
    row = _live_row({"market_ticker": "KX-REST", "as_of_ms": 20_050, "recv_ms": 20_000,
                     "source_ts_ms": None, "quote_age_ms": None,
                     "coinbase_feed_age_ms": 1_000, "binance_feed_age_ms": 1_000})
    assert row["book_age_ms"] == 50
    assert row["book_age_basis"] == "recv_ms"
    g = F.paper_candidate_freshness(book_age_ms=row["book_age_ms"], coinbase_age_ms=1_000,
                                    binance_age_ms=1_000, fcfg=f)
    assert g["ok"] is True


def test_live_feature_rows_backfill_missing_rest_timestamp_from_normalized(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    feats = tmp_path / "features"
    norm = tmp_path / "normalized"
    feats.mkdir(parents=True)
    norm.mkdir(parents=True)
    feature = {"market_ticker": "KX-REST", "as_of_ms": 20_050, "close_ms": 40_000,
               "quote_age_ms": None, "book_age_ms": None,
               "coinbase_feed_age_ms": 1_000, "binance_feed_age_ms": 1_000}
    book = {"market_ticker": "KX-REST", "recv_ms": 20_000, "source_ts_ms": None,
            "quote_age_ms": None}
    future_book = {"market_ticker": "KX-REST", "recv_ms": 20_100, "source_ts_ms": None,
                   "quote_age_ms": None}
    (feats / "kalshi_feature_rows-20260605.jsonl").write_text(
        json.dumps(feature) + "\n", encoding="utf-8")
    (norm / "kalshi_orderbook-20260605.jsonl").write_text(
        json.dumps({"stream": "kalshi_orderbook", "event": book}) + "\n"
        + json.dumps({"stream": "kalshi_orderbook", "event": future_book}) + "\n",
        encoding="utf-8")

    from btc5m.venues.kalshi.paper_runtime import latest_feature_rows
    row = latest_feature_rows(load_config(mode="paper"), lines=20)[0]
    assert row["book_age_ms"] == 50
    assert row["book_age_basis"] == "recv_ms"
    assert row["book_recv_ms"] == 20_000
    assert row["book_timestamp_joined_from_normalized"] is True


def test_candidate_like_row_blocked_only_when_actual_book_age_exceeds_threshold():
    from btc5m.venues.kalshi import freshness as F
    from btc5m.venues.kalshi.paper_runtime import _live_row
    f = load_config(mode="paper").freshness

    fresh = _live_row({"market_ticker": "KX-REST", "as_of_ms": 30_500, "recv_ms": 30_000,
                       "source_ts_ms": None, "quote_age_ms": None,
                       "coinbase_feed_age_ms": 1_000, "binance_feed_age_ms": 1_000})
    stale = _live_row({"market_ticker": "KX-REST", "as_of_ms": 33_000, "recv_ms": 30_000,
                       "source_ts_ms": None, "quote_age_ms": None,
                       "coinbase_feed_age_ms": 1_000, "binance_feed_age_ms": 1_000})

    def candidate_reasons(row):
        gate = F.paper_candidate_freshness(book_age_ms=row["book_age_ms"], coinbase_age_ms=1_000,
                                           binance_age_ms=1_000, fcfg=f)
        reasons = ["PAPER_CANDIDATE_OK"]
        if not gate["ok"]:
            reasons.extend(gate["reasons"])
        return reasons

    assert "BOOK_DECISION_STALE" not in candidate_reasons(fresh)
    assert "BOOK_DECISION_STALE" in candidate_reasons(stale)


def test_future_recv_ms_is_not_used_as_fresh_book_data():
    from btc5m.venues.kalshi.book_freshness import effective_book_age
    from btc5m.venues.kalshi import freshness as F
    f = load_config(mode="paper").freshness
    b = effective_book_age({"as_of_ms": 40_000, "recv_ms": 40_050,
                            "source_ts_ms": None, "quote_age_ms": None})
    assert b["book_age_ms"] is None
    assert b["book_age_basis"] == "recv_ms_after_as_of"
    g = F.paper_candidate_freshness(book_age_ms=b["book_age_ms"], coinbase_age_ms=1_000,
                                    binance_age_ms=1_000, fcfg=f)
    assert g["ok"] is False and "BOOK_DECISION_STALE" in g["reasons"]


def test_build_feature_row_records_rest_book_age_provenance():
    from btc5m.venues.kalshi.fees import KalshiFeeModel
    from btc5m.venues.kalshi.paper import build_feature_row
    norm = {"market_ticker": "KX-REST", "series_ticker": "KXBTC15M", "recv_ms": 50_000,
            "source_ts_ms": None, "quote_age_ms": None, "close_ms": 60_000,
            "status": "active", "yes_ask": 0.42, "no_ask": 0.60,
            "yes_ask_size": 100.0, "no_ask_size": 100.0,
            "book_validity_flags": {"yes_side_present": True, "no_side_present": True,
                                    "prices_in_range": True}}
    row = build_feature_row(norm, as_of_ms=50_125, reference_price=70_001.0,
                            sigma_per_sqrt_s=1e-4, start_reference=70_000.0,
                            fee_model=KalshiFeeModel())
    assert row["quote_age_ms"] is None
    assert row["book_age_ms"] == 125
    assert row["book_age_basis"] == "recv_ms"
    assert row["book_recv_ms"] == 50_000
    assert row["recv_ms"] == 50_000


def test_runtime_summary_splits_freshness_stale_rows():
    from btc5m.venues.kalshi.paper_runtime import _summarize_eval
    prep = {"edge_required": True, "buckets": [], "rt": {"model_path": "m", "calibrator_path": "c"}}
    decisions = [
        {"freshness_ok": False, "book_decision_stale": True, "reason_codes": []},
        {"freshness_ok": False, "underlying_decision_stale": True, "reason_codes": []},
        {"freshness_ok": True, "reason_codes": ["FEATURE_ROW_STALE"]},
        {"freshness_ok": True, "deribit_stale": True, "reason_codes": ["STALE_DERIBIT"]},
    ]
    out = _summarize_eval({}, prep, decisions, Counter(), [], enforce_feature_row_age=True,
                          ftr_thr=1_000, n_rows=len(decisions))
    assert out["freshness_stale_rows"] == 2
    assert out["book_stale_rows"] == 1
    assert out["underlying_stale_rows"] == 1
    assert out["feature_row_stale_rows"] == 1
    assert out["deribit_stale_rows"] == 1


# --------------------------------------------------------------------------- #
# source-health: liveness vs decision per source
# --------------------------------------------------------------------------- #
def _norm(prefix, tmp_path, recv_ms, **fields):
    d = tmp_path / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    ev = {"source": prefix.replace("underlying_", ""), "recv_ms": recv_ms, **fields}
    (d / f"{prefix}-20260602.jsonl").write_text(
        json.dumps({"stream": prefix, "event": ev}) + "\n", encoding="utf-8")


def test_source_health_reports_liveness_vs_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from btc5m.timeutils import now_ms
    from btc5m.venues.kalshi.source_health import assess_source_health
    now = now_ms()
    _norm("underlying_coinbase", tmp_path, now - 33_000, price=70000.0)   # alive(60s) but decision-stale(5s)
    _norm("underlying_binance_futures", tmp_path, now - 1_000, best_bid=70010.0)  # fresh
    h = assess_source_health(load_config(mode="paper"))
    by = {s["source"]: s for s in h["sources"]}
    cb = by["coinbase"]
    assert cb["liveness_stale"] is False and cb["decision_stale"] is True
    assert cb["fresh_for_collection"] is True and cb["fresh_for_paper_candidate"] is False
    u = h["underlying"]
    assert u["underlying_liveness_ok"] is True          # binance alive
    assert u["underlying_decision_ok"] is True          # decision-fresh via fallback
    assert u["fallback_used"] is True and u["reference_source"] == "binance"


def test_source_health_both_decision_stale_blocks_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from btc5m.timeutils import now_ms
    from btc5m.venues.kalshi.source_health import assess_source_health
    now = now_ms()
    _norm("underlying_coinbase", tmp_path, now - 33_000, price=70000.0)
    _norm("underlying_binance_futures", tmp_path, now - 40_000, best_bid=70010.0)
    u = assess_source_health(load_config(mode="paper"))["underlying"]
    assert u["underlying_liveness_ok"] is True          # both alive under 60s
    assert u["underlying_decision_ok"] is False and u["both_decision_stale"] is True


# --------------------------------------------------------------------------- #
# paper runtime: stale data NEVER becomes PAPER_CANDIDATE
# --------------------------------------------------------------------------- #
def _setup_promo(tmp_path, monkeypatch, *, book_age_ms):
    """Build feature rows (with a chosen book age) + labels + staged model+calibrator,
    promote for paper, and return the loaded config."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    from btc5m.venues.kalshi.feature_schema import DISTANCE_TIME_VOL_FEATURES, MODEL_SCHEMA_VERSION
    feats = tmp_path / "features"; feats.mkdir(parents=True)
    labels = tmp_path / "labels"; labels.mkdir(parents=True)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(4):
        close = base + (w + 1) * WIN
        yes = w % 2
        for i in range(6):
            fr.append({"market_ticker": f"KX-{w}", "has_orderbook": True, "has_underlying": True,
                       "has_start_reference": True, "book_ok": True,
                       "seconds_to_close": 120.0, "as_of_ms": close - (200 - i * 10) * 1000,
                       "close_ms": close, "feature_set_version": 3, "yes_ask": 0.42, "no_ask": 0.60,
                       "yes_spread": 0.02, "no_spread": 0.02, "top_depth": 100.0,
                       "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": book_age_ms,
                       "reference_start_price": 70000.0, "reference_price": 70010.0,
                       "distance_to_start": (50.0 if yes else -50.0), "spot_sigma_per_sqrt_s": 1e-4,
                       "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
                       "coinbase_feed_age_ms": 1000, "binance_feed_age_ms": 1000,
                       "coinbase_stale": False, "binance_stale": False})
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL", "label_yes_resolved": yes})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fr) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lr) + "\n", encoding="utf-8")
    for sub, name in (("calibration", "kalshi_calibration_report_X.md"),
                      ("backtests", "kalshi_baseline_comparison_X.md"),
                      ("edge", "kalshi_edge_policy_report_X.md"),
                      ("frequency", "kalshi_frequency_frontier_X.md")):
        d = tmp_path / "reports" / sub; d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text("x", encoding="utf-8")
    cfg = load_config(mode="paper")
    from btc5m.venues.kalshi.calibrate import Calibrator, build_calibrator_artifact, save_calibrator
    from btc5m.venues.kalshi.model_artifacts import build_artifact, save_artifact
    from btc5m.venues.kalshi.paper_promotion import promote
    feats_n = DISTANCE_TIME_VOL_FEATURES
    art = build_artifact(model_name="microstructure_logistic", model_obj_dict={"w": [0.0] * len(feats_n), "b": 0.0},
                         feature_names=feats_n, imputer_dict={"means": [0.0] * len(feats_n),
                         "stds": [1.0] * len(feats_n), "n_features": len(feats_n)},
                         split_metadata={}, training_config={}, metrics={}, tradable=True,
                         model_schema_version=MODEL_SCHEMA_VERSION, is_diagnostic=False, is_staged=True)
    m = save_artifact(cfg, art, staged=True, stem="kalshi_microstructure_logistic_test")["artifact_file"]
    cal = build_calibrator_artifact(calibrator=Calibrator(method="identity", params={}), method="platt",
                                    model_name="microstructure_logistic", split_metadata={}, metrics_before={},
                                    metrics_after={}, tradable=True, gate_windows=4, is_staged=True)
    c = save_calibrator(cfg, cal, staged=True, stem="kalshi_calibrator_test")["calibrator_file"]
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    return cfg


def test_paper_runtime_never_emits_stale_candidate(tmp_path, monkeypatch):
    # book is grossly stale (10s) -> every row is freshness-stale for a decision.
    cfg = _setup_promo(tmp_path, monkeypatch, book_age_ms=10_000)
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="paper", limit=20)
    assert ev["status"] == "OK"
    assert ev["freshness_stale_rows"] >= 1               # stale book flagged
    for d in ev["decisions"]:
        # INVARIANT: a PAPER_CANDIDATE can NEVER have failed the freshness gate.
        assert d["live_submission_allowed"] is False
        assert "freshness_ok" in d and "book_decision_stale" in d
        if d["decision_state"] == "PAPER_CANDIDATE":
            assert d["freshness_ok"] is True
        if d["book_decision_stale"]:
            assert d["decision_state"] != "PAPER_CANDIDATE"


def test_paper_runtime_records_carry_freshness(tmp_path, monkeypatch):
    cfg = _setup_promo(tmp_path, monkeypatch, book_age_ms=500)   # fresh book
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="shadow", limit=10)
    assert ev["decisions"]
    d = ev["decisions"][0]
    for key in ("freshness_ok", "freshness_reasons", "book_age_ms", "coinbase_feed_age_ms",
                "binance_feed_age_ms", "underlying_reference_source", "underlying_decision_stale"):
        assert key in d
