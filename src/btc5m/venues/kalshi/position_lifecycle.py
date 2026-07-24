"""Post-entry position lifecycle manager (paper-only; never live).

Given an EXISTING open paper position, decide the best action *right now* by
comparing three changing values:

    1. same-leg exit value     (sell the leg we hold at its executable bid)
    2. opposite-leg lock value  (buy the other leg to lock guaranteed profit)
    3. continue / ride EV        (hold to settlement, using the *latest* calibrated
                                  model probability — not the entry-time belief)

This is NOT an entry strategy and NOT a flat-position arbitrage scanner. It never
opens directional positions and never scans markets where we hold nothing. It
reuses the position accounting + opposite-leg lock math from :mod:`lock_profit`
and adds same-leg exit + a unified ride/sell/lock/risk-exit decision.

Internal unit is DECIMAL 0.0–1.0 (see :mod:`prices`); thresholds are configured in
cents. Every decision carries ``paper_only=True`` and ``live_submission_allowed=False``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .fees import KalshiFeeModel
from .lock_profit import (
    LOCK_FULL, LOCK_PARTIAL, KalshiPositionLot, KalshiPositionState, LockConfig, decimal_to_cents, evaluate_lock,
)
from .prices import format_price_cents

# Re-export accounting types so callers import everything lifecycle-related here.
__all__ = [
    "KalshiPositionLot", "KalshiPositionState", "LifecycleConfig", "LifecycleInput",
    "LifecycleDecision", "LifecycleOrderIntent", "SameLegExitOpportunity",
    "OppositeLegLockOpportunity", "ContinueEV", "same_leg_exit_value",
    "evaluate_lifecycle",
    "NO_POSITION", "ALREADY_FULLY_LOCKED", "HOLD", "RIDE", "SELL_SAME_LEG",
    "SELL_PARTIAL", "LOCK_WITH_OPPOSITE_LEG", "PARTIAL_LOCK", "RISK_EXIT",
    "WATCH", "REJECTED",
]

# ----- Lifecycle actions (NO live actions exist) ----------------------------- #
NO_POSITION = "NO_POSITION"
ALREADY_FULLY_LOCKED = "ALREADY_FULLY_LOCKED"
HOLD = "HOLD"
RIDE = "RIDE"
SELL_SAME_LEG = "SELL_SAME_LEG"
SELL_PARTIAL = "SELL_PARTIAL"
LOCK_WITH_OPPOSITE_LEG = "LOCK_WITH_OPPOSITE_LEG"
PARTIAL_LOCK = "PARTIAL_LOCK"
RISK_EXIT = "RISK_EXIT"
WATCH = "WATCH"
REJECTED = "REJECTED"


class LifecycleReason:
    OK = "OK"
    NO_POSITION = "NO_POSITION"
    ALREADY_FULLY_LOCKED = "ALREADY_FULLY_LOCKED"
    MODULE_DISABLED = "MODULE_DISABLED"
    HARD_SELL = "HARD_SELL"
    HARD_LOCK = "HARD_LOCK"
    CONDITIONAL_SELL = "CONDITIONAL_SELL"
    CONDITIONAL_LOCK = "CONDITIONAL_LOCK"
    SELL_BEATS_LOCK = "SELL_BEATS_LOCK"
    FORCE_EXIT_MODEL_FADED = "FORCE_EXIT_MODEL_FADED"
    FORCE_LOCK_MODEL_FADED = "FORCE_LOCK_MODEL_FADED"
    RIDE_MODEL_EDGE = "RIDE_MODEL_EDGE"
    RIDE_NO_BETTER_ACTION = "RIDE_NO_BETTER_ACTION"
    SELL_BELOW_MIN = "SELL_BELOW_MIN"
    LOCK_BELOW_MIN = "LOCK_BELOW_MIN"
    NO_MODEL_FOR_RIDE = "NO_MODEL_FOR_RIDE"
    SOURCE_UNSAFE_RISK_EXIT = "SOURCE_UNSAFE_RISK_EXIT"
    SOURCE_UNSAFE_NO_EXIT = "SOURCE_UNSAFE_NO_EXIT"
    MISSING_BOOK = "MISSING_BOOK"
    MISSING_BID = "MISSING_BID"
    STALE_BOOK = "STALE_BOOK"
    TOO_CLOSE_TO_CLOSE = "TOO_CLOSE_TO_CLOSE"
    WIDE_SPREAD = "WIDE_SPREAD"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    PARTIAL_NOT_ALLOWED = "PARTIAL_NOT_ALLOWED"
    NOTHING_ACTIONABLE = "NOTHING_ACTIONABLE"


# --------------------------------------------------------------------------- #
# Config (standalone mirror of config.LifecycleConfig; keeps math testable)
# --------------------------------------------------------------------------- #
@dataclass
class LifecycleConfig:
    enabled: bool = False
    paper_only: bool = True
    min_sell_profit_cents: float = 2.0
    hard_sell_profit_cents: float = 5.0
    min_lock_profit_cents: float = 2.0
    hard_lock_profit_cents: float = 5.0
    ride_min_edge_cents: float = 3.0
    force_exit_when_model_edge_below_cents: float = 0.0
    force_lock_when_model_edge_below_cents: float = 1.0
    allow_partial_exit: bool = False
    allow_partial_lock: bool = False
    default_tif: str = "fill_or_kill"
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_depth_contracts: float = 1.0
    min_seconds_to_close: int = 3
    max_spread_cents: float = 10.0
    notify: bool = True

    @classmethod
    def from_app(cls, config) -> "LifecycleConfig":
        c = getattr(config, "lifecycle", None)
        if c is None:
            return cls()
        return cls(**{f: getattr(c, f) for f in cls.__dataclass_fields__ if hasattr(c, f)})

    @property
    def live_submission_allowed(self) -> bool:
        return False

    def to_lock_config(self) -> LockConfig:
        """Map lifecycle settings onto the lock module's config for reuse."""
        return LockConfig(
            enabled=self.enabled, paper_only=True,
            min_profit_cents=self.min_lock_profit_cents,
            hard_profit_cents=self.hard_lock_profit_cents,
            allow_partial=self.allow_partial_lock,
            default_mode=("ioc" if self.allow_partial_lock else "fok"),
            max_book_age_ms=self.max_book_age_ms,
            max_underlying_age_ms=self.max_underlying_age_ms,
            min_depth_contracts=self.min_depth_contracts,
            min_seconds_to_close=self.min_seconds_to_close,
            ride_min_edge_cents=self.ride_min_edge_cents,
            force_when_model_edge_below_cents=self.force_lock_when_model_edge_below_cents,
            slippage_buffer_cents=0.0, require_underlying_fresh=False, notify=self.notify)


# --------------------------------------------------------------------------- #
# Opportunity / input / decision structures
# --------------------------------------------------------------------------- #
@dataclass
class SameLegExitOpportunity:
    available: bool
    held_side: Optional[str]                      # "YES" | "NO"
    exit_price: Optional[float]                    # executable same-leg BID (decimal)
    profit_per_contract: Optional[float]           # bid - total_cost - sell_fee (decimal)
    fee_per_contract: Optional[float]
    max_fillable_qty: float = 0.0
    partial: bool = False
    reason_codes: list = field(default_factory=list)


@dataclass
class OppositeLegLockOpportunity:
    available: bool
    lock_leg: Optional[str]                        # leg to BUY ("NO" if held YES)
    opposite_ask: Optional[float]
    max_acceptable_price: Optional[float]
    locked_profit_per_pair: Optional[float]
    lock_quantity: float = 0.0
    reason_codes: list = field(default_factory=list)


@dataclass
class ContinueEV:
    continue_ev_per_contract: Optional[float]      # p_win - total_cost (decimal)
    probability_of_win: Optional[float]
    probability_of_loss: Optional[float]
    max_loss_per_contract: Optional[float]         # the naked cost basis (lose it all)
    model_probability_yes: Optional[float]
    model_valid: bool
    calibration_status: Optional[str]
    model_version: Optional[str]


@dataclass
class LifecycleInput:
    current_ts_ms: Optional[int] = None
    same_leg_bid: Optional[float] = None
    same_leg_bid_depth: Optional[float] = None
    opposite_leg_ask: Optional[float] = None
    opposite_leg_ask_depth: Optional[float] = None
    book_ok: bool = False
    book_age_ms: Optional[int] = None
    underlying_age_ms: Optional[int] = None
    underlying_stale: bool = False
    seconds_to_close: Optional[float] = None
    spread_cents: Optional[float] = None
    calibrated_p_yes: Optional[float] = None
    model_valid: bool = False
    model_version: Optional[str] = None
    calibration_status: Optional[str] = None
    source_healthy: bool = True


@dataclass
class LifecycleOrderIntent:
    ticker: Optional[str]
    action: str                                    # "sell" | "buy"
    side: Optional[str]                            # "YES" | "NO"
    quantity: float
    limit_price: Optional[float]
    reservation_price: Optional[float]             # floor for sell / ceiling for buy
    time_in_force: str
    max_acceptable_price: Optional[float]
    expected_fee: Optional[float]
    expected_value: Optional[float]                # realized sell profit / locked profit
    reason_codes: list = field(default_factory=list)
    paper_only: bool = True
    live_submission_allowed: bool = False


@dataclass
class LifecycleDecision:
    action: str
    ticker: Optional[str]
    current_ts_ms: Optional[int]
    seconds_to_close: Optional[float]
    current_position_side: Optional[str]
    naked_quantity_before: float
    naked_quantity_after: float
    locked_pairs_before: float
    locked_pairs_after: float
    same_leg_exit_price: Optional[float]
    same_leg_exit_profit_per_contract: Optional[float]
    opposite_leg_ask: Optional[float]
    max_acceptable_opposite_price: Optional[float]
    lock_profit_per_pair: Optional[float]
    total_expected_lock_profit: Optional[float]
    continue_ev_per_contract: Optional[float]
    model_probability_yes: Optional[float]
    selected_order_intent: Optional[LifecycleOrderIntent]
    reason_codes: list
    human_summary: str
    paper_only: bool = True
    live_submission_allowed: bool = False


def _cents(x: Optional[float]) -> Optional[float]:
    return decimal_to_cents(x) if isinstance(x, (int, float)) else None


def _ge(a: Optional[float], b: float) -> bool:
    """a >= b with a tiny tolerance so cent thresholds aren't tripped by float noise."""
    return isinstance(a, (int, float)) and a >= b - 1e-9


# --------------------------------------------------------------------------- #
# Same-leg exit value (the new piece; the lock value is reused from lock_profit)
# --------------------------------------------------------------------------- #
def same_leg_exit_value(
    position: KalshiPositionState,
    *,
    same_leg_bid: Optional[float],
    depth: Optional[float],
    book_ok: bool,
    seconds_to_close: Optional[float],
    book_age_ms: Optional[int] = None,
    spread_cents: Optional[float] = None,
    config: LifecycleConfig = None,
    fee_model: Optional[KalshiFeeModel] = None,
    allow_partial: Optional[bool] = None,
) -> SameLegExitOpportunity:
    """Value of selling the naked leg we hold at its executable BID (never midpoint)."""
    cfg = config or LifecycleConfig()
    fee_model = fee_model or KalshiFeeModel()
    allow_partial = cfg.allow_partial_exit if allow_partial is None else allow_partial

    held = ("YES" if position.naked_yes_quantity > 0
            else "NO" if position.naked_no_quantity > 0 else None)
    if held is None:
        return SameLegExitOpportunity(False, None, None, None, None,
                                      reason_codes=[LifecycleReason.NO_POSITION])
    naked = position.naked_yes_quantity if held == "YES" else position.naked_no_quantity
    cost = position.yes_total_cost if held == "YES" else position.no_total_cost

    if not book_ok:
        return SameLegExitOpportunity(False, held, None, None, None,
                                      reason_codes=[LifecycleReason.MISSING_BOOK])
    if same_leg_bid is None:
        return SameLegExitOpportunity(False, held, None, None, None,
                                      reason_codes=[LifecycleReason.MISSING_BID])

    sell_fee = fee_model.per_contract_fee(same_leg_bid)
    profit = same_leg_bid - cost - sell_fee   # decimal per contract

    reasons: list[str] = []
    if book_age_ms is not None and book_age_ms > cfg.max_book_age_ms:
        reasons.append(LifecycleReason.STALE_BOOK)
    if seconds_to_close is not None and seconds_to_close < cfg.min_seconds_to_close:
        reasons.append(LifecycleReason.TOO_CLOSE_TO_CLOSE)
    if spread_cents is not None and spread_cents > cfg.max_spread_cents:
        reasons.append(LifecycleReason.WIDE_SPREAD)

    avail_qty = min(naked, depth or 0.0)
    partial = avail_qty < naked
    if avail_qty <= 0:
        reasons.append(LifecycleReason.INSUFFICIENT_DEPTH)
    elif partial and not allow_partial:
        reasons.append(LifecycleReason.PARTIAL_NOT_ALLOWED)

    available = not reasons and avail_qty > 0 and (not partial or allow_partial)
    return SameLegExitOpportunity(
        available=available, held_side=held, exit_price=same_leg_bid,
        profit_per_contract=profit, fee_per_contract=sell_fee,
        max_fillable_qty=avail_qty, partial=partial,
        reason_codes=reasons or [LifecycleReason.OK])


# --------------------------------------------------------------------------- #
# Unified lifecycle decision
# --------------------------------------------------------------------------- #
def evaluate_lifecycle(
    position: KalshiPositionState,
    inp: LifecycleInput,
    *,
    config: LifecycleConfig = None,
    fee_model: Optional[KalshiFeeModel] = None,
) -> LifecycleDecision:
    """Choose HOLD/RIDE/SELL/LOCK/PARTIAL/RISK_EXIT/WATCH for an existing position.

    Compares same-leg sell value vs opposite-leg lock value vs continue EV, applies
    freshness/depth/fee/time/risk gates, and reasons from the CURRENT calibrated
    model probability (``inp.calibrated_p_yes``) — never the entry-time belief.
    """
    cfg = config or LifecycleConfig()
    fee_model = fee_model or KalshiFeeModel()
    locked_before = position.locked_pairs_quantity
    naked_before = position.naked_yes_quantity + position.naked_no_quantity

    def decision(action, *, side=None, reasons, intent=None, summary=None,
                 sell=None, lock=None, cev=None, naked_after=None, locked_after=None):
        return LifecycleDecision(
            action=action, ticker=position.ticker, current_ts_ms=inp.current_ts_ms,
            seconds_to_close=inp.seconds_to_close, current_position_side=side,
            naked_quantity_before=naked_before,
            naked_quantity_after=(naked_before if naked_after is None else naked_after),
            locked_pairs_before=locked_before,
            locked_pairs_after=(locked_before if locked_after is None else locked_after),
            same_leg_exit_price=(sell.exit_price if sell else None),
            same_leg_exit_profit_per_contract=(sell.profit_per_contract if sell else None),
            opposite_leg_ask=(lock.current_opposite_ask if lock else None),
            max_acceptable_opposite_price=(lock.max_acceptable_opposite_price if lock else None),
            lock_profit_per_pair=(lock.lock_value_per_contract if lock else None),
            total_expected_lock_profit=(lock.expected_total_locked_profit if lock else None),
            continue_ev_per_contract=cev,
            model_probability_yes=inp.calibrated_p_yes,
            selected_order_intent=intent, reason_codes=list(reasons),
            human_summary=(summary or _summary(action, side, sell, lock, cev, reasons)),
            paper_only=True, live_submission_allowed=False)

    # 1) presence
    if not position.has_position:
        return decision(NO_POSITION, reasons=[LifecycleReason.NO_POSITION])
    if position.naked_yes_quantity == 0 and position.naked_no_quantity == 0:
        return decision(ALREADY_FULLY_LOCKED, reasons=[LifecycleReason.ALREADY_FULLY_LOCKED],
                        locked_after=locked_before)

    held = "YES" if position.naked_yes_quantity > 0 else "NO"
    naked = position.naked_yes_quantity if held == "YES" else position.naked_no_quantity

    # --- the three values --------------------------------------------------- #
    sell = same_leg_exit_value(
        position, same_leg_bid=inp.same_leg_bid, depth=inp.same_leg_bid_depth,
        book_ok=inp.book_ok, seconds_to_close=inp.seconds_to_close,
        book_age_ms=inp.book_age_ms, spread_cents=inp.spread_cents,
        config=cfg, fee_model=fee_model)
    lock = evaluate_lock(
        position, opposite_ask=inp.opposite_leg_ask, opposite_depth=inp.opposite_leg_ask_depth,
        book_ok=inp.book_ok, seconds_to_close=inp.seconds_to_close, book_age_ms=inp.book_age_ms,
        underlying_age_ms=inp.underlying_age_ms, underlying_stale=inp.underlying_stale,
        calibrated_p_yes=inp.calibrated_p_yes, config=cfg.to_lock_config(), fee_model=fee_model)
    cev = lock.continue_ev_per_contract  # single source: p_win - total_cost (or None)

    sell_c = _cents(sell.profit_per_contract) if sell.available else None
    lock_pp = lock.lock_value_per_contract
    lock_priceable = (lock.current_opposite_ask is not None
                      and lock.max_acceptable_opposite_price is not None
                      and lock.current_opposite_ask <= lock.max_acceptable_opposite_price + 1e-12
                      and lock.decision_state != "REJECTED")
    lock_c = _cents(lock_pp) if lock_priceable else None
    cev_c = _cents(cev)

    def sell_intent(qty, partial=False):
        tif = "immediate_or_cancel" if partial else cfg.default_tif
        return LifecycleOrderIntent(
            ticker=position.ticker, action="sell", side=held, quantity=qty,
            limit_price=sell.exit_price, reservation_price=sell.exit_price,
            time_in_force=tif, max_acceptable_price=sell.exit_price,
            expected_fee=(sell.fee_per_contract or 0.0) * qty,
            expected_value=(sell.profit_per_contract or 0.0) * qty,
            reason_codes=[], paper_only=True, live_submission_allowed=False)

    def lock_intent():
        li = lock.order_intent
        qty = li.quantity if li else lock.lock_quantity
        return LifecycleOrderIntent(
            ticker=position.ticker, action="buy", side=lock.side_to_buy, quantity=qty,
            limit_price=lock.current_opposite_ask, reservation_price=lock.max_acceptable_opposite_price,
            time_in_force=(li.time_in_force if li else cfg.default_tif),
            max_acceptable_price=lock.max_acceptable_opposite_price,
            expected_fee=(lock.expected_lock_fee or 0.0) * qty,
            expected_value=lock.expected_total_locked_profit,
            reason_codes=[], paper_only=True, live_submission_allowed=False)

    def sell_action(qty, base_reason, action_override=None):
        partial = qty < naked
        intent = sell_intent(qty, partial=partial)
        act = action_override or (SELL_PARTIAL if partial else SELL_SAME_LEG)
        extra = [LifecycleReason.INSUFFICIENT_DEPTH] if (partial and not action_override) else []
        return decision(act, side=held, reasons=[base_reason] + extra,
                        intent=intent, sell=sell, lock=lock, cev=cev,
                        naked_after=naked - qty, locked_after=locked_before)

    def lock_action(base_reason):
        qty = (lock.order_intent.quantity if lock.order_intent else lock.lock_quantity) or 0.0
        act = PARTIAL_LOCK if lock.decision_state == LOCK_PARTIAL else LOCK_WITH_OPPOSITE_LEG
        return decision(act, side=held, reasons=[base_reason], intent=lock_intent(),
                        sell=sell, lock=lock, cev=cev,
                        naked_after=naked - qty, locked_after=locked_before + qty)

    # 2) RISK EXIT — source/book/model unsafe: get flat if we can.
    if not inp.source_healthy:
        if sell.available:
            return sell_action(sell.max_fillable_qty,
                               LifecycleReason.SOURCE_UNSAFE_RISK_EXIT, action_override=RISK_EXIT)
        if lock.decision_state in (LOCK_FULL, LOCK_PARTIAL):
            return lock_action(LifecycleReason.SOURCE_UNSAFE_RISK_EXIT)
        return decision(WATCH, side=held, reasons=[LifecycleReason.SOURCE_UNSAFE_NO_EXIT],
                        sell=sell, lock=lock, cev=cev)

    # 3) HARD SELL — realize a large profit now.
    if sell.available and _ge(sell_c, cfg.hard_sell_profit_cents):
        return sell_action(sell.max_fillable_qty, LifecycleReason.HARD_SELL)
    # 4) HARD LOCK — guaranteed locked profit (works even without a model).
    if lock.decision_state in (LOCK_FULL, LOCK_PARTIAL) and _ge(lock_c, cfg.hard_lock_profit_cents):
        return lock_action(LifecycleReason.HARD_LOCK)

    # 5) FORCE on a faded model edge.
    if cev_c is not None and cev_c < cfg.force_exit_when_model_edge_below_cents \
            and sell.available and _ge(sell_c, cfg.min_sell_profit_cents):
        return sell_action(sell.max_fillable_qty, LifecycleReason.FORCE_EXIT_MODEL_FADED)
    if cev_c is not None and cev_c < cfg.force_lock_when_model_edge_below_cents \
            and lock_priceable and _ge(lock_c, cfg.min_lock_profit_cents):
        return lock_action(LifecycleReason.FORCE_LOCK_MODEL_FADED)

    weakened = (cev_c is None) or (cev_c < cfg.ride_min_edge_cents - 1e-9)

    # 6) CONDITIONAL SELL — sellable profit + weakened edge; prefer sell if it beats lock.
    if sell.available and _ge(sell_c, cfg.min_sell_profit_cents) and weakened:
        if _ge(lock_c, cfg.min_lock_profit_cents) and (lock_pp or 0) > (sell.profit_per_contract or 0):
            return lock_action(LifecycleReason.CONDITIONAL_LOCK)
        return sell_action(sell.max_fillable_qty, LifecycleReason.CONDITIONAL_SELL)
    # 7) CONDITIONAL LOCK — the lock module already decided a conditional/hard lock.
    if lock.decision_state in (LOCK_FULL, LOCK_PARTIAL):
        if sell.available and _ge(sell_c, cfg.min_sell_profit_cents) \
                and (sell.profit_per_contract or 0) > (lock_pp or 0):
            return sell_action(sell.max_fillable_qty, LifecycleReason.SELL_BEATS_LOCK)
        return lock_action(LifecycleReason.CONDITIONAL_LOCK)

    # 8) RIDE — model valid and continue EV dominates sell/lock.
    alts = []
    if sell.available and isinstance(sell.profit_per_contract, (int, float)):
        alts.append(sell.profit_per_contract)
    if lock_priceable and isinstance(lock_pp, (int, float)):
        alts.append(lock_pp)
    best_alt = max(alts) if alts else None
    if inp.model_valid and cev is not None and _ge(cev_c, cfg.ride_min_edge_cents) \
            and (best_alt is None or cev >= best_alt - 1e-9):
        return decision(RIDE, side=held, reasons=[LifecycleReason.RIDE_MODEL_EDGE],
                        sell=sell, lock=lock, cev=cev)

    # 9) Otherwise WATCH (or REJECTED if nothing was even evaluable).
    if not sell.available and not lock_priceable:
        return decision(REJECTED, side=held,
                        reasons=(sell.reason_codes or []) + [LifecycleReason.NOTHING_ACTIONABLE],
                        sell=sell, lock=lock, cev=cev)
    reason = LifecycleReason.NO_MODEL_FOR_RIDE if not inp.model_valid else LifecycleReason.RIDE_NO_BETTER_ACTION
    return decision(WATCH, side=held, reasons=[reason], sell=sell, lock=lock, cev=cev)


def _summary(action, side, sell, lock, cev, reasons) -> str:
    bits = [f"{action}"]
    if side:
        bits.append(side)
    if sell and sell.exit_price is not None:
        bits.append(f"sell {format_price_cents(sell.exit_price)} ({format_price_cents(sell.profit_per_contract)})")
    if lock and lock.current_opposite_ask is not None:
        bits.append(f"lock {format_price_cents(lock.lock_value_per_contract)}")
    if isinstance(cev, (int, float)):
        bits.append(f"continue {format_price_cents(cev)}")
    bits.append(",".join(reasons))
    return " | ".join(bits)
