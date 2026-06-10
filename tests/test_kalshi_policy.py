"""Paper-candidate policy engine — EV/reservation math, validity + execution gates,
decision states, paper simulation, notifications, low-latency integration, safety.

All offline; stdlib only; no orders. PAPER_CANDIDATE must be unreachable without a
trained + calibrated + non-diagnostic + sufficiently-backtested model.
"""

import json

from btc5m.cli import main
from btc5m.config import PaperPolicyConfig, load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.policy import (
    BacktestValidity, CalibrationValidity, ExecutablePrices, ModelValidity, PolicyInput,
    Reason, SourceFreshness, evaluate_policy,
)
from btc5m.venues.kalshi.policy_runtime import maybe_notify, run_paper_policy_sim

PC = lambda **o: PaperPolicyConfig(enabled=True, **o)  # noqa: E731


def _valid(**over):
    pi = PolicyInput(
        series="KXBTC15M", ticker="KX", as_of_ts_ms=1000, market_open_ts_ms=0,
        market_close_ts_ms=900_000, seconds_to_close=300.0,
        calibrated_probability_yes=0.62, model_probability_yes=0.60, feature_schema_version=1,
        book_ok=True, has_underlying=True, reference_start_price=70_000.0,
        prices=ExecutablePrices(yes_bid=0.40, yes_ask=0.42, no_bid=0.56, no_ask=0.58,
                                yes_depth=100.0, no_depth=100.0, yes_spread=0.02, no_spread=0.02),
        freshness=SourceFreshness(book_age_ms=100, underlying_age_ms=100, deribit_age_ms=None),
        model_validity=ModelValidity(exists=True, trained=True, diagnostic_only=False,
                                     tradable_stamp=True, feature_schema_version=1),
        calibration_validity=CalibrationValidity(exists=True, valid=True, diagnostic_only=False),
        backtest_validity=BacktestValidity(exists=True, valid=True, windows=80))
    for k, v in over.items():
        setattr(pi, k, v)
    return pi


# --------------------------------------------------------------------------- #
# EV / reservation math
# --------------------------------------------------------------------------- #
def test_paper_candidate_when_all_gates_pass():
    d = evaluate_policy(_valid(), PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "PAPER_CANDIDATE" and d.selected_side == "YES"
    assert d.is_paper_candidate is True and d.live_submission_allowed is False
    assert d.order_intent is not None and d.order_intent.live_submission_allowed is False
    assert d.order_intent.limit_price == 0.42         # executable YES ask, not midpoint
    assert d.order_intent.opposite_side_ask == 0.58   # carried for Prompt 6 lock module
    assert "LIVE_CANDIDATE" not in d.decision_state


def test_reservation_and_edges_with_fees_and_buffer():
    fm = KalshiFeeModel()
    d = evaluate_policy(_valid(), PC(), fee_model=fm)
    fee = fm.per_contract_fee(0.42)
    assert abs(d.raw_edge_yes - (0.62 - 0.42)) < 1e-9
    assert abs(d.net_edge_yes - (0.20 - fee - 0.01)) < 1e-9     # buffer = 1c uncertainty + 0 slippage
    assert abs(d.max_acceptable_yes_price - (0.62 - fee - 0.01 - 0.02)) < 1e-9  # - min_net(2c)
    assert d.net_edge_yes < d.raw_edge_yes                       # fees reduce edge


def test_uncertainty_buffer_reduces_net_edge():
    d0 = evaluate_policy(_valid(), PC(uncertainty_buffer_cents=0), fee_model=KalshiFeeModel())
    d1 = evaluate_policy(_valid(), PC(uncertainty_buffer_cents=5), fee_model=KalshiFeeModel())
    assert d1.net_edge_yes < d0.net_edge_yes


def test_selected_side_is_higher_net_edge():
    # cheap NO (0.30) with low prob -> NO edge dominates
    d = evaluate_policy(_valid(calibrated_probability_yes=0.30,
                               prices=ExecutablePrices(yes_ask=0.72, no_ask=0.30,
                                                       yes_spread=0.02, no_spread=0.02,
                                                       yes_depth=100, no_depth=100)),
                        PC(), fee_model=KalshiFeeModel())
    assert d.selected_side == "NO" and d.decision_state == "PAPER_CANDIDATE"


def test_hard_high_prob_but_fair_price_is_not_a_trade():
    # model very confident YES (0.99) but priced fairly (ask 0.99) -> no edge -> WATCH, never candidate
    d = evaluate_policy(_valid(calibrated_probability_yes=0.99,
                               prices=ExecutablePrices(yes_ask=0.99, no_ask=0.02,
                                                       yes_spread=0.01, no_spread=0.01,
                                                       yes_depth=100, no_depth=100)),
                        PC(), fee_model=KalshiFeeModel())
    assert d.decision_state != "PAPER_CANDIDATE"


# --------------------------------------------------------------------------- #
# Validity gates
# --------------------------------------------------------------------------- #
def test_policy_disabled_blocks():
    d = evaluate_policy(_valid(), PaperPolicyConfig(enabled=False), fee_model=KalshiFeeModel())
    assert d.decision_state == "WATCH" and Reason.POLICY_DISABLED in d.reason_codes
    assert d.is_paper_candidate is False


def test_missing_and_untrained_model_watch():
    d = evaluate_policy(_valid(model_validity=ModelValidity(exists=False)), PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "WATCH" and Reason.MODEL_MISSING in d.reason_codes
    d2 = evaluate_policy(_valid(model_validity=ModelValidity(exists=True, trained=False, diagnostic_only=False)),
                         PC(), fee_model=KalshiFeeModel())
    assert d2.decision_state == "WATCH" and Reason.MODEL_UNTRAINED in d2.reason_codes


def test_diagnostic_model_rejected():
    d = evaluate_policy(_valid(model_validity=ModelValidity(exists=True, trained=True, diagnostic_only=True)),
                        PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "REJECTED" and Reason.MODEL_DIAGNOSTIC_ONLY in d.reason_codes


def test_calibrator_missing_watch_invalid_rejected():
    d = evaluate_policy(_valid(calibration_validity=CalibrationValidity(exists=False)),
                        PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "WATCH" and Reason.CALIBRATOR_MISSING in d.reason_codes
    d2 = evaluate_policy(_valid(calibration_validity=CalibrationValidity(exists=True, valid=False,
                                                                        diagnostic_only=True)),
                         PC(), fee_model=KalshiFeeModel())
    assert d2.decision_state == "REJECTED" and Reason.CALIBRATOR_INVALID in d2.reason_codes


def test_backtest_missing_watch_insufficient_rejected():
    d = evaluate_policy(_valid(backtest_validity=BacktestValidity(exists=False)),
                        PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "WATCH" and Reason.BACKTEST_MISSING in d.reason_codes
    d2 = evaluate_policy(_valid(backtest_validity=BacktestValidity(exists=True, valid=True, windows=10)),
                         PC(), fee_model=KalshiFeeModel())   # windows 10 < 60
    assert d2.decision_state == "REJECTED" and Reason.BACKTEST_INSUFFICIENT in d2.reason_codes


def test_feature_schema_mismatch_rejected():
    d = evaluate_policy(_valid(feature_schema_version=99), PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "REJECTED" and Reason.FEATURE_SCHEMA_MISMATCH in d.reason_codes


# --------------------------------------------------------------------------- #
# Execution gates
# --------------------------------------------------------------------------- #
def test_execution_gates_reject():
    fm = KalshiFeeModel()
    assert Reason.STALE_BOOK in evaluate_policy(
        _valid(freshness=SourceFreshness(book_age_ms=5000, underlying_age_ms=100)), PC(), fee_model=fm).reason_codes
    assert Reason.STALE_UNDERLYING in evaluate_policy(
        _valid(freshness=SourceFreshness(book_age_ms=100, underlying_age_ms=9000)), PC(), fee_model=fm).reason_codes
    assert Reason.WIDE_SPREAD in evaluate_policy(
        _valid(prices=ExecutablePrices(yes_ask=0.42, no_ask=0.58, yes_spread=0.20, no_spread=0.20,
                                       yes_depth=100, no_depth=100)), PC(), fee_model=fm).reason_codes
    assert Reason.INSUFFICIENT_DEPTH in evaluate_policy(
        _valid(prices=ExecutablePrices(yes_ask=0.42, no_ask=0.58, yes_spread=0.02, no_spread=0.02,
                                       yes_depth=0.0, no_depth=0.0)), PC(), fee_model=fm).reason_codes
    assert Reason.TOO_CLOSE_TO_CLOSE in evaluate_policy(
        _valid(seconds_to_close=1.0), PC(), fee_model=fm).reason_codes
    assert Reason.MAX_OPEN_POSITIONS in evaluate_policy(
        _valid(current_open_positions=5), PC(), fee_model=fm).reason_codes
    assert Reason.RISK_BLOCKED in evaluate_policy(
        _valid(risk_blocked=True), PC(), fee_model=fm).reason_codes


def test_deribit_stale_soft_vs_hard():
    fresh_required = PC(require_deribit_fresh=True, max_deribit_age_ms=180_000)
    d = evaluate_policy(_valid(freshness=SourceFreshness(book_age_ms=100, underlying_age_ms=100,
                                                         deribit_age_ms=5_000_000)),
                        fresh_required, fee_model=KalshiFeeModel())
    assert d.decision_state == "REJECTED" and Reason.STALE_DERIBIT in d.reason_codes
    soft = PC(require_deribit_fresh=False)
    d2 = evaluate_policy(_valid(freshness=SourceFreshness(book_age_ms=100, underlying_age_ms=100,
                                                          deribit_age_ms=5_000_000)),
                         soft, fee_model=KalshiFeeModel())
    assert d2.decision_state == "MANUAL_REVIEW" and Reason.STALE_DERIBIT in d2.reason_codes


def test_price_above_reservation_is_watch_not_candidate():
    # raw edge exists but below min_raw -> not eligible
    d = evaluate_policy(_valid(calibrated_probability_yes=0.43), PC(), fee_model=KalshiFeeModel())
    assert d.decision_state == "WATCH" and d.is_paper_candidate is False


# --------------------------------------------------------------------------- #
# Paper simulation + notifications + safety
# --------------------------------------------------------------------------- #
def test_paper_policy_sim_blocks_without_valid_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_PAPER_POLICY_ENABLED", "true")
    # minimal dataset so the runner has rows (still no model/calibrator/backtest)
    feats = (tmp_path / "features"); feats.mkdir(parents=True)
    labels = (tmp_path / "labels"); labels.mkdir(parents=True)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(4):
        close = base + (w + 1) * 900_000
        for i in range(4):
            fr.append({"market_ticker": f"KX-{w}", "series_ticker": "KXBTC15M", "has_orderbook": True,
                       "has_underlying": True, "has_start_reference": True, "book_ok": True,
                       "seconds_to_close": 200.0, "as_of_ms": close - 200_000, "close_ms": close,
                       "feature_set_version": 2, "yes_ask": 0.42, "no_ask": 0.60,
                       "reference_start_price": 70000.0, "yes_ask_size": 100.0, "no_ask_size": 100.0})
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL", "label_yes_resolved": w % 2})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text("\n".join(json.dumps(r) for r in fr) + "\n", "utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text("\n".join(json.dumps(r) for r in lr) + "\n", "utf-8")
    r = run_paper_policy_sim(load_config(mode="paper"), series="KXBTC15M", limit=50)
    assert r["paper_candidates"] == 0 and r["ledger_rows"] == 0
    assert r["live_submission_allowed"] is False
    assert "MODEL_NOT_TRAINED" in r["blockers"] or "MODEL_DIAGNOSTIC_ONLY" in r["blockers"]


def test_notifications_noop_safe(monkeypatch):
    monkeypatch.delenv("PUSHOVER_ENABLED", raising=False)
    cfg = load_config(mode="paper")
    cand = evaluate_policy(_valid(), PC(), fee_model=KalshiFeeModel())
    assert cand.decision_state == "PAPER_CANDIDATE"
    assert isinstance(maybe_notify(cfg, cand), bool)        # Noop, never raises
    watch = evaluate_policy(_valid(), PaperPolicyConfig(enabled=False), fee_model=KalshiFeeModel())
    assert maybe_notify(cfg, watch) is False                # don't notify on non-candidate


def test_low_latency_runtime_policy_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_PAPER_POLICY_ENABLED", "true")
    from btc5m.venues.kalshi.low_latency_runtime import run_hotpath_smoke
    res = run_hotpath_smoke(load_config(mode="paper"), seconds=0.0, synthetic=True, emit=lambda *_: None)
    # policy evaluated in the hot path; never a candidate (no valid model), never live
    assert "PAPER_CANDIDATE" not in res["decisions_by_state"]


def test_live_disabled_and_no_paper_candidate_from_diagnostic(monkeypatch):
    # diagnostic model can never produce a PAPER_CANDIDATE even with strong edge
    d = evaluate_policy(_valid(model_validity=ModelValidity(exists=True, trained=True, diagnostic_only=True)),
                        PC(), fee_model=KalshiFeeModel())
    assert not d.is_paper_candidate
    assert main(["check-live-disabled"]) == 0
