"""Paper-candidate policy engine (strict, explainable; NEVER trades live).

Sits between a trained/calibrated/backtested model and paper execution. Given a
feature snapshot + calibrated probability + model/calibration/backtest validity +
executable YES/NO ASK prices + fees/depth/spread/staleness + source health + risk
limits, it emits exactly one of WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE
with reason codes and a human summary. PAPER_CANDIDATE requires the policy enabled
AND a trained, calibrated, non-diagnostic, sufficiently-backtested model passing
every executable-EV / freshness / liquidity / time / risk gate. No LIVE_CANDIDATE
exists; ``live_submission_allowed`` is always False; a hard Up/Down class alone can
never produce a trade (decisions use the calibrated probability + executable EV).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .fees import KalshiFeeModel
from .paper import MANUAL_REVIEW, PAPER_CANDIDATE, REJECTED, WATCH


# --------------------------------------------------------------------------- #
# Reason codes
# --------------------------------------------------------------------------- #
class Reason:
    OK = "OK"
    POLICY_DISABLED = "POLICY_DISABLED"
    MODEL_MISSING = "MODEL_MISSING"
    MODEL_UNTRAINED = "MODEL_UNTRAINED"
    MODEL_UNCALIBRATED = "MODEL_UNCALIBRATED"
    MODEL_DIAGNOSTIC_ONLY = "MODEL_DIAGNOSTIC_ONLY"
    CALIBRATOR_MISSING = "CALIBRATOR_MISSING"
    CALIBRATOR_INVALID = "CALIBRATOR_INVALID"
    BACKTEST_MISSING = "BACKTEST_MISSING"
    BACKTEST_INSUFFICIENT = "BACKTEST_INSUFFICIENT"
    FEATURE_SCHEMA_MISMATCH = "FEATURE_SCHEMA_MISMATCH"
    MISSING_FEATURE = "MISSING_FEATURE"
    MISSING_BOOK = "MISSING_BOOK"
    MISSING_UNDERLYING = "MISSING_UNDERLYING"
    MISSING_START_REFERENCE = "MISSING_START_REFERENCE"
    STALE_BOOK = "STALE_BOOK"
    STALE_UNDERLYING = "STALE_UNDERLYING"
    STALE_DERIBIT = "STALE_DERIBIT"
    WIDE_SPREAD = "WIDE_SPREAD"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    EDGE_BELOW_THRESHOLD = "EDGE_BELOW_THRESHOLD"
    PRICE_ABOVE_RESERVATION = "PRICE_ABOVE_RESERVATION"
    PRICE_CAP_EXCEEDED = "PRICE_CAP_EXCEEDED"
    BOTH_SIDES_POSITIVE = "BOTH_SIDES_POSITIVE"
    TOO_CLOSE_TO_CLOSE = "TOO_CLOSE_TO_CLOSE"
    TOO_FAR_FROM_CLOSE = "TOO_FAR_FROM_CLOSE"
    RISK_BLOCKED = "RISK_BLOCKED"
    MAX_TRADES_PER_WINDOW = "MAX_TRADES_PER_WINDOW"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    PAPER_CANDIDATE_OK = "PAPER_CANDIDATE_OK"


# "Not ready yet" infra reasons -> WATCH; explicit disqualifications -> REJECTED.
_WATCH_INFRA = {Reason.MODEL_MISSING, Reason.MODEL_UNTRAINED, Reason.MODEL_UNCALIBRATED,
                Reason.CALIBRATOR_MISSING, Reason.BACKTEST_MISSING}
_REJECT_INFRA = {Reason.MODEL_DIAGNOSTIC_ONLY, Reason.CALIBRATOR_INVALID,
                 Reason.BACKTEST_INSUFFICIENT, Reason.FEATURE_SCHEMA_MISMATCH}


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class ModelValidity:
    exists: bool = False
    trained: bool = False
    diagnostic_only: bool = True
    tradable_stamp: bool = False
    version: Optional[str] = None
    artifact_path: Optional[str] = None
    feature_schema_version: Optional[int] = None


@dataclass
class CalibrationValidity:
    exists: bool = False
    valid: bool = False
    diagnostic_only: bool = True
    version: Optional[str] = None


@dataclass
class BacktestValidity:
    exists: bool = False
    valid: bool = False
    windows: int = 0
    version: Optional[str] = None


@dataclass
class SourceFreshness:
    book_age_ms: Optional[int] = None
    underlying_age_ms: Optional[int] = None
    deribit_age_ms: Optional[int] = None
    coinbase_stale: bool = False
    binance_stale: bool = False


@dataclass
class ExecutablePrices:
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    yes_depth: Optional[float] = None
    no_depth: Optional[float] = None
    yes_spread: Optional[float] = None
    no_spread: Optional[float] = None


@dataclass
class PolicyInput:
    series: str
    ticker: Optional[str]
    as_of_ts_ms: Optional[int]
    market_open_ts_ms: Optional[int]
    market_close_ts_ms: Optional[int]
    seconds_to_close: Optional[float]
    calibrated_probability_yes: Optional[float]
    model_probability_yes: Optional[float] = None
    feature_schema_version: Optional[int] = None
    book_ok: bool = False
    has_underlying: bool = False
    reference_start_price: Optional[float] = None
    prices: ExecutablePrices = field(default_factory=ExecutablePrices)
    freshness: SourceFreshness = field(default_factory=SourceFreshness)
    model_validity: ModelValidity = field(default_factory=ModelValidity)
    calibration_validity: CalibrationValidity = field(default_factory=CalibrationValidity)
    backtest_validity: BacktestValidity = field(default_factory=BacktestValidity)
    feature_snapshot: dict = field(default_factory=dict)
    # risk / exposure context
    current_open_positions: int = 0
    trades_this_window: int = 0
    risk_blocked: bool = False
    daily_loss_limit_hit: bool = False


@dataclass
class CandidateOrderIntent:
    ticker: Optional[str]
    series: str
    side: str                       # "YES" | "NO"
    action: str                     # "buy"
    size: float
    limit_price: Optional[float]
    time_in_force: str
    post_only: bool
    max_acceptable_price: Optional[float]
    opposite_side_ask: Optional[float]   # for the later lock-profit module (Prompt 6)
    expected_fee: Optional[float]
    expected_notional: Optional[float]
    market_close_ts_ms: Optional[int]
    as_of_ts_ms: Optional[int]
    reason_codes: list = field(default_factory=list)
    live_submission_allowed: bool = False


@dataclass
class PolicyDecision:
    decision_state: str
    selected_side: Optional[str]
    reason_codes: list
    human_summary: str
    model_probability_yes: Optional[float]
    calibrated_probability_yes: Optional[float]
    executable_yes_price: Optional[float]
    executable_no_price: Optional[float]
    raw_edge_yes: Optional[float]
    raw_edge_no: Optional[float]
    net_edge_yes: Optional[float]
    net_edge_no: Optional[float]
    selected_raw_edge: Optional[float]
    selected_net_edge: Optional[float]
    expected_fee: Optional[float]
    uncertainty_buffer: float
    max_acceptable_yes_price: Optional[float]
    max_acceptable_no_price: Optional[float]
    order_intent: Optional[CandidateOrderIntent] = None
    is_paper_candidate: bool = False
    live_submission_allowed: bool = False


def _c(x: Optional[float]) -> str:
    return f"{x*100:+.1f}c" if isinstance(x, (int, float)) else "n/a"


def evaluate_policy(pi: PolicyInput, pc, *, fee_model: Optional[KalshiFeeModel] = None) -> PolicyDecision:
    """Pure policy evaluation. ``pc`` is a PaperPolicyConfig. Never trades."""
    fee_model = fee_model or KalshiFeeModel()
    p_yes = pi.calibrated_probability_yes
    p_yes_for_edge = p_yes if p_yes is not None else pi.model_probability_yes
    yes_ask = pi.prices.yes_ask
    no_ask = pi.prices.no_ask
    buffers = (pc.uncertainty_buffer_cents + pc.slippage_buffer_cents) / 100.0
    min_net = pc.min_net_edge_cents / 100.0
    min_raw = pc.min_raw_edge_cents / 100.0

    fee_yes = fee_model.per_contract_fee(yes_ask) if yes_ask is not None else None
    fee_no = fee_model.per_contract_fee(no_ask) if no_ask is not None else None
    raw_yes = (p_yes_for_edge - yes_ask) if (p_yes_for_edge is not None and yes_ask is not None) else None
    raw_no = ((1 - p_yes_for_edge) - no_ask) if (p_yes_for_edge is not None and no_ask is not None) else None
    net_yes = (raw_yes - fee_yes - buffers) if (raw_yes is not None and fee_yes is not None) else None
    net_no = (raw_no - fee_no - buffers) if (raw_no is not None and fee_no is not None) else None
    max_yes = (p_yes_for_edge - fee_yes - buffers - min_net) if (p_yes_for_edge is not None and fee_yes is not None) else None
    max_no = ((1 - p_yes_for_edge) - fee_no - buffers - min_net) if (p_yes_for_edge is not None and fee_no is not None) else None

    def build(state, side, reasons, *, intent=None) -> PolicyDecision:
        sel_raw = raw_yes if side == "YES" else raw_no if side == "NO" else None
        sel_net = net_yes if side == "YES" else net_no if side == "NO" else None
        summ = f"{state}"
        if side:
            summ += f" BUY {side} @ {pi.prices.yes_ask if side=='YES' else pi.prices.no_ask}"
        if p_yes_for_edge is not None:
            summ += f" | model {p_yes_for_edge:.3f}"
        if sel_net is not None:
            summ += f" | net {_c(sel_net)}"
        summ += f" | {','.join(reasons)}"
        return PolicyDecision(
            decision_state=state, selected_side=side, reason_codes=reasons, human_summary=summ,
            model_probability_yes=pi.model_probability_yes, calibrated_probability_yes=p_yes,
            executable_yes_price=yes_ask, executable_no_price=no_ask,
            raw_edge_yes=raw_yes, raw_edge_no=raw_no, net_edge_yes=net_yes, net_edge_no=net_no,
            selected_raw_edge=sel_raw, selected_net_edge=sel_net,
            expected_fee=(fee_yes if side == "YES" else fee_no if side == "NO" else None),
            uncertainty_buffer=pc.uncertainty_buffer_cents / 100.0,
            max_acceptable_yes_price=max_yes, max_acceptable_no_price=max_no,
            order_intent=intent, is_paper_candidate=(state == PAPER_CANDIDATE),
            live_submission_allowed=False)

    # ----- Phase 0: policy enabled -----
    if not pc.enabled:
        return build(WATCH, None, [Reason.POLICY_DISABLED])

    # ----- Phase A: model / calibration / backtest validity -----
    infra: list[str] = []
    mv, cv, bv = pi.model_validity, pi.calibration_validity, pi.backtest_validity
    if not mv.exists:
        infra.append(Reason.MODEL_MISSING)
    elif pc.require_trained_model and not mv.trained:
        infra.append(Reason.MODEL_UNTRAINED)
    if pc.require_non_diagnostic_model and mv.exists and mv.diagnostic_only:
        infra.append(Reason.MODEL_DIAGNOSTIC_ONLY)
    if pc.require_calibrated_model:
        if not cv.exists:
            infra.append(Reason.CALIBRATOR_MISSING)
        elif cv.diagnostic_only or not cv.valid:
            infra.append(Reason.CALIBRATOR_INVALID)
        if p_yes is None:
            infra.append(Reason.MODEL_UNCALIBRATED)
    if pc.require_backtest_evidence:
        if not bv.exists:
            infra.append(Reason.BACKTEST_MISSING)
        elif not bv.valid or bv.windows < pc.min_backtest_windows:
            infra.append(Reason.BACKTEST_INSUFFICIENT)
    if (mv.exists and mv.feature_schema_version is not None
            and pi.feature_schema_version is not None
            and mv.feature_schema_version != pi.feature_schema_version):
        infra.append(Reason.FEATURE_SCHEMA_MISMATCH)

    if any(r in _REJECT_INFRA for r in infra):
        return build(REJECTED, None, [r for r in infra if r in _REJECT_INFRA] or infra)
    if any(r in _WATCH_INFRA for r in infra):
        return build(WATCH, None, infra)

    # ----- Phase B: data presence / freshness / liquidity / time -----
    hard: list[str] = []
    soft: list[str] = []
    if not pi.book_ok or yes_ask is None or no_ask is None:
        hard.append(Reason.MISSING_BOOK)
    if not pi.has_underlying:
        hard.append(Reason.MISSING_UNDERLYING)
    if pi.reference_start_price is None:
        hard.append(Reason.MISSING_START_REFERENCE)
    fr = pi.freshness
    if fr.book_age_ms is not None and fr.book_age_ms > pc.max_book_age_ms:
        hard.append(Reason.STALE_BOOK)
    if (fr.underlying_age_ms is not None and fr.underlying_age_ms > pc.max_underlying_age_ms) \
            or (fr.coinbase_stale and fr.binance_stale):
        hard.append(Reason.STALE_UNDERLYING)
    if fr.deribit_age_ms is not None and fr.deribit_age_ms > pc.max_deribit_age_ms:
        (hard if pc.require_deribit_fresh else soft).append(Reason.STALE_DERIBIT)
    spread_c = max((pi.prices.yes_spread or 0.0), (pi.prices.no_spread or 0.0)) * 100.0
    if spread_c > pc.max_spread_cents:
        hard.append(Reason.WIDE_SPREAD)
    depth = pi.prices.yes_depth if pi.prices.yes_depth is not None else pi.prices.no_depth
    top_depth = (pi.prices.yes_depth or 0.0) + (pi.prices.no_depth or 0.0)
    if top_depth < pc.min_top_depth_contracts:
        hard.append(Reason.INSUFFICIENT_DEPTH)
    if pi.seconds_to_close is not None and pi.seconds_to_close < pc.min_seconds_to_close:
        hard.append(Reason.TOO_CLOSE_TO_CLOSE)
    if pi.seconds_to_close is not None and pi.seconds_to_close > pc.max_seconds_to_close:
        hard.append(Reason.TOO_FAR_FROM_CLOSE)

    # ----- Phase C: risk limits -----
    if pi.current_open_positions >= pc.max_open_positions:
        hard.append(Reason.MAX_OPEN_POSITIONS)
    if pi.trades_this_window >= pc.max_trades_per_window:
        hard.append(Reason.MAX_TRADES_PER_WINDOW)
    if pi.risk_blocked:
        hard.append(Reason.RISK_BLOCKED)
    if pi.daily_loss_limit_hit:
        hard.append(Reason.DAILY_LOSS_LIMIT)

    if hard:
        return build(REJECTED, None, hard)

    # ----- Phase D: executable EV + reservation -----
    def eligible(side, ask, raw, net, maxp, cap_c):
        if ask is None or raw is None or net is None:
            return False, None
        if ask * 100.0 > cap_c:
            return False, Reason.PRICE_CAP_EXCEEDED
        if maxp is not None and ask > maxp + 1e-12:
            return False, Reason.PRICE_ABOVE_RESERVATION
        if net < min_net or raw < min_raw:
            return False, Reason.EDGE_BELOW_THRESHOLD
        return True, None

    ok_yes, why_yes = eligible("YES", yes_ask, raw_yes, net_yes, max_yes, pc.max_yes_price_cents)
    ok_no, why_no = eligible("NO", no_ask, raw_no, net_no, max_no, pc.max_no_price_cents)

    if not ok_yes and not ok_no:
        why = [w for w in (why_yes, why_no) if w] or [Reason.EDGE_BELOW_THRESHOLD]
        return build(WATCH, None, sorted(set(why)))

    if ok_yes and ok_no:
        side = "YES" if (net_yes or 0) >= (net_no or 0) else "NO"
        return build(MANUAL_REVIEW, side, [Reason.BOTH_SIDES_POSITIVE])

    side = "YES" if ok_yes else "NO"
    ask = yes_ask if side == "YES" else no_ask
    maxp = max_yes if side == "YES" else max_no
    fee = fee_yes if side == "YES" else fee_no
    reasons = [Reason.PAPER_CANDIDATE_OK]
    if soft:
        intent = _intent(pi, pc, side, ask, maxp, fee, soft + [Reason.OK])
        return build(MANUAL_REVIEW, side, soft, intent=None)
    intent = _intent(pi, pc, side, ask, maxp, fee, reasons)
    return build(PAPER_CANDIDATE, side, reasons, intent=intent)


def _intent(pi: PolicyInput, pc, side, ask, maxp, fee, reasons) -> CandidateOrderIntent:
    size = pc.paper_default_size
    opp = pi.prices.no_ask if side == "YES" else pi.prices.yes_ask
    return CandidateOrderIntent(
        ticker=pi.ticker, series=pi.series, side=side, action="buy", size=size,
        limit_price=ask, time_in_force="fill_or_kill", post_only=False,
        max_acceptable_price=maxp, opposite_side_ask=opp,
        expected_fee=(fee * size if fee is not None else None),
        expected_notional=(ask * size if ask is not None else None),
        market_close_ts_ms=pi.market_close_ts_ms, as_of_ts_ms=pi.as_of_ts_ms,
        reason_codes=list(reasons), live_submission_allowed=False)
