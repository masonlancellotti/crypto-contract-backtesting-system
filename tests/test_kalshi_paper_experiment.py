"""Controlled PAPER experiment framework — preflight, shadow, paper gating, abort.

Offline. Verifies: experiment defaults are safe; preflight blocks on no-promotion /
live-enabled and is shadow-ready with a valid promotion; shadow mode logs decisions
but NEVER fills/candidates; paper mode requires a prior shadow run + preflight; the
fill simulator settles vs the OFFICIAL label; abort criteria fire; nothing goes live.
"""

import json
from datetime import datetime, timezone

from btc5m.config import load_config

WIN = 15 * 60 * 1000


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_experiment_config_defaults_safe(monkeypatch):
    for k in ("KALSHI_PAPER_EXPERIMENT_ENABLED", "KALSHI_PAPER_EXPERIMENT_MODE"):
        monkeypatch.delenv(k, raising=False)
    x = load_config(mode="paper").paper_experiment
    assert x.enabled is False and x.mode == "shadow"
    assert x.min_net_edge_cents >= 5 and x.max_trades_per_window == 1 and x.max_daily_trades == 10
    assert x.require_promoted_model is True and x.allow_diagnostic is False
    assert x.live_submission_allowed is False
    monkeypatch.setenv("KALSHI_PAPER_EXPERIMENT_MODE", "paper")
    assert load_config(mode="paper").paper_experiment.mode == "paper"


# --------------------------------------------------------------------------- #
# Fixture: feature rows + labels + staged artifacts + (optional) promotion
# --------------------------------------------------------------------------- #
def _frow(tk, *, as_of, close, yes, book_age=500):
    return {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
            "has_start_reference": True, "book_ok": True, "seconds_to_close": 120.0,
            "as_of_ms": as_of, "close_ms": close, "feature_set_version": 3,
            "yes_ask": 0.42, "no_ask": 0.60, "yes_spread": 0.02, "no_spread": 0.02,
            "top_depth": 100.0, "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": book_age,
            "reference_start_price": 70000.0, "reference_price": 70010.0,
            "distance_to_start": (50.0 if yes else -50.0), "spot_sigma_per_sqrt_s": 1e-4,
            "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
            "coinbase_feed_age_ms": 1000, "binance_feed_age_ms": 1000,
            "coinbase_stale": False, "binance_stale": False}


def _write_fresh_source(tmp_path):
    """Write today-dated fresh normalized rows so source-health reads decision-fresh."""
    from btc5m.timeutils import now_ms
    norm = tmp_path / "normalized"; norm.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    now = now_ms()
    rows = {"underlying_coinbase": {"source": "coinbase", "recv_ms": now, "price": 70000.0},
            "underlying_binance_futures": {"source": "binance", "recv_ms": now, "best_bid": 70010.0},
            "kalshi_orderbook": {"source": "kalshi", "recv_ms": now}}
    for prefix, ev in rows.items():
        (norm / f"{prefix}-{day}.jsonl").write_text(
            json.dumps({"stream": prefix, "event": ev}) + "\n", encoding="utf-8")


def _setup(tmp_path, monkeypatch, *, promote=True, diagnostic=False, fresh_source=False):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    from btc5m.venues.kalshi.feature_schema import DISTANCE_TIME_VOL_FEATURES, MODEL_SCHEMA_VERSION
    feats = tmp_path / "features"; feats.mkdir(parents=True)
    labels = tmp_path / "labels"; labels.mkdir(parents=True)
    # These are already-settled, historical windows: a fixed instant far in the past
    # (well before any plausible wall-clock run date), so the rows always read as stale
    # to the freshness gates and never as decision-fresh. This is the fail-safe anchor —
    # as the calendar advances the gap to `now` only grows, so the fixture never drifts
    # into a fresh-looking regime. (Live-decision tests write their own today-dated
    # fresh rows separately via _write_fresh_source / _write_live_feature_rows.)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(4):
        close = base + (w + 1) * WIN
        yes = w % 2
        for i in range(6):
            fr.append(_frow(f"KX-{w}", as_of=close - (200 - i * 10) * 1000, close=close, yes=yes))
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
    if fresh_source:
        _write_fresh_source(tmp_path)
    cfg = load_config(mode="paper")
    if promote:
        from btc5m.venues.kalshi.calibrate import Calibrator, build_calibrator_artifact, save_calibrator
        from btc5m.venues.kalshi.model_artifacts import build_artifact, save_artifact
        from btc5m.venues.kalshi.paper_promotion import promote as do_promote
        fn = DISTANCE_TIME_VOL_FEATURES
        art = build_artifact(model_name="microstructure_logistic",
                             model_obj_dict={"w": [0.0] * len(fn), "b": 0.0}, feature_names=fn,
                             imputer_dict={"means": [0.0] * len(fn), "stds": [1.0] * len(fn), "n_features": len(fn)},
                             split_metadata={}, training_config={}, metrics={}, tradable=(not diagnostic),
                             model_schema_version=MODEL_SCHEMA_VERSION, is_diagnostic=diagnostic, is_staged=True)
        m = save_artifact(cfg, art, staged=True, stem="kalshi_microstructure_logistic_test")["artifact_file"]
        cal = build_calibrator_artifact(calibrator=Calibrator(method="identity", params={}), method="platt",
                                        model_name="microstructure_logistic", split_metadata={}, metrics_before={},
                                        metrics_after={}, tradable=True, gate_windows=4, is_staged=True)
        c = save_calibrator(cfg, cal, staged=True, stem="kalshi_calibrator_test")["calibrator_file"]
        if not diagnostic:
            do_promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    return cfg


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def test_preflight_blocks_without_promotion(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=False)
    from btc5m.venues.kalshi.paper_experiment import preflight
    r = preflight(cfg, series="KXBTC15M")
    assert r["preflight_pass"] is False
    assert "paper_promotion_manifest_exists" in r["blockers"] or "promotion_valid_hash_match" in r["blockers"]
    assert r["recommended_mode"] == "disabled"
    assert r["live_submission_allowed"] is False


def test_preflight_shadow_ready_with_promotion(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import preflight
    r = preflight(cfg, series="KXBTC15M")
    assert r["preflight_pass"] is True            # shadow-ready
    assert r["blockers"] == []
    # paper not ready (no fresh source rows) -> recommend shadow
    assert r["recommended_mode"] == "shadow"


def test_preflight_blocks_when_live_enabled(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    # simulate an unexpected live-enable -> live_blockers() empties -> severe FAIL
    monkeypatch.setattr(type(cfg), "live_blockers", lambda self: [])
    from btc5m.venues.kalshi.paper_experiment import preflight
    r = preflight(cfg, series="KXBTC15M")
    assert r["preflight_pass"] is False and "live_disabled" in r["blockers"]
    assert r["recommended_mode"] == "disabled"


def test_preflight_paper_ready_with_fresh_source(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True, fresh_source=True)
    from btc5m.venues.kalshi.paper_experiment import preflight
    r = preflight(cfg, series="KXBTC15M")
    assert r["preflight_pass"] is True
    assert r["paper_ready"] is True and r["kalshi_book_decision_stale"] is False


# --------------------------------------------------------------------------- #
# Shadow mode
# --------------------------------------------------------------------------- #
def test_shadow_run_logs_no_fills_no_candidates(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import run_experiment
    r = run_experiment(cfg, series="KXBTC15M", mode="shadow", limit=20)
    assert r["status"] == "COMPLETED" and r["live_submission_allowed"] is False
    s = r["summary"]
    assert s["paper_candidates"] == 0 and s["paper_fills"] == 0 and s["open_positions"] == 0
    assert set(s["decisions_by_state"]).issubset({"SHADOW_DECISION"})
    # ledger written + every row live_submission_allowed False
    from pathlib import Path
    led = Path(r["ledger_file"])
    rows = [json.loads(ln) for ln in led.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and all(x["live_submission_allowed"] is False for x in rows)
    assert all(x["decision_state"] == "SHADOW_DECISION" for x in rows)


# --------------------------------------------------------------------------- #
# Paper mode gating
# --------------------------------------------------------------------------- #
def test_paper_requires_shadow_first(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True, fresh_source=True)
    from btc5m.venues.kalshi.paper_experiment import run_experiment
    r = run_experiment(cfg, series="KXBTC15M", mode="paper", limit=10)
    assert r["status"] == "ABORTED" and "PAPER_REQUIRES_SHADOW_FIRST" in r["abort_reason"]
    assert r["live_submission_allowed"] is False


def test_paper_not_ready_when_source_stale(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True, fresh_source=False)
    from btc5m.venues.kalshi.paper_experiment import run_experiment
    # skip the shadow-first guard to isolate the source-freshness gate
    r = run_experiment(cfg, series="KXBTC15M", mode="paper", limit=10, skip_shadow_warning=True)
    assert r["status"] == "ABORTED" and "PAPER_NOT_READY" in r["abort_reason"]


def test_paper_runs_when_ready_and_never_emits_stale_candidate(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True, fresh_source=True)
    from btc5m.venues.kalshi.paper_experiment import run_experiment
    r = run_experiment(cfg, series="KXBTC15M", mode="paper", limit=20, skip_shadow_warning=True)
    assert r["status"] in ("COMPLETED", "ABORTED")
    assert r["live_submission_allowed"] is False
    for d in (r.get("summary", {}).get("decisions_by_state") or {}):
        assert d != "LIVE"


# --------------------------------------------------------------------------- #
# Fill simulation + abort criteria (unit)
# --------------------------------------------------------------------------- #
def test_simulate_paper_fills_settles_vs_label():
    from btc5m.venues.kalshi.fees import KalshiFeeModel
    from btc5m.venues.kalshi.paper_experiment import simulate_paper_fills
    decisions = [
        {"decision_state": "PAPER_CANDIDATE", "selected_side": "YES", "ticker": "KX-0",
         "executable_yes_price": 0.40, "executable_no_price": 0.60, "label_yes_resolved": 1},
        {"decision_state": "PAPER_CANDIDATE", "selected_side": "NO", "ticker": "KX-1",
         "executable_yes_price": 0.55, "executable_no_price": 0.45, "label_yes_resolved": 1},  # NO loses
        {"decision_state": "WATCH", "selected_side": None, "ticker": "KX-2"},
    ]
    f = simulate_paper_fills(decisions, KalshiFeeModel(), size=1.0)
    assert f["n_fills"] == 2 and f["distinct_windows"] == 2 and f["open_positions"] == 0
    assert all(x["live_submission_allowed"] is False for x in f["fills"])


def test_abort_on_unexpected_live(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    monkeypatch.setattr(type(cfg), "live_blockers", lambda self: [])   # live permitted -> abort
    from btc5m.venues.kalshi.paper_experiment import abort_reasons
    a = abort_reasons(cfg, decisions=[], fills={}, error=None, promo_valid=True)
    assert "UNEXPECTED_LIVE_PERMITTED" in a


def test_abort_on_model_error_and_loss(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import abort_reasons
    a = abort_reasons(cfg, decisions=[], fills={"net_pnl_cents": -999.0, "max_drawdown_cents": 999.0},
                      error="ValueError: boom", promo_valid=True)
    assert any(x.startswith("RUNTIME_ERROR") for x in a)
    assert "MAX_DAILY_PAPER_LOSS_EXCEEDED" in a and "MAX_DRAWDOWN_EXCEEDED" in a


def test_abort_on_live_submission_flag(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import abort_reasons
    a = abort_reasons(cfg, decisions=[{"live_submission_allowed": True}], fills={}, error=None, promo_valid=True)
    assert "UNEXPECTED_LIVE_SUBMISSION_FLAG" in a


# --------------------------------------------------------------------------- #
# Status / report / safety
# --------------------------------------------------------------------------- #
def test_status_and_report_after_shadow(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import report, run_experiment, status
    run_experiment(cfg, series="KXBTC15M", mode="shadow", limit=10)
    st = status(cfg, series="KXBTC15M")
    assert st["status"] == "COMPLETED" and st["mode"] == "shadow"
    assert st["live_safety"]["live_submission_allowed"] is False
    rep = report(cfg, series="KXBTC15M")
    from pathlib import Path
    assert Path(rep["report_file"]).exists()
    body = Path(rep["report_file"]).read_text(encoding="utf-8")
    assert "live_submission_allowed: false" in body.lower()      # safety line present
    assert "Recommendation" in body and "Source health" in body  # report content present


def test_stop_writes_flag(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import stop
    r = stop(cfg, series="KXBTC15M", reason="manual")
    from pathlib import Path
    assert Path(r["stop_flag"]).exists() and r["live_submission_allowed"] is False


def test_runtime_surfaces_and_enforces_feature_row_age(tmp_path, monkeypatch):
    # the fixture's feature rows are far in the past (as_of ~ base) -> stale wall-clock.
    cfg = _setup(tmp_path, monkeypatch, promote=True, fresh_source=True)
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="paper", limit=10,
                             enforce_feature_row_age=True)
    assert ev["status"] == "OK" and ev["enforce_feature_row_age"] is True
    # wall-clock age is surfaced (large == evaluating STALE stored rows)
    assert ev["stalest_feature_row_age_ms"] is not None and ev["stalest_feature_row_age_ms"] > 1_000_000
    assert all(d.get("feature_row_age_ms") is not None for d in ev["decisions"])
    # no PAPER_CANDIDATE can survive on stale feature rows when enforcing
    assert ev["paper_candidates"] == 0
    for d in ev["decisions"]:
        assert d["decision_state"] != "PAPER_CANDIDATE" and d["live_submission_allowed"] is False


# --------------------------------------------------------------------------- #
# Live loop: --minutes is respected; continuously samples FRESH rows (deduped)
# --------------------------------------------------------------------------- #
def _write_live_feature_rows(tmp_path, tickers, *, age_ms=1000):
    """Append today-dated (newest) FRESH feature rows the live loop will pick up."""
    from btc5m.timeutils import now_ms
    d = tmp_path / "features"; d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    now = now_ms()
    rows = []
    for tk in tickers:
        rows.append({"market_ticker": tk, "as_of_ms": now - age_ms, "close_ms": now + 600_000,
                     "seconds_to_close": 600.0, "book_ok": True, "has_orderbook": True, "has_underlying": True,
                     "yes_ask": 0.42, "no_ask": 0.60, "yes_spread": 0.02, "no_spread": 0.02,
                     "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": 500,
                     "coinbase_feed_age_ms": 1000, "binance_feed_age_ms": 1000,
                     "coinbase_stale": False, "binance_stale": False,
                     "reference_start_price": 70000.0, "reference_price": 70010.0,
                     "distance_to_start": 50.0, "spot_sigma_per_sqrt_s": 1e-4,
                     "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4, "feature_set_version": 3})
    with (d / f"kalshi_feature_rows-{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_live_shadow_loops_until_max_iterations_and_dedups(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    _write_live_feature_rows(tmp_path, ["LK-0", "LK-1", "LK-2"])
    from btc5m.venues.kalshi.paper_runtime import run_live_shadow
    clock = {"t": 0.0}
    r = run_live_shadow(cfg, series="KXBTC15M", minutes=10, mode="shadow", poll_interval=1.0,
                        limit=25, max_iterations=4, sleep=lambda *_: clock.__setitem__("t", clock["t"] + 1),
                        monotonic=lambda: clock["t"])
    assert r["live_loop"] is True and r["iterations"] == 4      # looped (not single pass)
    assert r["samples"] == 3                                    # 3 distinct rows, deduped across iters
    assert r["paper_candidates"] == 0                           # shadow never emits a candidate
    assert set(r["decisions_by_state"]).issubset({"SHADOW_DECISION"})
    assert all(d["live_submission_allowed"] is False for d in r["decisions"])


def test_live_shadow_respects_time_budget(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    _write_live_feature_rows(tmp_path, ["LK-0"])
    from btc5m.venues.kalshi.paper_runtime import run_live_shadow
    state = {"t": 0.0}

    def mono():
        state["t"] += 100.0     # each call jumps 100s -> a 30s budget expires immediately
        return state["t"]

    r = run_live_shadow(cfg, series="KXBTC15M", minutes=0.5, mode="shadow", poll_interval=5.0,
                        sleep=lambda *_: None, monotonic=mono)
    assert r["live_loop"] is True and r["iterations"] >= 1
    assert r["samples"] == 1 and r["paper_candidates"] == 0


def test_experiment_minutes_runs_live_loop_no_fills(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    _write_live_feature_rows(tmp_path, ["LK-0", "LK-1"])
    from btc5m.venues.kalshi.paper_experiment import run_experiment, status
    r = run_experiment(cfg, series="KXBTC15M", mode="shadow", minutes=0.02, poll_interval=0.2, limit=25)
    assert r["status"] in ("COMPLETED", "ABORTED") and r["live_submission_allowed"] is False
    s = r["summary"]
    assert s["live_loop"] is True and s["iterations"] >= 1 and s["samples"] >= 1
    assert s["paper_fills"] == 0 and s["paper_candidates"] == 0   # shadow: no fills, no candidates
    st = status(cfg, series="KXBTC15M")
    assert st["status"] in ("COMPLETED", "ABORTED")


def test_experiment_no_minutes_is_single_batch_pass(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.venues.kalshi.paper_experiment import run_experiment
    r = run_experiment(cfg, series="KXBTC15M", mode="shadow", limit=20)   # no minutes
    assert r["status"] == "COMPLETED"
    assert r["summary"].get("live_loop") in (False, None)        # single pass, not a loop


# --------------------------------------------------------------------------- #
# Row SELECTION: shadow must evaluate ONLY executable active in-window rows.
# The collector records every discovered market (open/upcoming/closed) as a
# COLLECTION row; the shadow/paper DECISION must filter to executable rows.
# --------------------------------------------------------------------------- #
def _write_mixed_feature_rows(tmp_path, *, now):
    """Today-dated COLLECTION rows: 1 active-executable + upcoming/no-book/no-ref/closed."""
    d = tmp_path / "features"; d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")

    def base(tk, **over):
        r = {"market_ticker": tk, "as_of_ms": now - 1000, "close_ms": now + 600_000,
             "seconds_to_close": 600.0, "book_ok": True, "has_orderbook": True, "has_underlying": True,
             "yes_ask": 0.42, "no_ask": 0.60, "yes_spread": 0.02, "no_spread": 0.02,
             "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": 500,
             "coinbase_feed_age_ms": 1000, "binance_feed_age_ms": 1000,
             "coinbase_stale": False, "binance_stale": False,
             "reference_start_price": 70000.0, "reference_price": 70010.0,
             "distance_to_start": 50.0, "spot_sigma_per_sqrt_s": 1e-4,
             "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4, "feature_set_version": 3}
        r.update(over); return r

    rows = [
        base("ACTIVE-EXEC"),                                                       # eligible
        base("UPCOMING", seconds_to_close=1500.0, close_ms=now + 1_500_000,        # not yet open
             book_ok=False, yes_ask=None, no_ask=None, reference_start_price=None,
             yes_ask_size=0.0, no_ask_size=0.0),                                    # -> OUTSIDE_DECISION_WINDOW
        base("NOBOOK", book_ok=False, yes_ask=None, no_ask=None),                  # active -> MISSING_BOOK
        base("NOREF", reference_start_price=None),                                 # active+book -> MISSING_START_REFERENCE
        base("CLOSED", seconds_to_close=-5.0, close_ms=now - 5_000),               # -> MARKET_CLOSED
    ]
    with (d / f"kalshi_feature_rows-{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return rows


def _run_shadow_once(cfg, *, now, poll_interval=1.0):
    """One deterministic shadow poll over the latest feature rows at a fixed wall-clock ``now``."""
    from btc5m.venues.kalshi.paper_runtime import run_live_shadow
    clock = {"t": 0.0}
    return run_live_shadow(cfg, series="KXBTC15M", minutes=10, mode="shadow",
                           poll_interval=poll_interval, max_iterations=1, now_fn=lambda: now,
                           sleep=lambda *_: clock.__setitem__("t", clock["t"] + 1),
                           monotonic=lambda: clock["t"])


def test_shadow_excludes_upcoming_rows(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    now = 1_780_600_000_000
    _write_mixed_feature_rows(tmp_path, now=now)
    r = _run_shadow_once(cfg, now=now)
    scored = {d["ticker"] for d in r["decisions"]}
    assert "UPCOMING" not in scored                              # upcoming never scored
    assert "OUTSIDE_DECISION_WINDOW" in r["rejected_before_scoring_by_reason"]
    assert r["executable_rows"] == 1 and r["rows_eligible_for_scoring"] == 1


def test_shadow_counts_but_does_not_score_missing_book_or_reference(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    now = 1_780_600_000_000
    _write_mixed_feature_rows(tmp_path, now=now)
    r = _run_shadow_once(cfg, now=now)
    scored = {d["ticker"] for d in r["decisions"]}
    assert {"NOBOOK", "NOREF"}.isdisjoint(scored)               # counted but NOT scored
    br = r["rejected_before_scoring_by_reason"]
    assert br.get("MISSING_BOOK", 0) >= 1 and br.get("MISSING_START_REFERENCE", 0) >= 1
    assert r["rows_read"] == 5 and r["rejected_before_scoring"] == 4


def test_shadow_selects_active_executable_rows(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, promote=True)
    now = 1_780_600_000_000
    _write_mixed_feature_rows(tmp_path, now=now)
    r = _run_shadow_once(cfg, now=now)
    assert r["samples"] == 1                                    # only the executable active row scored
    assert [d["ticker"] for d in r["decisions"]] == ["ACTIVE-EXEC"]
    assert all(d["decision_state"] == "SHADOW_DECISION" for d in r["decisions"])
    assert r["active_window_rows"] == 3 and r["paper_candidates"] == 0
    assert r["book_backed_rows"] == 3 and r["start_reference_rows"] == 3


def test_check_live_disabled_passes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, promote=True)
    from btc5m.cli import main
    assert main(["check-live-disabled"]) == 0
