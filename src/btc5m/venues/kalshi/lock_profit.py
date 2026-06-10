"""Post-entry lock-profit module (paper-only; never live).

POSITION MANAGEMENT after a paper directional entry — **not** a flat-position arb
scanner. It only evaluates buying the OPPOSITE leg of an EXISTING paper position to
lock guaranteed profit after fees: held YES → monitor NO; held NO → monitor YES.
It never opens directional positions, never scans flat markets, and never submits a
live order. Decisions: NO_POSITION / ALREADY_FULLY_LOCKED / WATCH / RIDE / LOCK_FULL
/ LOCK_PARTIAL / REJECTED. Internal unit is DECIMAL probability/dollars 0.0–1.0
(matching the repo's normalized book); thresholds are configured in cents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .fees import KalshiFeeModel

# Decision states (no LIVE_* state exists).
NO_POSITION = "NO_POSITION"
ALREADY_FULLY_LOCKED = "ALREADY_FULLY_LOCKED"
WATCH = "WATCH"
RIDE = "RIDE"
LOCK_FULL = "LOCK_FULL"
LOCK_PARTIAL = "LOCK_PARTIAL"
REJECTED = "REJECTED"


class LockReason:
    OK = "OK"
    NO_POSITION = "NO_POSITION"
    ALREADY_FULLY_LOCKED = "ALREADY_FULLY_LOCKED"
    MODULE_DISABLED = "MODULE_DISABLED"
    HARD_LOCK = "HARD_LOCK"
    CONDITIONAL_LOCK = "CONDITIONAL_LOCK"
    RIDE_MODEL_EDGE = "RIDE_MODEL_EDGE"
    LOCK_BELOW_MIN = "LOCK_BELOW_MIN"
    PRICE_ABOVE_MAX = "PRICE_ABOVE_MAX"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    PARTIAL_DEPTH = "PARTIAL_DEPTH"
    PARTIAL_NOT_ALLOWED = "PARTIAL_NOT_ALLOWED"
    STALE_BOOK = "STALE_BOOK"
    STALE_UNDERLYING = "STALE_UNDERLYING"
    TOO_CLOSE_TO_CLOSE = "TOO_CLOSE_TO_CLOSE"
    MISSING_BOOK = "MISSING_BOOK"
    NO_MODEL_FOR_SOFT_LOCK = "NO_MODEL_FOR_SOFT_LOCK"


# --------------------------------------------------------------------------- #
# Price units (the repo standardizes on DECIMAL 0.0–1.0; thresholds are cents)
# --------------------------------------------------------------------------- #
def cents_to_decimal(c: float) -> float:
    return c / 100.0


def decimal_to_cents(d: float) -> float:
    return d * 100.0


def normalize_price(p, *, assume: str = "decimal") -> Optional[float]:
    """Coerce a price to decimal 0.0–1.0. ``assume='cents'`` divides by 100."""
    if p is None:
        return None
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if assume == "cents":
        v = v / 100.0
    return v


def validate_binary_price(p) -> bool:
    return isinstance(p, (int, float)) and 0.0 <= float(p) <= 1.0


# --------------------------------------------------------------------------- #
# Position accounting
# --------------------------------------------------------------------------- #
@dataclass
class KalshiPositionLot:
    side: str                 # "YES" | "NO"
    quantity: float
    price: float              # decimal 0..1
    fee_per_contract: float = 0.0


@dataclass
class KalshiPositionState:
    series: str
    ticker: Optional[str]
    market_close_ts_ms: Optional[int] = None
    yes_quantity: float = 0.0
    no_quantity: float = 0.0
    yes_avg_price: float = 0.0
    no_avg_price: float = 0.0
    yes_avg_fee: float = 0.0
    no_avg_fee: float = 0.0
    venue: str = "kalshi"
    paper_only: bool = True

    @classmethod
    def from_lots(cls, lots: list[KalshiPositionLot], *, series: str, ticker: Optional[str],
                  market_close_ts_ms: Optional[int] = None) -> "KalshiPositionState":
        def agg(side):
            ls = [l for l in lots if l.side.upper() == side]
            q = sum(l.quantity for l in ls)
            if q <= 0:
                return 0.0, 0.0, 0.0
            ap = sum(l.price * l.quantity for l in ls) / q
            af = sum(l.fee_per_contract * l.quantity for l in ls) / q
            return q, ap, af
        yq, yap, yaf = agg("YES")
        nq, nap, naf = agg("NO")
        return cls(series=series, ticker=ticker, market_close_ts_ms=market_close_ts_ms,
                   yes_quantity=yq, no_quantity=nq, yes_avg_price=yap, no_avg_price=nap,
                   yes_avg_fee=yaf, no_avg_fee=naf)

    @property
    def yes_total_cost(self) -> float:
        return self.yes_avg_price + self.yes_avg_fee

    @property
    def no_total_cost(self) -> float:
        return self.no_avg_price + self.no_avg_fee

    @property
    def locked_pairs_quantity(self) -> float:
        return min(self.yes_quantity, self.no_quantity)

    @property
    def naked_yes_quantity(self) -> float:
        return max(0.0, self.yes_quantity - self.no_quantity)

    @property
    def naked_no_quantity(self) -> float:
        return max(0.0, self.no_quantity - self.yes_quantity)

    @property
    def has_position(self) -> bool:
        return self.yes_quantity > 0 or self.no_quantity > 0

    @property
    def realized_locked_profit(self) -> float:
        """Guaranteed profit on the locked pairs (1 - yes_total - no_total per pair)."""
        return self.locked_pairs_quantity * (1.0 - self.yes_total_cost - self.no_total_cost)

    @property
    def unrealized_directional_exposure(self) -> float:
        """Cost basis still at directional risk (the naked leg)."""
        if self.naked_yes_quantity > 0:
            return self.naked_yes_quantity * self.yes_total_cost
        if self.naked_no_quantity > 0:
            return self.naked_no_quantity * self.no_total_cost
        return 0.0


# --------------------------------------------------------------------------- #
# Lock config / opportunity / decision / intent
# --------------------------------------------------------------------------- #
@dataclass
class LockConfig:
    """Mirror of config.LockConfig (kept here so the math is testable standalone)."""
    enabled: bool = False
    paper_only: bool = True
    min_profit_cents: float = 2.0
    hard_profit_cents: float = 5.0
    allow_partial: bool = False
    default_mode: str = "fok"
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_depth_contracts: float = 1.0
    min_seconds_to_close: int = 3
    ride_min_edge_cents: float = 3.0
    force_when_model_edge_below_cents: float = 1.0
    slippage_buffer_cents: float = 0.0
    require_underlying_fresh: bool = False
    notify: bool = True

    @classmethod
    def from_app(cls, config) -> "LockConfig":
        c = getattr(config, "lock", None)
        if c is None:
            return cls()
        return cls(**{f: getattr(c, f) for f in cls.__dataclass_fields__ if hasattr(c, f)})


@dataclass
class LockOrderIntent:
    ticker: Optional[str]
    side_to_buy: str
    quantity: float
    limit_price: float
    time_in_force: str
    max_acceptable_price: float
    expected_fee: float
    expected_locked_profit: float
    reason_codes: list = field(default_factory=list)
    paper_only: bool = True
    live_submission_allowed: bool = False


@dataclass
class LockedPair:
    ticker: Optional[str]
    quantity: float
    yes_total_cost: float
    no_total_cost: float
    locked_profit_per_pair: float


@dataclass
class LockDecision:
    decision_state: str
    ticker: Optional[str]
    side_to_buy: Optional[str]
    lock_quantity: float
    current_opposite_ask: Optional[float]
    max_acceptable_opposite_price: Optional[float]
    expected_lock_fee: Optional[float]
    expected_locked_profit_per_pair: Optional[float]
    expected_total_locked_profit: Optional[float]
    existing_position_side: Optional[str]
    naked_quantity_before: float
    naked_quantity_after: float
    locked_quantity_after: float
    continue_ev_per_contract: Optional[float]
    lock_value_per_contract: Optional[float]
    ride_vs_lock_reason: str
    reason_codes: list
    human_summary: str
    order_intent: Optional[LockOrderIntent] = None
    live_submission_allowed: bool = False


def _c(x: Optional[float]) -> str:
    return f"{x*100:+.1f}c" if isinstance(x, (int, float)) else "n/a"


def evaluate_lock(
    position: KalshiPositionState,
    *,
    opposite_ask: Optional[float],
    opposite_depth: Optional[float],
    book_ok: bool,
    seconds_to_close: Optional[float],
    book_age_ms: Optional[int] = None,
    underlying_age_ms: Optional[int] = None,
    underlying_stale: bool = False,
    calibrated_p_yes: Optional[float] = None,
    config: LockConfig = None,
    fee_model: Optional[KalshiFeeModel] = None,
    mode: Optional[str] = None,
    allow_partial: Optional[bool] = None,
) -> LockDecision:
    """Decide whether to lock the opposite leg of an EXISTING paper position."""
    cfg = config or LockConfig()
    fee_model = fee_model or KalshiFeeModel()
    mode = (mode or cfg.default_mode or "fok").lower()
    allow_partial = cfg.allow_partial if allow_partial is None else allow_partial
    buffers = cfg.slippage_buffer_cents / 100.0
    min_lock = cfg.min_profit_cents / 100.0
    hard_lock = cfg.hard_profit_cents / 100.0

    def base(state, *, side=None, qty=0.0, reasons=None, ride_reason="", intent=None,
             max_opp=None, locked_pp=None, cont_ev=None, naked_after=None, locked_after=None):
        naked_before = position.naked_yes_quantity + position.naked_no_quantity
        reasons = reasons or [state]
        summ = f"{state}"
        if side:
            summ += f" buy {side} @ {opposite_ask}"
        if locked_pp is not None:
            summ += f" | locks {_c(locked_pp)}"
        if qty:
            summ += f" | qty {qty}"
        summ += f" | {','.join(reasons)}"
        return LockDecision(
            decision_state=state, ticker=position.ticker, side_to_buy=side, lock_quantity=qty,
            current_opposite_ask=opposite_ask, max_acceptable_opposite_price=max_opp,
            expected_lock_fee=(fee_model.per_contract_fee(opposite_ask) if opposite_ask is not None else None),
            expected_locked_profit_per_pair=locked_pp,
            expected_total_locked_profit=(locked_pp * qty if (locked_pp is not None and qty) else None),
            existing_position_side=held, naked_quantity_before=naked_before,
            naked_quantity_after=(naked_before - qty if naked_after is None else naked_after),
            locked_quantity_after=(position.locked_pairs_quantity + qty if locked_after is None else locked_after),
            continue_ev_per_contract=cont_ev, lock_value_per_contract=locked_pp,
            ride_vs_lock_reason=ride_reason, reason_codes=reasons, human_summary=summ,
            order_intent=intent, live_submission_allowed=False)

    # ----- position presence -----
    if not position.has_position:
        held = None
        return base(NO_POSITION, reasons=[LockReason.NO_POSITION])
    if position.naked_yes_quantity == 0 and position.naked_no_quantity == 0:
        held = None
        return base(ALREADY_FULLY_LOCKED, reasons=[LockReason.ALREADY_FULLY_LOCKED])

    held = "YES" if position.naked_yes_quantity > 0 else "NO"
    lock_leg = "NO" if held == "YES" else "YES"
    naked = position.naked_yes_quantity if held == "YES" else position.naked_no_quantity
    existing_cost = position.yes_total_cost if held == "YES" else position.no_total_cost

    # continue EV for the naked leg (probabilistic; can lose the whole naked cost)
    cont_ev = None
    if calibrated_p_yes is not None:
        cont_ev = ((calibrated_p_yes - existing_cost) if held == "YES"
                   else ((1.0 - calibrated_p_yes) - existing_cost))

    # ----- hard gates -----
    if not book_ok or opposite_ask is None:
        return base(REJECTED, reasons=[LockReason.MISSING_BOOK], cont_ev=cont_ev)
    opp_fee = fee_model.per_contract_fee(opposite_ask)
    max_opp = 1.0 - existing_cost - opp_fee - buffers - min_lock
    locked_pp = 1.0 - existing_cost - (opposite_ask + opp_fee + buffers)

    if book_age_ms is not None and book_age_ms > cfg.max_book_age_ms:
        return base(REJECTED, reasons=[LockReason.STALE_BOOK], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
    if cfg.require_underlying_fresh and (underlying_stale or
            (underlying_age_ms is not None and underlying_age_ms > cfg.max_underlying_age_ms)):
        return base(REJECTED, reasons=[LockReason.STALE_UNDERLYING], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
    if seconds_to_close is not None and seconds_to_close < cfg.min_seconds_to_close:
        return base(REJECTED, reasons=[LockReason.TOO_CLOSE_TO_CLOSE], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
    avail = opposite_depth or 0.0
    if avail < cfg.min_depth_contracts:
        return base(REJECTED, reasons=[LockReason.INSUFFICIENT_DEPTH], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)

    lock_qty = min(naked, avail)

    # ----- is the lock priced acceptably? -----
    lockable = (locked_pp >= min_lock) and (opposite_ask <= max_opp + 1e-12)
    if not lockable:
        reason = LockReason.PRICE_ABOVE_MAX if opposite_ask > max_opp else LockReason.LOCK_BELOW_MIN
        if cont_ev is not None and decimal_to_cents(cont_ev) >= cfg.ride_min_edge_cents:
            return base(RIDE, reasons=[reason, LockReason.RIDE_MODEL_EDGE],
                        ride_reason=f"continue_ev {_c(cont_ev)} >= ride_min {cfg.ride_min_edge_cents}c; lock {_c(locked_pp)} < min",
                        max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
        return base(WATCH, reasons=[reason], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)

    # ----- lock vs ride decision -----
    hard = locked_pp >= hard_lock
    decide_lock = False
    ride_reason = ""
    reason = LockReason.OK
    if hard:
        decide_lock = True
        reason = LockReason.HARD_LOCK
        ride_reason = f"hard lock: locked {_c(locked_pp)} >= hard {cfg.hard_profit_cents}c (guaranteed)"
    elif cont_ev is None:
        # soft/conditional lock needs a model; without one only hard lock is allowed.
        return base(WATCH, reasons=[LockReason.NO_MODEL_FOR_SOFT_LOCK], max_opp=max_opp,
                    locked_pp=locked_pp, cont_ev=cont_ev)
    else:
        cont_c = decimal_to_cents(cont_ev)
        if cont_ev > locked_pp and cont_c >= cfg.ride_min_edge_cents:
            return base(RIDE, reasons=[LockReason.RIDE_MODEL_EDGE],
                        ride_reason=f"continue_ev {_c(cont_ev)} > lock {_c(locked_pp)} and >= ride_min {cfg.ride_min_edge_cents}c",
                        max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
        decide_lock = True
        reason = LockReason.CONDITIONAL_LOCK
        ride_reason = (f"conditional lock: model edge {_c(cont_ev)} weak "
                       f"(< ride_min {cfg.ride_min_edge_cents}c or <= lock {_c(locked_pp)})")

    if not decide_lock:
        return base(WATCH, reasons=[LockReason.LOCK_BELOW_MIN], max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)

    # ----- depth-aware fill mode -----
    need_partial = lock_qty < naked
    if need_partial:
        if allow_partial and mode == "ioc":
            state, qty, rs = LOCK_PARTIAL, lock_qty, [reason, LockReason.PARTIAL_DEPTH]
        else:
            return base(REJECTED, reasons=[LockReason.INSUFFICIENT_DEPTH, LockReason.PARTIAL_NOT_ALLOWED],
                        max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev)
    else:
        state, qty, rs = LOCK_FULL, naked, [reason]

    tif = "immediate_or_cancel" if mode == "ioc" else "fill_or_kill"
    intent = LockOrderIntent(
        ticker=position.ticker, side_to_buy=lock_leg, quantity=qty, limit_price=opposite_ask,
        time_in_force=tif, max_acceptable_price=max_opp, expected_fee=opp_fee * qty,
        expected_locked_profit=locked_pp * qty, reason_codes=list(rs),
        paper_only=True, live_submission_allowed=False)
    return base(state, side=lock_leg, qty=qty, reasons=rs, ride_reason=ride_reason, intent=intent,
                max_opp=max_opp, locked_pp=locked_pp, cont_ev=cont_ev,
                naked_after=naked - qty, locked_after=position.locked_pairs_quantity + qty)
