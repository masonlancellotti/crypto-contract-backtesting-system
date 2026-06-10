"""Post-entry position lifecycle manager (paper-only; never live).

Covers price units, position state, same-leg sell value, opposite-leg lock value,
continue EV, the unified ride/sell/lock/risk-exit decision policy, order intents,
ledger events, and safety (no flat arb, live disabled). All offline; no orders.
"""

import json

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.prices import (
    format_price_cents, price_unit_name, to_cents_price, to_decimal_price,
    validate_binary_price,
)
from btc5m.venues.kalshi.position_lifecycle import (
    ALREADY_FULLY_LOCKED, LOCK_WITH_OPPOSITE_LEG, NO_POSITION, REJECTED, RIDE,
    RISK_EXIT, SELL_SAME_LEG, WATCH, KalshiPositionLot, KalshiPositionState,
    LifecycleConfig, LifecycleInput, evaluate_lifecycle, same_leg_exit_value,
)
from btc5m.venues.kalshi.position_lifecycle_runtime import (
    lifecycle_event_from_decision, run_position_monitor_dry_run, write_lifecycle_ledger,
)

FM = KalshiFeeModel()
CFG = LifecycleConfig()  # defaults: min sell/lock 2c, hard 5c, ride_min 3c, force_lock<1c


def _pos(side="YES", qty=1.0, price=0.68, fee=0.0, ticker="KXBTC15M-T-30"):
    return KalshiPositionState.from_lots(
        [KalshiPositionLot(side=side, quantity=qty, price=price, fee_per_contract=fee)],
        series="KXBTC15M", ticker=ticker)


def _inp(**over):
    base = dict(book_ok=True, same_leg_bid=0.70, same_leg_bid_depth=10,
                opposite_leg_ask=0.40, opposite_leg_ask_depth=10, book_age_ms=100,
                seconds_to_close=300, spread_cents=2.0, source_healthy=True,
                model_valid=False, calibrated_p_yes=None)
    base.update(over)
    return LifecycleInput(**base)


# --------------------------------------------------------------------------- #
# Part A — price units
# --------------------------------------------------------------------------- #
def test_price_unit_conversions():
    assert price_unit_name() == "decimal"
    assert to_decimal_price(68, assume="cents") == pytest.approx(0.68)
    assert to_decimal_price(0.68) == pytest.approx(0.68)
    assert to_cents_price(0.68) == pytest.approx(68.0)
    assert to_cents_price(68, assume="cents") == pytest.approx(68.0)
    assert to_decimal_price(None) is None and to_decimal_price("x") is None


def test_price_validation_bounds():
    assert validate_binary_price(0.0) and validate_binary_price(1.0) and validate_binary_price(0.68)
    assert not validate_binary_price(-0.01) and not validate_binary_price(1.5)
    assert validate_binary_price(100, unit="cents") and not validate_binary_price(101, unit="cents")
    assert not validate_binary_price(True)   # bool rejected


def test_format_and_fee_in_decimal_unit():
    assert format_price_cents(0.68) == "68c"
    assert format_price_cents(0.681) == "68.1c"
    # exact fee uses decimal price: round_up_cent(0.07 * p * (1-p))
    assert FM.per_contract_fee(0.30) == pytest.approx(0.02)


# --------------------------------------------------------------------------- #
# Part B — position state
# --------------------------------------------------------------------------- #
def test_position_states():
    flat = KalshiPositionState.from_lots([], series="KXBTC15M", ticker="T")
    assert not flat.has_position
    y = _pos("YES", 2)
    assert y.naked_yes_quantity == 2 and y.naked_no_quantity == 0 and y.locked_pairs_quantity == 0
    n = _pos("NO", 3)
    assert n.naked_no_quantity == 3 and n.naked_yes_quantity == 0
    locked = KalshiPositionState.from_lots(
        [KalshiPositionLot("YES", 2, 0.60), KalshiPositionLot("NO", 2, 0.30)],
        series="KXBTC15M", ticker="T")
    assert locked.locked_pairs_quantity == 2 and locked.naked_yes_quantity == 0


def test_multiple_fills_weighted_average_cost():
    pos = KalshiPositionState.from_lots(
        [KalshiPositionLot("YES", 1, 0.60, 0.01), KalshiPositionLot("YES", 3, 0.70, 0.01)],
        series="KXBTC15M", ticker="T")
    assert pos.yes_quantity == 4
    assert pos.yes_avg_price == pytest.approx((0.60 + 3 * 0.70) / 4)   # 0.675
    assert pos.yes_total_cost == pytest.approx(0.675 + 0.01)


# --------------------------------------------------------------------------- #
# Part C — same-leg exit value
# --------------------------------------------------------------------------- #
def test_same_leg_sell_yes_and_no_profit_includes_fee():
    sell_y = same_leg_exit_value(_pos("YES", 1, 0.68), same_leg_bid=0.78, depth=5,
                                 book_ok=True, seconds_to_close=300, book_age_ms=100,
                                 config=CFG, fee_model=FM)
    assert sell_y.available and sell_y.held_side == "YES"
    assert sell_y.profit_per_contract == pytest.approx(0.78 - 0.68 - FM.per_contract_fee(0.78))
    sell_n = same_leg_exit_value(_pos("NO", 1, 0.30), same_leg_bid=0.40, depth=5,
                                 book_ok=True, seconds_to_close=300, book_age_ms=100,
                                 config=CFG, fee_model=FM)
    assert sell_n.available and sell_n.held_side == "NO"
    assert sell_n.profit_per_contract == pytest.approx(0.40 - 0.30 - FM.per_contract_fee(0.40))


def test_same_leg_sell_rejections():
    base = dict(same_leg_bid=0.78, depth=5, seconds_to_close=300, config=CFG, fee_model=FM)
    assert not same_leg_exit_value(_pos("YES"), book_ok=True, book_age_ms=9999, **base).available  # stale
    assert not same_leg_exit_value(_pos("YES"), book_ok=True, book_age_ms=100,
                                   **{**base, "depth": 0}).available                                # depth
    assert not same_leg_exit_value(_pos("YES"), book_ok=True, book_age_ms=100,
                                   **{**base, "same_leg_bid": None}).available                       # bid
    assert not same_leg_exit_value(_pos("YES"), book_ok=False, book_age_ms=100, **base).available    # book


# --------------------------------------------------------------------------- #
# Part E — continue EV
# --------------------------------------------------------------------------- #
def test_continue_ev_signs_and_missing_model():
    # naked YES: cev = p - cost
    d = evaluate_lifecycle(_pos("YES", 1, 0.68), _inp(model_valid=True, calibrated_p_yes=0.80,
                                                      opposite_leg_ask=0.40, same_leg_bid=0.69),
                           config=CFG, fee_model=FM)
    assert d.continue_ev_per_contract == pytest.approx(0.80 - 0.68)
    # naked NO: cev = (1-p) - cost
    d2 = evaluate_lifecycle(_pos("NO", 1, 0.30), _inp(model_valid=True, calibrated_p_yes=0.40,
                                                      same_leg_bid=0.40, opposite_leg_ask=0.65),
                            config=CFG, fee_model=FM)
    assert d2.continue_ev_per_contract == pytest.approx((1 - 0.40) - 0.30)
    # missing model -> no continue EV, ride not allowed
    d3 = evaluate_lifecycle(_pos("YES", 1, 0.68), _inp(calibrated_p_yes=None, same_leg_bid=0.69,
                                                       opposite_leg_ask=0.50), config=CFG, fee_model=FM)
    assert d3.continue_ev_per_contract is None and d3.action != RIDE


# --------------------------------------------------------------------------- #
# Part G — decision policy
# --------------------------------------------------------------------------- #
def test_no_position_and_fully_locked():
    assert evaluate_lifecycle(KalshiPositionState.from_lots([], series="K", ticker="T"),
                              _inp(), config=CFG, fee_model=FM).action == NO_POSITION
    locked = KalshiPositionState.from_lots(
        [KalshiPositionLot("YES", 1, 0.60), KalshiPositionLot("NO", 1, 0.30)],
        series="K", ticker="T")
    assert evaluate_lifecycle(locked, _inp(), config=CFG, fee_model=FM).action == ALREADY_FULLY_LOCKED


def test_hard_sell_beats_ride():
    # sell +8c (>=5c hard) even though model still likes it -> SELL
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.78, opposite_leg_ask=0.50,
                                model_valid=True, calibrated_p_yes=0.85), config=CFG, fee_model=FM)
    assert d.action == SELL_SAME_LEG and d.selected_order_intent.action == "sell"


def test_hard_lock_beats_ride():
    # lock +6c (>=5c hard); same-leg sell unprofitable -> LOCK
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.69, opposite_leg_ask=0.24,
                                model_valid=True, calibrated_p_yes=0.85), config=CFG, fee_model=FM)
    assert d.action == LOCK_WITH_OPPOSITE_LEG and d.selected_order_intent.action == "buy"
    assert d.selected_order_intent.side == "NO"


def test_ride_when_continue_ev_dominates_and_model_valid():
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.69, opposite_leg_ask=0.40,
                                model_valid=True, calibrated_p_yes=0.80), config=CFG, fee_model=FM)
    assert d.action == RIDE and d.continue_ev_per_contract == pytest.approx(0.12)


def test_conditional_sell_when_model_faded_and_sell_available():
    # cev +1c (weak, but not below force-exit 0c); sell +2c available -> conditional SELL
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.72, opposite_leg_ask=0.55,
                                model_valid=True, calibrated_p_yes=0.69), config=CFG, fee_model=FM)
    assert d.action == SELL_SAME_LEG


def test_conditional_lock_when_model_faded_and_lock_available():
    # cev +1c weak; same-leg unprofitable; lock +3c (>=min, <hard) -> LOCK
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.68, opposite_leg_ask=0.27,
                                model_valid=True, calibrated_p_yes=0.69), config=CFG, fee_model=FM)
    assert d.action == LOCK_WITH_OPPOSITE_LEG


def test_risk_exit_when_source_unsafe_and_sell_available():
    d = evaluate_lifecycle(_pos("YES", 1, 0.68),
                           _inp(same_leg_bid=0.70, opposite_leg_ask=0.50,
                                source_healthy=False, model_valid=True, calibrated_p_yes=0.80),
                           config=CFG, fee_model=FM)
    assert d.action == RISK_EXIT and d.selected_order_intent.action == "sell"


def test_watch_or_rejected_when_nothing_actionable():
    # invalid book -> nothing evaluable -> REJECTED
    d = evaluate_lifecycle(_pos("YES", 1, 0.68), _inp(book_ok=False), config=CFG, fee_model=FM)
    assert d.action in (WATCH, REJECTED)
    # fresh book, no model, no sell/lock profit -> WATCH (not a fabricated ride)
    d2 = evaluate_lifecycle(_pos("YES", 1, 0.68),
                            _inp(same_leg_bid=0.66, opposite_leg_ask=0.55, model_valid=False,
                                 calibrated_p_yes=None), config=CFG, fee_model=FM)
    assert d2.action in (WATCH, REJECTED) and d2.action != RIDE


# --------------------------------------------------------------------------- #
# Part H — order intents
# --------------------------------------------------------------------------- #
def test_order_intents_are_paper_fok_with_reservation_and_no_live():
    sell = evaluate_lifecycle(_pos("YES", 1, 0.68),
                              _inp(same_leg_bid=0.78, opposite_leg_ask=0.50, model_valid=True,
                                   calibrated_p_yes=0.85), config=CFG, fee_model=FM).selected_order_intent
    assert sell.time_in_force in ("fill_or_kill", "immediate_or_cancel")
    assert sell.max_acceptable_price == sell.limit_price          # no-chase reservation
    assert sell.paper_only is True and sell.live_submission_allowed is False
    lock = evaluate_lifecycle(_pos("YES", 1, 0.68),
                              _inp(same_leg_bid=0.69, opposite_leg_ask=0.24, model_valid=True,
                                   calibrated_p_yes=0.85), config=CFG, fee_model=FM).selected_order_intent
    assert lock.action == "buy" and lock.time_in_force == "fill_or_kill"
    assert lock.max_acceptable_price is not None and lock.live_submission_allowed is False


# --------------------------------------------------------------------------- #
# Part I — ledger
# --------------------------------------------------------------------------- #
def test_lifecycle_event_fields_and_no_position(tmp_path, monkeypatch):
    dec = evaluate_lifecycle(_pos("YES", 1, 0.68),
                             _inp(same_leg_bid=0.78, opposite_leg_ask=0.50, model_valid=True,
                                  calibrated_p_yes=0.85), config=CFG, fee_model=FM)
    ev = lifecycle_event_from_decision(dec, timestamp_ms=123)
    for k in ("event_type", "venue", "series", "ticker", "action", "side", "quantity", "price",
              "fee", "same_leg_exit_profit_per_contract", "lock_profit_per_pair",
              "continue_ev_per_contract", "model_probability_yes", "decision_reason_codes",
              "naked_yes_after", "naked_no_after", "locked_pairs_after", "live_submission_allowed"):
        assert k in ev
    assert ev["event_type"] == "PAPER_SELL_INTENT" and ev["live_submission_allowed"] is False

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    p = write_lifecycle_ledger(cfg, [ev])
    assert p and json.loads(open(p, encoding="utf-8").read().splitlines()[0])["live_submission_allowed"] is False
    # No paper positions -> NO_POSITION (never crashes).
    r = run_position_monitor_dry_run(cfg, series="KXBTC15M")
    assert r["status"] == "NO_POSITION" and r["open_positions"] == 0


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_safety_paper_only_no_flat_scan_no_live():
    # Lifecycle never acts on a flat position (no flat YES+NO arb scanning).
    flat = evaluate_lifecycle(KalshiPositionState.from_lots([], series="K", ticker="T"),
                              _inp(), config=CFG, fee_model=FM)
    assert flat.action == NO_POSITION and flat.selected_order_intent is None
    assert flat.live_submission_allowed is False
    assert CFG.live_submission_allowed is False
    # The module never opens a directional position from flat: there is no such entrypoint.
    import btc5m.venues.kalshi.position_lifecycle as pl
    assert not any("scan" in n.lower() or "arb" in n.lower() for n in dir(pl))
