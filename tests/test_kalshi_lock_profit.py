"""Post-entry lock-profit module — units/math, position accounting, lock-vs-ride
decisions, order planning, ledger, notifications, and safety.

POST-ENTRY ONLY: the module manages an EXISTING paper position; it is never a flat
arb scanner. All offline; no orders; paper-only.
"""

import json

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.lock_profit import (
    KalshiPositionLot, KalshiPositionState, LockConfig, LockReason, cents_to_decimal,
    decimal_to_cents, evaluate_lock, normalize_price, validate_binary_price,
)
from btc5m.venues.kalshi.lock_runtime import (
    lock_event_from_decision, maybe_notify_lock, run_lock_dry_run, run_lock_sim, write_lock_ledger,
)

FM = KalshiFeeModel()
CFG = lambda **o: LockConfig(min_profit_cents=2, hard_profit_cents=5, **o)  # noqa: E731


def _pos(yes=0.0, no=0.0, yes_price=0.68, no_price=0.29, yes_fee=0.0, no_fee=0.0):
    lots = []
    if yes:
        lots.append(KalshiPositionLot("YES", yes, yes_price, yes_fee))
    if no:
        lots.append(KalshiPositionLot("NO", no, no_price, no_fee))
    return KalshiPositionState.from_lots(lots, series="KXBTC15M", ticker="KX")


def _ev(pos, *, opposite_ask, opposite_depth=10.0, book_ok=True, secs=300.0, p=None,
        cfg=None, mode="fok", allow_partial=False, book_age=100, **kw):
    return evaluate_lock(pos, opposite_ask=opposite_ask, opposite_depth=opposite_depth,
                         book_ok=book_ok, seconds_to_close=secs, book_age_ms=book_age,
                         calibrated_p_yes=p, config=cfg or CFG(), fee_model=FM, mode=mode,
                         allow_partial=allow_partial, **kw)


# --------------------------------------------------------------------------- #
# Units + math
# --------------------------------------------------------------------------- #
def test_price_unit_helpers():
    assert cents_to_decimal(5) == 0.05 and decimal_to_cents(0.05) == 5.0
    assert normalize_price(42, assume="cents") == 0.42 and normalize_price(0.42) == 0.42
    assert validate_binary_price(0.5) and not validate_binary_price(1.5) and not validate_binary_price("x")


def test_locked_profit_and_max_price_with_fees():
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24)   # held YES, lock NO @0.24
    fee = FM.per_contract_fee(0.24)
    assert abs(d.expected_locked_profit_per_pair - (1.0 - 0.68 - 0.24 - fee)) < 1e-9
    assert abs(d.max_acceptable_opposite_price - (1.0 - 0.68 - fee - 0.02)) < 1e-9  # - min(2c)
    # fee reduces locked profit
    d0 = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24, cfg=CFG())
    d0b = evaluate_lock(_pos(yes=1, yes_price=0.68), opposite_ask=0.24, opposite_depth=10,
                        book_ok=True, seconds_to_close=300, config=CFG(),
                        fee_model=KalshiFeeModel(rate=0.0))
    assert d0b.expected_locked_profit_per_pair > d0.expected_locked_profit_per_pair


def test_max_yes_price_after_no_entry():
    d = _ev(_pos(no=1, no_price=0.30), opposite_ask=0.20)   # held NO, lock YES @0.20
    fee = FM.per_contract_fee(0.20)
    assert d.existing_position_side == "NO" and d.side_to_buy == "YES"
    assert abs(d.max_acceptable_opposite_price - (1.0 - 0.30 - fee - 0.02)) < 1e-9


# --------------------------------------------------------------------------- #
# Position accounting
# --------------------------------------------------------------------------- #
def test_position_accounting():
    assert _pos(yes=3, no=1).naked_yes_quantity == 2 and _pos(yes=3, no=1).locked_pairs_quantity == 1
    assert _pos(no=2).naked_no_quantity == 2 and _pos(no=2).naked_yes_quantity == 0
    assert _pos(yes=2, no=2).naked_yes_quantity == 0 and _pos(yes=2, no=2).naked_no_quantity == 0
    # multiple YES fills -> weighted average cost
    p = KalshiPositionState.from_lots(
        [KalshiPositionLot("YES", 1, 0.60), KalshiPositionLot("YES", 3, 0.70)],
        series="KXBTC15M", ticker="KX")
    assert abs(p.yes_avg_price - 0.675) < 1e-9 and p.yes_quantity == 4


def test_realized_locked_profit():
    p = _pos(yes=2, no=2, yes_price=0.68, no_price=0.27)
    assert abs(p.realized_locked_profit - 2 * (1 - 0.68 - 0.27)) < 1e-9


# --------------------------------------------------------------------------- #
# Lock decisions
# --------------------------------------------------------------------------- #
def test_no_position_and_fully_locked():
    assert _ev(_pos(), opposite_ask=0.3).decision_state == "NO_POSITION"
    assert _ev(_pos(yes=2, no=2), opposite_ask=0.3).decision_state == "ALREADY_FULLY_LOCKED"


def test_hard_lock_full():
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24, p=None)   # locked ~6c >= hard 5c
    assert d.decision_state == "LOCK_FULL" and d.side_to_buy == "NO"
    assert LockReason.HARD_LOCK in d.reason_codes
    assert d.order_intent and d.order_intent.time_in_force == "fill_or_kill"
    assert d.order_intent.live_submission_allowed is False and d.live_submission_allowed is False
    assert d.naked_quantity_after == 0 and d.locked_quantity_after == 1


def test_reject_stale_book_and_depth_and_too_close():
    assert _ev(_pos(yes=1), opposite_ask=0.24, book_age=5000).decision_state == "REJECTED"
    assert LockReason.STALE_BOOK in _ev(_pos(yes=1), opposite_ask=0.24, book_age=5000).reason_codes
    assert LockReason.INSUFFICIENT_DEPTH in _ev(_pos(yes=1), opposite_ask=0.24, opposite_depth=0).reason_codes
    assert LockReason.TOO_CLOSE_TO_CLOSE in _ev(_pos(yes=1), opposite_ask=0.24, secs=1).reason_codes
    assert _ev(_pos(yes=1), opposite_ask=0.24, book_ok=False).decision_state == "REJECTED"


def test_lock_below_min_rides_with_model_else_watch():
    # NO too expensive -> locked < min; strong model edge -> RIDE
    d = _ev(_pos(yes=1, yes_price=0.50), opposite_ask=0.49, p=0.70)
    assert d.decision_state == "RIDE" and LockReason.RIDE_MODEL_EDGE in d.reason_codes
    # same, no model -> WATCH
    d2 = _ev(_pos(yes=1, yes_price=0.50), opposite_ask=0.49, p=None)
    assert d2.decision_state == "WATCH"


def test_hard_lock_overrides_strong_ride():
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24, p=0.99)   # ride EV huge but hard lock wins
    assert d.decision_state == "LOCK_FULL" and LockReason.HARD_LOCK in d.reason_codes


def test_conditional_zone_ride_vs_lock_by_model():
    # locked ~3c (min<=<hard); strong model -> RIDE
    assert _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.27, p=0.90).decision_state == "RIDE"
    # weak model edge -> CONDITIONAL LOCK
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.27, p=0.69)
    assert d.decision_state == "LOCK_FULL" and LockReason.CONDITIONAL_LOCK in d.reason_codes
    # no model in conditional zone -> WATCH (soft lock needs a model)
    assert _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.27, p=None).decision_state == "WATCH"


# --------------------------------------------------------------------------- #
# Order planning (FOK/IOC/partial)
# --------------------------------------------------------------------------- #
def test_partial_requires_ioc_and_allow_partial():
    pos = _pos(yes=5, yes_price=0.68)   # naked 5, only 2 depth -> needs partial
    # FOK can't partial
    assert _ev(pos, opposite_ask=0.24, opposite_depth=2, mode="fok").decision_state == "REJECTED"
    # IOC without allow_partial -> reject
    assert _ev(pos, opposite_ask=0.24, opposite_depth=2, mode="ioc", allow_partial=False).decision_state == "REJECTED"
    # IOC + allow_partial -> partial lock of 2
    d = _ev(pos, opposite_ask=0.24, opposite_depth=2, mode="ioc", allow_partial=True)
    assert d.decision_state == "LOCK_PARTIAL" and d.lock_quantity == 2
    assert d.order_intent.time_in_force == "immediate_or_cancel" and d.naked_quantity_after == 3


# --------------------------------------------------------------------------- #
# Ledger + notifications
# --------------------------------------------------------------------------- #
def test_lock_event_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24)
    ev = lock_event_from_decision(d, timestamp_ms=1234, model_probability_yes=0.6)
    assert ev["event_type"] == "PAPER_LOCK_FILLED" and ev["side"] == "NO"
    assert ev["live_submission_allowed"] is False and ev["locked_pairs_after"] == 1
    path = write_lock_ledger(load_config(mode="paper"), [ev])
    assert path and json.loads(open(path).read().splitlines()[0])["event_type"] == "PAPER_LOCK_FILLED"


def test_notifications_noop_safe(monkeypatch):
    monkeypatch.delenv("PUSHOVER_ENABLED", raising=False)
    cfg = load_config(mode="paper")
    lock = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24)
    assert isinstance(maybe_notify_lock(cfg, lock), bool)              # noop, never raises
    watch = _ev(_pos(yes=1, yes_price=0.50), opposite_ask=0.49, p=None)
    assert maybe_notify_lock(cfg, watch) is False                     # don't notify WATCH


# --------------------------------------------------------------------------- #
# Runtime + integration (NO_POSITION + full position->lock->settle)
# --------------------------------------------------------------------------- #
def test_dry_run_and_sim_no_position(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    assert run_lock_dry_run(cfg, series="KXBTC15M")["status"] == "NO_POSITION"
    assert run_lock_sim(cfg, series="KXBTC15M")["status"] == "NO_POSITION"


def test_lock_sim_reduces_risk_with_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    paper = (tmp_path / "paper"); paper.mkdir(parents=True)
    feats = (tmp_path / "features"); feats.mkdir(parents=True)
    labels = (tmp_path / "labels"); labels.mkdir(parents=True)
    close = 1_780_000_000_000 + 900_000
    # an open paper position: filled YES @0.68 in window KX-0 (settles NO -> ride would lose)
    paper_row = {"paper_fill_status": "simulated_filled", "selected_side": "YES", "ticker": "KX-0",
                 "size": 1, "selected_entry_price": 0.68, "expected_fee": 0.0,
                 "market_close_ts_ms": close}
    (paper / "kalshi_policy_paper_ledger-20260602.jsonl").write_text(json.dumps(paper_row) + "\n", "utf-8")
    # later book rows for KX-0 where NO is cheap (0.24) -> hard lock; label NO (0)
    fr = []
    for i in range(3):
        fr.append({"market_ticker": "KX-0", "series_ticker": "KXBTC15M", "has_orderbook": True,
                   "has_underlying": True, "has_start_reference": True, "book_ok": True,
                   "seconds_to_close": 200.0 - i * 10, "as_of_ms": close - (200 - i * 10) * 1000,
                   "close_ms": close, "feature_set_version": 2, "yes_ask": 0.78, "no_ask": 0.24,
                   "reference_start_price": 70000.0, "yes_ask_size": 100.0, "no_ask_size": 100.0})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text("\n".join(json.dumps(r) for r in fr) + "\n", "utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        json.dumps({"market_ticker": "KX-0", "label_source_status": "OFFICIAL", "label_yes_resolved": 0}) + "\n", "utf-8")

    r = run_lock_sim(load_config(mode="paper"), series="KXBTC15M", limit=10)
    assert r["status"] == "OK" and r["open_positions"] == 1
    res = r["results"][0]
    assert res["lock_triggered"] is True and res["lock_state"] == "LOCK_FULL"
    # ride loses the naked YES (label NO); lock secures the guaranteed profit -> better + less risk
    assert res["lock_pnl"] > res["ride_pnl"]
    assert r["summary"]["pnl_with_lock"] > r["summary"]["pnl_no_lock"]
    assert r["summary"]["risk_reduction_contracts"] == 1


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_no_flat_arb_scanner_and_live_disabled():
    # no command name suggests a flat arbitrage scanner
    assert not any("arb" in name.lower() for name in _COMMANDS)
    assert "kalshi-lock-dry-run" in _COMMANDS and "kalshi-lock-sim" in _COMMANDS
    # lock decision/intents never allow live submission
    d = _ev(_pos(yes=1, yes_price=0.68), opposite_ask=0.24)
    assert d.live_submission_allowed is False and d.order_intent.live_submission_allowed is False
    assert main(["check-live-disabled"]) == 0
