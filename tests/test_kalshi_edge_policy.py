"""Confidence-aware edge threshold / reservation-price policy (paper-only).

Covers edge formulas, conservative YES/NO probability bounds, Wilson calibration
intervals, dynamic required edge, reservation price, policy integration gates, and
safety (no live, no promotion). Offline; no orders.
"""

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.edge_policy import (
    EdgeInputs, EdgePolicyConfig, conservative_continue_ev, evaluate_edge,
)
from btc5m.venues.kalshi.uncertainty import (
    build_calibration_buckets, calibration_uncertainty, lookup_bucket,
    wilson_interval, z_for_confidence,
)

FM = KalshiFeeModel()
CFG = EdgePolicyConfig()  # min_raw 5c, min_final 2c, base_profit 2c, fixed_buf 3c, conf 0.80


def _inp(**over):
    base = dict(p_yes_hat=0.80, p_yes_lower=0.74, p_yes_upper=0.86, yes_ask=0.40, no_ask=0.62,
                yes_ask_size=50, no_ask_size=50, seconds_to_close=300, model_calibrated=True,
                model_tradable=True, backtest_valid=True)
    base.update(over)
    return EdgeInputs(**base)


# --------------------------------------------------------------------------- #
# Uncertainty primitives
# --------------------------------------------------------------------------- #
def test_z_and_wilson():
    assert z_for_confidence(0.80) == pytest.approx(1.2816, abs=1e-3)
    assert z_for_confidence(0.95) == pytest.approx(1.9600, abs=1e-3)
    lo, hi = wilson_interval(5, 10, confidence=0.80)
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    lo2, hi2 = wilson_interval(50, 100, confidence=0.80)
    assert (hi2 - lo2) < (hi - lo)   # more samples -> tighter interval


def test_calibration_bucket_lookup_and_low_n():
    y = [1, 0, 1, 1, 0, 1]
    p = [0.62, 0.63, 0.61, 0.64, 0.66, 0.62]
    buckets = build_calibration_buckets(y, p)
    b = lookup_bucket(buckets, 0.62)
    assert b is not None and b.lo == pytest.approx(0.6)
    cu = calibration_uncertainty(0.62, "YES", buckets, min_bucket_n=30)
    assert not cu.available and cu.reason == "CALIBRATION_BUCKET_TOO_SMALL"


# --------------------------------------------------------------------------- #
# Conservative probability bounds (Part B)
# --------------------------------------------------------------------------- #
def test_no_bound_is_one_minus_yes_upper():
    d = evaluate_edge(_inp(p_yes_hat=0.20, p_yes_lower=0.14, p_yes_upper=0.28,
                           yes_ask=0.62, no_ask=0.30), CFG, FM)
    # NO is the good side; conservative NO = 1 - p_yes_upper = 0.72 (NOT 1 - lower)
    assert d.side == "NO"
    assert d.p_no_lower == pytest.approx(1 - 0.28)
    assert d.conservative_p == pytest.approx(0.72)


def test_yes_bound_used_for_yes():
    d = evaluate_edge(_inp(), CFG, FM)
    assert d.side == "YES" and d.conservative_p == pytest.approx(0.74)
    # model uncertainty buffer = p_hat - conservative bound
    assert d.model_uncertainty_buffer_cents == pytest.approx((0.80 - 0.74) * 100, abs=1e-6)


# --------------------------------------------------------------------------- #
# Edge formulas + reservation (Parts A, E)
# --------------------------------------------------------------------------- #
def test_edge_chain_and_reservation():
    d = evaluate_edge(_inp(p_yes_hat=0.80, p_yes_lower=0.74, yes_ask=0.40), CFG, FM)
    fee = FM.per_contract_fee(0.40)
    # conservative_raw = 0.74 - 0.40 = 0.34 ; cost = 0.34 - fee ; final = cost - 0.02(min profit)
    assert d.conservative_raw_edge_cents == pytest.approx((0.74 - 0.40) * 100, abs=1e-6)
    assert d.cost_adjusted_edge_cents == pytest.approx((0.34 - fee) * 100, abs=1e-6)
    assert d.final_policy_edge_cents == pytest.approx((0.34 - fee - 0.02) * 100, abs=1e-6)
    # reservation: max_acceptable = ask + final ; ask <= max_acceptable -> passes
    assert d.max_acceptable_price == pytest.approx(0.40 + d.final_policy_edge_cents / 100, abs=1e-6)
    assert d.state == "EDGE_OK"


def test_raw_edge_alone_is_insufficient():
    # raw point edge is 10c, but a wide downside bound kills the conservative edge
    d = evaluate_edge(_inp(p_yes_hat=0.40, p_yes_lower=0.31, p_yes_upper=0.49, yes_ask=0.30), CFG, FM)
    assert d.raw_edge_cents == pytest.approx(10.0, abs=1e-6)
    assert d.state != "EDGE_OK"   # final edge fails after the conservative bound + fees


def test_price_above_reservation_rejected():
    d = evaluate_edge(_inp(p_yes_hat=0.60, p_yes_lower=0.58, p_yes_upper=0.62, yes_ask=0.57,
                           no_ask=0.45), CFG, FM)
    assert "PRICE_ABOVE_RESERVATION" in d.reason_codes and d.state != "EDGE_OK"


# --------------------------------------------------------------------------- #
# Missing bounds handling
# --------------------------------------------------------------------------- #
def test_missing_bounds_require_rejects():
    d = evaluate_edge(_inp(p_yes_lower=None, p_yes_upper=None), CFG, FM)
    assert "UNCERTAINTY_METHOD_UNAVAILABLE" in d.reason_codes and d.state != "EDGE_OK"


def test_missing_bounds_fixed_buffer_when_not_required():
    cfg = EdgePolicyConfig(require_confidence_bounds=False)
    d = evaluate_edge(_inp(p_yes_hat=0.80, p_yes_lower=None, p_yes_upper=None, yes_ask=0.30), cfg, FM)
    # conservative_p = 0.80 - fixed(0.03) = 0.77 -> still a large edge -> EDGE_OK
    assert d.conservative_p == pytest.approx(0.77, abs=1e-6) and d.state == "EDGE_OK"


# --------------------------------------------------------------------------- #
# Dynamic required edge increases with risk (Part D)
# --------------------------------------------------------------------------- #
def test_required_edge_increases_with_risk():
    base = evaluate_edge(_inp(), CFG, FM).required_edge_cents
    assert evaluate_edge(_inp(coinbase_stale=True), CFG, FM).required_edge_cents > base   # source buffer
    assert evaluate_edge(_inp(book_age_ms=900), CFG, FM).required_edge_cents > base       # stale quote
    assert evaluate_edge(_inp(sigma_per_sqrt_s=2e-4), CFG, FM).required_edge_cents > base  # high vol
    assert evaluate_edge(_inp(overtrading=True), CFG, FM).required_edge_cents > base       # overtrading


# --------------------------------------------------------------------------- #
# Policy-integration gates
# --------------------------------------------------------------------------- #
def test_uncalibrated_and_diagnostic_rejected():
    unc = evaluate_edge(_inp(model_calibrated=False), CFG, FM)
    assert unc.state == "REJECTED" and "UNCALIBRATED_MODEL_REJECTED" in unc.reason_codes
    diag = evaluate_edge(_inp(model_calibrated=True, model_tradable=False), CFG, FM)
    assert diag.state == "REJECTED" and "DIAGNOSTIC_MODEL_REJECTED" in diag.reason_codes


def test_disabled_policy_passes_through():
    d = evaluate_edge(_inp(), EdgePolicyConfig(enabled=False), FM)
    assert d.state == "DISABLED" and "EDGE_POLICY_DISABLED" in d.reason_codes


# --------------------------------------------------------------------------- #
# Lifecycle conservative continue EV (Part K)
# --------------------------------------------------------------------------- #
def test_conservative_continue_ev_uses_bounds():
    # YES uses lower bound; NO uses 1 - upper bound
    assert conservative_continue_ev(held_side="YES", p_yes_lower=0.60, p_yes_upper=0.80,
                                    total_cost=0.55) == pytest.approx(0.05)
    assert conservative_continue_ev(held_side="NO", p_yes_lower=0.20, p_yes_upper=0.40,
                                    total_cost=0.55) == pytest.approx((1 - 0.40) - 0.55)
    assert conservative_continue_ev(held_side="YES", p_yes_lower=None, p_yes_upper=0.8,
                                    total_cost=0.5) is None


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_no_live_no_promotion_no_flat_scanner():
    import btc5m.venues.kalshi.edge_policy as ep
    assert not any("scan" in n.lower() or "arb" in n.lower() for n in dir(ep))
    d = evaluate_edge(_inp(), CFG, FM)
    assert d.live_submission_allowed is False and d.paper_only is True


def test_cli_blocked_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    from btc5m.venues.kalshi.edge_policy_runtime import run_edge_policy_report
    r = run_edge_policy_report(cfg, series="KXBTC15M")
    assert r["status"] == "BLOCKED" and r["promoted"] is False and r["live_submission_allowed"] is False
