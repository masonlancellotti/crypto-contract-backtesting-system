"""Calibration-uncertainty audit (READ-ONLY).

Covers the edge-formula recomputation (via the production evaluate_edge), the
calibration buffer = bias + sampling decomposition, ROW vs DISTINCT-WINDOW bucket
counts, the model-vs-market-implied comparison, near-pass extraction, the CLI command
on a fixture ledger, and the safety invariants (no live/paper, no promotion, no
artifact mutation). Offline; no orders; nothing is promoted.
"""

import json

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.edge_policy import EdgeInputs, EdgePolicyConfig, evaluate_edge
from btc5m.venues.kalshi.uncertainty import CalibrationBucket
from btc5m.venues.kalshi import uncertainty_audit as ua

FM = KalshiFeeModel()
ECFG = EdgePolicyConfig()


def _bucket(lo, hi, *, count, mean_pred, mean_actual, wl, wh):
    return CalibrationBucket(lo=lo, hi=hi, count=count, mean_pred=mean_pred,
                             mean_actual=mean_actual, wilson_low=wl, wilson_high=wh)


def _decision(**over):
    """A ledger row shaped like a real edge-blocked YES decision."""
    p_hat = over.get("calibrated_probability_yes", 0.33)
    ya = over.get("executable_yes_price", 0.23)
    na = over.get("executable_no_price", 0.78)
    raw = (p_hat - ya) * 100.0
    req = over.get("stored_required_edge_cents", 25.0)
    final = raw - req
    base = {
        "ticker": "KXBTC15M-26JUN050030-30", "as_of_ts_ms": 1780633145944,
        "seconds_to_close": 654.0, "selected_side": "YES",
        "model_probability_yes": 0.145, "calibrated_probability_yes": p_hat,
        "executable_yes_price": ya, "executable_no_price": na,
        "probability_lower": 0.19, "probability_upper": 0.22,
        "edge_raw_cents": raw, "edge_required_cents": req,
        "edge_final_cents": final, "edge_max_acceptable_price": ya + final / 100.0,
        "book_age_ms": 0, "coinbase_decision_stale": False, "binance_decision_stale": False,
        "reason_codes": ["PAPER_CANDIDATE_OK", "EDGE_POLICY_BLOCKED:REJECTED",
                         "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN", "PRICE_ABOVE_RESERVATION"],
    }
    base.update({k: v for k, v in over.items() if k != "stored_required_edge_cents"})
    return base


# --------------------------------------------------------------------------- #
# Cohort selection
# --------------------------------------------------------------------------- #
def test_is_edge_blocked_and_cohort():
    blocked = _decision()
    passed = _decision(reason_codes=["PAPER_CANDIDATE_OK", "EDGE_OK"])
    watch = _decision(reason_codes=["WATCH"])
    assert ua.is_edge_blocked(blocked) is True
    assert ua.is_edge_blocked(passed) is False
    assert ua.is_edge_blocked(watch) is False
    decs = [blocked, passed, watch]
    assert len(ua.select_cohort(decs, ua.COHORT_EDGE_BLOCKED)) == 1
    assert len(ua.select_cohort(decs, ua.COHORT_ALL)) == 3


# --------------------------------------------------------------------------- #
# Part A — edge recomputation via the production evaluate_edge
# --------------------------------------------------------------------------- #
def test_recompute_row_internal_identity_and_market_implied():
    buckets = [_bucket(0.3, 0.4, count=1000, mean_pred=0.358, mean_actual=0.206, wl=0.19, wh=0.22)]
    rec = ua.recompute_row(_decision(), buckets, ECFG, FM)
    # raw edge = (p_hat - ask) * 100
    assert rec["rc_raw_edge_cents"] == pytest.approx((0.33 - 0.23) * 100, abs=1e-6)
    # the fundamental chain identity: final == raw - required (recomputed)
    assert rec["rc_final_policy_edge_cents"] == pytest.approx(
        rec["rc_raw_edge_cents"] - rec["rc_required_edge_cents"], abs=1e-6)
    # reservation == ask + final/100
    assert rec["rc_reservation_price"] == pytest.approx(
        0.23 + rec["rc_final_policy_edge_cents"] / 100.0, abs=1e-6)
    # stored ledger identity holds
    assert rec["identity_final_eq_raw_minus_required"] is True
    assert rec["identity_reservation_eq_ask_plus_final"] is True
    # market-implied = ya / (ya + na); model sits above market for this row
    assert rec["market_implied_yes"] == pytest.approx(0.23 / (0.23 + 0.78), abs=1e-9)
    assert rec["model_minus_market_cents"] == pytest.approx((0.33 - 0.23 / 1.01) * 100, abs=1e-6)


def test_recompute_calibration_buffer_is_meanpred_minus_wilsonlow():
    # YES-side calibration buffer = mean_pred - wilson_low (Part B), via real evaluate_edge.
    buckets = [_bucket(0.3, 0.4, count=1000, mean_pred=0.358, mean_actual=0.206, wl=0.19, wh=0.22)]
    rec = ua.recompute_row(_decision(calibrated_probability_yes=0.33), buckets, ECFG, FM)
    assert rec["rc_calibration_uncertainty_buffer_cents"] == pytest.approx((0.358 - 0.19) * 100, abs=1e-6)
    # model-uncertainty buffer is ensemble disagreement vs the market (NOT the fixed 3c fallback)
    mkt = 0.23 / 1.01
    disp = abs(0.33 - mkt) / 2.0
    assert rec["rc_model_uncertainty_buffer_cents"] == pytest.approx(disp * 100, abs=1e-6)
    assert rec["rc_method"] == "ensemble_disagreement"


def test_no_side_conservative_bound_is_one_minus_yes_upper():
    # YES/NO conservative bound correctness (independent of the audit recompute).
    d = evaluate_edge(EdgeInputs(p_yes_hat=0.20, p_yes_lower=0.14, p_yes_upper=0.28,
                                 yes_ask=0.62, no_ask=0.30, yes_ask_size=50, no_ask_size=50,
                                 model_calibrated=True, model_tradable=True, backtest_valid=True),
                      ECFG, FM)
    assert d.side == "NO"
    assert d.conservative_p == pytest.approx(1 - 0.28)        # NOT 1 - lower
    assert d.p_no_lower == pytest.approx(1 - 0.28)


# --------------------------------------------------------------------------- #
# Parts B/C — ROW vs DISTINCT-WINDOW bucket accounting
# --------------------------------------------------------------------------- #
def test_bucket_window_stats_row_vs_window_divergence():
    # bucket [0.3,0.4): window A=10 rows all NO, windows B,C=1 row each YES.
    rows = ([{"calibrated_probability_yes": 0.35, "ticker": "A", "label_yes_resolved": 0}] * 10
            + [{"calibrated_probability_yes": 0.35, "ticker": "B", "label_yes_resolved": 1}]
            + [{"calibrated_probability_yes": 0.35, "ticker": "C", "label_yes_resolved": 1}])
    stats = ua.bucket_window_stats(rows)
    b = next(s for s in stats if s["bucket"] == "[0.3,0.4)")
    assert b["row_n"] == 12
    assert b["distinct_window_n"] == 3
    assert b["row_yes_rate"] == pytest.approx(2 / 12, abs=1e-4)
    assert b["window_yes_rate"] == pytest.approx(2 / 3, abs=1e-4)          # row vs window differ a lot
    assert b["top1_window_row_share"] == pytest.approx(10 / 12, abs=1e-3)
    # fewer windows than rows => window Wilson interval is WIDER (honest, not fake-tight)
    assert b["window_wilson_width"] > b["row_wilson_width"]


def test_bucket_buffer_decomposition_sums_to_buffer():
    rows = ([{"calibrated_probability_yes": 0.35, "ticker": f"w{i}", "label_yes_resolved": (i % 5 == 0)}
             for i in range(200)])
    stats = ua.bucket_window_stats(rows)
    b = next(s for s in stats if s["bucket"] == "[0.3,0.4)")
    # buffer(row) = bias(row) + sampling(row), all in cents (within rounding)
    assert b["calib_buffer_row_cents"] == pytest.approx(
        b["calib_bias_row_cents"] + b["calib_sampling_row_cents"], abs=0.02)
    assert b["distinct_window_n"] == 200    # every row its own window here


# --------------------------------------------------------------------------- #
# Near-pass extraction + end-to-end run on a fixture ledger
# --------------------------------------------------------------------------- #
def _write_ledger(path, decisions):
    with open(path, "w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")


def test_run_audit_on_fixture_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ledger = tmp_path / "fixture_decisions.jsonl"
    decs = [
        _decision(ticker="W1", calibrated_probability_yes=0.33, executable_yes_price=0.23,
                  stored_required_edge_cents=25.0),
        _decision(ticker="W2", calibrated_probability_yes=0.30, executable_yes_price=0.20,
                  stored_required_edge_cents=22.0),
        _decision(ticker="W3", reason_codes=["WATCH"]),     # not in cohort
    ]
    _write_ledger(ledger, decs)

    r = ua.run_uncertainty_audit(cfg, series="KXBTC15M", ledger=str(ledger),
                                 cohort="edge_blocked", top_n=20)
    assert r["status"] == "OK"
    assert r["n_decisions"] == 3 and r["n_cohort"] == 2
    assert r["live_submission_allowed"] is False
    # near-passes sorted by recomputed final edge, descending
    finals = [x["rc_final_policy_edge_cents"] for x in r["near_passes"]]
    assert finals == sorted(finals, reverse=True)
    # reports written ONLY under reports/edge
    for key in ("rows_csv", "bucket_csv", "near_passes_csv", "markdown"):
        p = r["reports"][key]
        assert (tmp_path / "reports" / "edge") == __import__("pathlib").Path(p).parent
        assert __import__("pathlib").Path(p).exists()
    # every recomputed row preserves the edge identity + the blocked reason codes (no weakening)
    rows = ua.load_decisions(ledger)
    cohort = ua.select_cohort(rows, "edge_blocked")
    for d in cohort:
        rec = ua.recompute_row(d, [], EdgePolicyConfig.from_app(cfg), KalshiFeeModel.from_config(cfg))
        assert rec["identity_final_eq_raw_minus_required"] is True
        assert "EDGE_POLICY_BLOCKED:REJECTED" in rec["stored_reason_codes"]


def test_run_audit_no_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = ua.run_uncertainty_audit(cfg, series="KXBTC15M", latest=True)
    assert r["status"] == "NO_LEDGER" and r["live_submission_allowed"] is False


# --------------------------------------------------------------------------- #
# Safety: no live/paper, no promotion, no artifact mutation
# --------------------------------------------------------------------------- #
def test_audit_is_read_only_and_changes_no_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ledger = tmp_path / "fixture_decisions.jsonl"
    _write_ledger(ledger, [_decision(ticker="W1")])
    res = ua.run_uncertainty_audit(cfg, series="KXBTC15M", ledger=str(ledger))
    data = tmp_path / "data"
    # the audit must NOT write any promotion manifest, model/calibrator artifact, paper
    # ledger, experiment manifest, or STOP flag (an empty resolver-created dir is harmless).
    assert not list(data.glob("**/kalshi_paper_promotion_manifest.json"))
    assert not list(data.glob("models/**/*.pkl"))
    assert not list(data.glob("paper/**/*ledger*.jsonl"))
    assert not list(data.glob("paper/**/kalshi_paper_experiment_*.json"))
    assert not list(data.glob("paper/**/STOP"))
    # reports are written ONLY under reports/edge (never under data/)
    assert res["live_submission_allowed"] is False
    assert all("reports" in p and "edge" in p for p in res["reports"].values())


def test_cli_command_registered():
    import btc5m.cli as c
    assert "kalshi-uncertainty-audit" in c._COMMANDS
    assert callable(c._COMMANDS["kalshi-uncertainty-audit"])


def test_check_live_disabled_still_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    # The audit never enables live; the live blockers remain intact.
    assert cfg.live_blockers()              # non-empty => live NOT permitted
    assert cfg.live_submission_allowed is False if hasattr(cfg, "live_submission_allowed") else True
