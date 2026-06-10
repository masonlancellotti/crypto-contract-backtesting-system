"""Confidence-aware edge threshold / reservation-price policy (paper-only; never live).

Core principle: do NOT trade merely because ``model_probability > market_price``.
Trade only when, after subtracting fees, depth/slippage, staleness, model +
calibration uncertainty, regime and overtrading buffers, and a minimum profit
buffer, the CONSERVATIVE edge still clears a configured floor.

Conservative probability bounds (Part B):
  conservative P(YES) = p_yes_lower
  conservative P(NO)  = 1 - p_yes_upper      (NOT 1 - p_yes_lower)

Edge chain (decimal; reported in cents):
  raw_edge              = p_hat_side - executable_ask              (point; for reference)
  conservative_raw_edge = conservative_p_side - executable_ask
  cost_adjusted         = conservative_raw_edge - fee - slippage
  uncertainty_adjusted  = cost_adjusted - calib - stale - source - regime - overtrading
  final_policy_edge     = uncertainty_adjusted - minimum_profit
  reservation:  max_acceptable_price = executable_ask + final_policy_edge
  trade only if final_policy_edge >= 0 AND raw>=min_raw AND final>=min_final AND ask<=reservation.

Executable asks for new buys (never midpoint). Uncalibrated / diagnostic models and
missing confidence bounds are rejected (or use a fixed buffer if configured). No
order is ever submitted; this module never promotes a policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .fees import KalshiFeeModel
from .uncertainty import calibration_uncertainty, ensemble_disagreement

# Reason codes (Part F)
EDGE_OK = "EDGE_OK"
EDGE_BELOW_MIN = "EDGE_BELOW_MIN"
RAW_EDGE_BELOW_MIN = "RAW_EDGE_BELOW_MIN"
COST_ADJUSTED_EDGE_BELOW_MIN = "COST_ADJUSTED_EDGE_BELOW_MIN"
UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN = "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN"
PRICE_ABOVE_RESERVATION = "PRICE_ABOVE_RESERVATION"
MODEL_UNCERTAINTY_TOO_HIGH = "MODEL_UNCERTAINTY_TOO_HIGH"
CALIBRATION_BUCKET_TOO_SMALL = "CALIBRATION_BUCKET_TOO_SMALL"
CALIBRATION_BUCKET_TOO_WEAK = "CALIBRATION_BUCKET_TOO_WEAK"
CALIBRATION_INTERVAL_TOO_WIDE = "CALIBRATION_INTERVAL_TOO_WIDE"
MODEL_DISAGREEMENT_TOO_HIGH = "MODEL_DISAGREEMENT_TOO_HIGH"
STALE_QUOTE_BUFFER_APPLIED = "STALE_QUOTE_BUFFER_APPLIED"
SOURCE_HEALTH_BUFFER_APPLIED = "SOURCE_HEALTH_BUFFER_APPLIED"
REGIME_BUFFER_APPLIED = "REGIME_BUFFER_APPLIED"
OVERTRADING_BUFFER_APPLIED = "OVERTRADING_BUFFER_APPLIED"
LOW_SAMPLE_REJECTED = "LOW_SAMPLE_REJECTED"
UNCERTAINTY_METHOD_UNAVAILABLE = "UNCERTAINTY_METHOD_UNAVAILABLE"
DIAGNOSTIC_MODEL_REJECTED = "DIAGNOSTIC_MODEL_REJECTED"
UNCALIBRATED_MODEL_REJECTED = "UNCALIBRATED_MODEL_REJECTED"
BACKTEST_EVIDENCE_MISSING = "BACKTEST_EVIDENCE_MISSING"
EDGE_POLICY_DISABLED = "EDGE_POLICY_DISABLED"
NO_EXECUTABLE_ASK = "NO_EXECUTABLE_ASK"
INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"


@dataclass
class EdgePolicyConfig:
    enabled: bool = True
    require_confidence_bounds: bool = True
    min_raw_edge_cents: float = 5.0
    min_final_edge_cents: float = 2.0
    base_min_profit_cents: float = 2.0
    fixed_uncertainty_buffer_cents: float = 3.0
    min_calibration_bucket_n: int = 30
    confidence_level: float = 0.80
    max_prob_interval_width_cents: float = 12.0
    use_calibration_buckets: bool = True
    use_window_bootstrap: bool = False
    bootstrap_samples: int = 500
    use_ensemble_disagreement: bool = True
    max_model_disagreement_cents: float = 10.0
    stale_quote_buffer_cents: float = 1.0
    source_stale_buffer_cents: float = 2.0
    high_vol_regime_buffer_cents: float = 2.0
    thin_book_buffer_cents: float = 2.0
    overtrading_buffer_cents: float = 1.0
    min_book_depth: float = 1.0
    max_spread_cents: float = 10.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    report_breakdown: bool = True

    @classmethod
    def from_app(cls, config) -> "EdgePolicyConfig":
        c = getattr(config, "edge_policy", None)
        if c is None:
            return cls()
        return cls(**{f: getattr(c, f) for f in cls.__dataclass_fields__ if hasattr(c, f)})


@dataclass
class EdgeInputs:
    p_yes_hat: Optional[float] = None
    p_yes_lower: Optional[float] = None
    p_yes_upper: Optional[float] = None
    yes_ask: Optional[float] = None
    no_ask: Optional[float] = None
    yes_ask_size: Optional[float] = None
    no_ask_size: Optional[float] = None
    seconds_to_close: Optional[float] = None
    spread_cents: Optional[float] = None
    book_age_ms: Optional[float] = None
    underlying_age_ms: Optional[float] = None
    coinbase_stale: bool = False
    binance_stale: bool = False
    deribit_regime: Optional[str] = None
    sigma_per_sqrt_s: Optional[float] = None
    overtrading: bool = False
    calibration_buckets: list = field(default_factory=list)
    ensemble_probs: dict = field(default_factory=dict)
    model_calibrated: bool = False
    model_tradable: bool = False
    backtest_valid: bool = True


@dataclass
class EdgeDecision:
    state: str                                  # EDGE_OK | EDGE_BELOW_MIN | REJECTED | DISABLED
    side: Optional[str]
    executable_price: Optional[float]
    p_yes_hat: Optional[float]
    p_yes_lower: Optional[float]
    p_yes_upper: Optional[float]
    p_no_hat: Optional[float]
    p_no_lower: Optional[float]
    p_no_upper: Optional[float]
    conservative_p: Optional[float]
    raw_edge_cents: Optional[float]
    conservative_raw_edge_cents: Optional[float]
    cost_adjusted_edge_cents: Optional[float]
    uncertainty_adjusted_edge_cents: Optional[float]
    final_policy_edge_cents: Optional[float]
    required_edge_cents: Optional[float]
    max_acceptable_price: Optional[float]
    margin_to_reservation: Optional[float]
    fee_cents: Optional[float]
    slippage_buffer_cents: float
    model_uncertainty_buffer_cents: float
    calibration_uncertainty_buffer_cents: float
    stale_quote_buffer_cents: float
    source_health_buffer_cents: float
    regime_buffer_cents: float
    overtrading_buffer_cents: float
    minimum_profit_buffer_cents: float
    edge_policy_method: str
    confidence_interval_low: Optional[float]
    confidence_interval_high: Optional[float]
    uncertainty_width: Optional[float]
    sample_count_used: Optional[int]
    probability_interval_method: Optional[str]
    reason_codes: list
    human_summary: str
    paper_only: bool = True
    live_submission_allowed: bool = False


def _c(x: Optional[float]) -> Optional[float]:
    return (x * 100.0) if isinstance(x, (int, float)) else None


def _side_breakdown(side: str, inp: EdgeInputs, cfg: EdgePolicyConfig, fee_model: KalshiFeeModel) -> dict:
    """Compute the full edge breakdown + reason codes for one side."""
    reasons: list[str] = []
    ask = inp.yes_ask if side == "YES" else inp.no_ask
    size_avail = inp.yes_ask_size if side == "YES" else inp.no_ask_size
    p_hat = inp.p_yes_hat if side == "YES" else ((1.0 - inp.p_yes_hat) if inp.p_yes_hat is not None else None)
    if ask is None or p_hat is None:
        return {"tradeable": False, "side": side, "reasons": [NO_EXECUTABLE_ASK], "final": None}

    # --- conservative probability bound + model-uncertainty buffer ---
    method = "fixed_buffer"
    have_bound = False
    if side == "YES":
        bound = inp.p_yes_lower
    else:
        bound = (1.0 - inp.p_yes_upper) if inp.p_yes_upper is not None else None
    if bound is not None:
        conservative_p = max(0.0, min(1.0, bound))
        have_bound = True
        method = "model_interval"
    else:
        conservative_p = None

    # ensemble disagreement (also a model-uncertainty source / hard reject)
    ens = ensemble_disagreement(inp.ensemble_probs) if cfg.use_ensemble_disagreement else None
    if ens and ens.available and _c(ens.dispersion) > cfg.max_model_disagreement_cents:
        reasons.append(MODEL_DISAGREEMENT_TOO_HIGH)
    if conservative_p is None and ens and ens.available:
        conservative_p = max(0.0, p_hat - ens.dispersion)
        have_bound = True
        method = "ensemble_disagreement"

    # calibration-bucket uncertainty
    calib_buf = 0.0
    calib = None
    if cfg.use_calibration_buckets and inp.calibration_buckets:
        calib = calibration_uncertainty(
            inp.p_yes_hat if inp.p_yes_hat is not None else p_hat, side, inp.calibration_buckets,
            min_bucket_n=cfg.min_calibration_bucket_n,
            max_width=cfg.max_prob_interval_width_cents / 100.0, confidence=cfg.confidence_level)
        if calib.available:
            calib_buf = calib.buffer
            if not have_bound:
                method = "calibration_bucket"
                have_bound = True
        else:
            reasons.append(calib.reason or LOW_SAMPLE_REJECTED)

    # fixed-buffer fallback when no statistical bound is available
    if conservative_p is None:
        if cfg.require_confidence_bounds and not (calib and calib.available):
            reasons.append(UNCERTAINTY_METHOD_UNAVAILABLE)
            conservative_p = max(0.0, p_hat - cfg.fixed_uncertainty_buffer_cents / 100.0)
            method = "unavailable"
        else:
            conservative_p = max(0.0, p_hat - cfg.fixed_uncertainty_buffer_cents / 100.0)
            method = "fixed_buffer"
    model_unc_buffer = max(0.0, p_hat - conservative_p)

    # regime / staleness / overtrading buffers
    regime_buf = 0.0
    high_vol = (inp.deribit_regime == "high") or (inp.sigma_per_sqrt_s is not None and inp.sigma_per_sqrt_s > 1.5e-4)
    thin = size_avail is not None and size_avail < cfg.min_book_depth
    if high_vol:
        regime_buf += cfg.high_vol_regime_buffer_cents / 100.0
    if thin:
        regime_buf += cfg.thin_book_buffer_cents / 100.0
    if regime_buf > 0:
        reasons.append(REGIME_BUFFER_APPLIED)
    stale_buf = 0.0
    if inp.book_age_ms is not None and inp.book_age_ms > 0.5 * cfg.max_book_age_ms:
        stale_buf = cfg.stale_quote_buffer_cents / 100.0
        reasons.append(STALE_QUOTE_BUFFER_APPLIED)
    source_buf = 0.0
    if inp.coinbase_stale or inp.binance_stale:
        source_buf = cfg.source_stale_buffer_cents / 100.0
        reasons.append(SOURCE_HEALTH_BUFFER_APPLIED)
    over_buf = 0.0
    if inp.overtrading:
        over_buf = cfg.overtrading_buffer_cents / 100.0
        reasons.append(OVERTRADING_BUFFER_APPLIED)

    fee = fee_model.per_contract_fee(ask)
    slippage = 0.0  # depth handled via thin-book regime buffer + hard depth gate
    min_profit = cfg.base_min_profit_cents / 100.0

    raw_edge = p_hat - ask
    cons_raw = conservative_p - ask
    cost_adj = cons_raw - fee - slippage
    unc_adj = cost_adj - calib_buf - stale_buf - source_buf - regime_buf - over_buf
    final = unc_adj - min_profit
    max_acceptable = ask + final           # reservation price
    required = fee + slippage + model_unc_buffer + calib_buf + stale_buf + source_buf + regime_buf + over_buf + min_profit

    # hard depth gate
    if size_avail is not None and size_avail < cfg.min_book_depth:
        reasons.append(INSUFFICIENT_DEPTH)

    # staged reason codes (first failing stage)
    hard_reject = any(r in reasons for r in (
        MODEL_DISAGREEMENT_TOO_HIGH, INSUFFICIENT_DEPTH, UNCERTAINTY_METHOD_UNAVAILABLE,
        CALIBRATION_BUCKET_TOO_SMALL, CALIBRATION_INTERVAL_TOO_WIDE, "CALIBRATION_BUCKET_MISSING"))
    if _c(raw_edge) < cfg.min_raw_edge_cents - 1e-9:
        reasons.append(RAW_EDGE_BELOW_MIN)
    if cost_adj < -1e-9:
        reasons.append(COST_ADJUSTED_EDGE_BELOW_MIN)
    if unc_adj < -1e-9:
        reasons.append(UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN)
    if ask > max_acceptable + 1e-9:
        reasons.append(PRICE_ABOVE_RESERVATION)
    if _c(final) < cfg.min_final_edge_cents - 1e-9:
        reasons.append(EDGE_BELOW_MIN)

    tradeable = (not hard_reject and _c(raw_edge) >= cfg.min_raw_edge_cents - 1e-9
                 and final >= -1e-9 and _c(final) >= cfg.min_final_edge_cents - 1e-9
                 and ask <= max_acceptable + 1e-9)
    if tradeable:
        reasons = [EDGE_OK] + [r for r in reasons if r.endswith("_APPLIED")]
    ci_low = calib.interval_low if (calib and calib.available) else (inp.p_yes_lower if side == "YES" else None)
    ci_high = calib.interval_high if (calib and calib.available) else (inp.p_yes_upper if side == "YES" else None)
    return {
        "tradeable": tradeable, "side": side, "ask": ask, "conservative_p": conservative_p,
        "p_hat": p_hat, "raw_edge": raw_edge, "cons_raw": cons_raw, "cost_adj": cost_adj,
        "unc_adj": unc_adj, "final": final, "required": required, "max_acceptable": max_acceptable,
        "fee": fee, "slippage": slippage, "model_unc": model_unc_buffer, "calib": calib_buf,
        "stale": stale_buf, "source": source_buf, "regime": regime_buf, "over": over_buf,
        "min_profit": min_profit, "method": method, "ci_low": ci_low, "ci_high": ci_high,
        "uncertainty_width": ((ci_high - ci_low) if (ci_low is not None and ci_high is not None) else None),
        "sample_n": (calib.bucket_n if calib else None),
        "reasons": reasons,
    }


def evaluate_edge(inp: EdgeInputs, cfg: EdgePolicyConfig = None,
                  fee_model: Optional[KalshiFeeModel] = None) -> EdgeDecision:
    """Return the conservative edge decision (best of YES/NO). Never submits orders."""
    cfg = cfg or EdgePolicyConfig()
    fee_model = fee_model or KalshiFeeModel()
    p_yes = inp.p_yes_hat

    def mk(state, b, reasons, summary):
        side = b["side"] if b else None
        return EdgeDecision(
            state=state, side=side, executable_price=(b["ask"] if b else None),
            p_yes_hat=p_yes, p_yes_lower=inp.p_yes_lower, p_yes_upper=inp.p_yes_upper,
            p_no_hat=((1 - p_yes) if p_yes is not None else None),
            p_no_lower=((1 - inp.p_yes_upper) if inp.p_yes_upper is not None else None),
            p_no_upper=((1 - inp.p_yes_lower) if inp.p_yes_lower is not None else None),
            conservative_p=(b["conservative_p"] if b else None),
            raw_edge_cents=_c(b["raw_edge"]) if b else None,
            conservative_raw_edge_cents=_c(b["cons_raw"]) if b else None,
            cost_adjusted_edge_cents=_c(b["cost_adj"]) if b else None,
            uncertainty_adjusted_edge_cents=_c(b["unc_adj"]) if b else None,
            final_policy_edge_cents=_c(b["final"]) if b else None,
            required_edge_cents=_c(b["required"]) if b else None,
            max_acceptable_price=(b["max_acceptable"] if b else None),
            margin_to_reservation=((b["max_acceptable"] - b["ask"]) if b else None),
            fee_cents=_c(b["fee"]) if b else None,
            slippage_buffer_cents=_c(b["slippage"]) if b else 0.0,
            model_uncertainty_buffer_cents=_c(b["model_unc"]) if b else 0.0,
            calibration_uncertainty_buffer_cents=_c(b["calib"]) if b else 0.0,
            stale_quote_buffer_cents=_c(b["stale"]) if b else 0.0,
            source_health_buffer_cents=_c(b["source"]) if b else 0.0,
            regime_buffer_cents=_c(b["regime"]) if b else 0.0,
            overtrading_buffer_cents=_c(b["over"]) if b else 0.0,
            minimum_profit_buffer_cents=_c(b["min_profit"]) if b else cfg.base_min_profit_cents,
            edge_policy_method=(b["method"] if b else "n/a"),
            confidence_interval_low=(b["ci_low"] if b else None),
            confidence_interval_high=(b["ci_high"] if b else None),
            uncertainty_width=(b["uncertainty_width"] if b else None),
            sample_count_used=(b["sample_n"] if b else None),
            probability_interval_method=(b["method"] if b else None),
            reason_codes=reasons, human_summary=summary, paper_only=True, live_submission_allowed=False)

    if not cfg.enabled:
        return mk("DISABLED", None, [EDGE_POLICY_DISABLED], "edge policy disabled")
    if p_yes is None:
        return mk("REJECTED", None, ["NO_MODEL_PROB"], "no model probability")

    # Model-validity gate: conservative by default — no candidate unless tradable.
    validity_reasons = []
    if not inp.model_calibrated:
        validity_reasons.append(UNCALIBRATED_MODEL_REJECTED)
    if inp.model_calibrated and not inp.model_tradable:
        validity_reasons.append(DIAGNOSTIC_MODEL_REJECTED)
    if not inp.backtest_valid:
        validity_reasons.append(BACKTEST_EVIDENCE_MISSING)

    yes_b = _side_breakdown("YES", inp, cfg, fee_model)
    no_b = _side_breakdown("NO", inp, cfg, fee_model)
    cands = [b for b in (yes_b, no_b) if b.get("final") is not None]
    best = max(cands, key=lambda b: b["final"]) if cands else None

    if validity_reasons:
        # report the best breakdown but REJECT (no PAPER_CANDIDATE possible).
        return mk("REJECTED", best, validity_reasons + (best["reasons"] if best else []),
                  f"REJECTED: {','.join(validity_reasons)} (edge breakdown reported; no candidate)")
    if best is None:
        return mk("REJECTED", None, [NO_EXECUTABLE_ASK], "no executable side")
    state = EDGE_OK if best["tradeable"] else ("REJECTED" if any(
        r in best["reasons"] for r in (PRICE_ABOVE_RESERVATION, INSUFFICIENT_DEPTH,
                                        MODEL_DISAGREEMENT_TOO_HIGH)) else EDGE_BELOW_MIN)
    summary = (f"{state} {best['side']} @ {best['ask']} | final {_c(best['final']):.1f}c "
               f"(raw {_c(best['raw_edge']):.1f}c, req {_c(best['required']):.1f}c) | "
               f"max_acc {best['max_acceptable']:.3f} | {','.join(best['reasons'])}")
    return mk(state, best, best["reasons"], summary)


def conservative_continue_ev(*, held_side: str, p_yes_lower: Optional[float],
                             p_yes_upper: Optional[float], total_cost: float) -> Optional[float]:
    """Conservative continue/ride EV for a naked position (Part K).

    Uses the CONSERVATIVE probability bound so we never justify holding with an
    overconfident point estimate: YES -> p_yes_lower; NO -> (1 - p_yes_upper).
    Returns None when the needed bound is missing (caller should not ride)."""
    if held_side == "YES":
        return None if p_yes_lower is None else (p_yes_lower - total_cost)
    if held_side == "NO":
        return None if p_yes_upper is None else ((1.0 - p_yes_upper) - total_cost)
    return None
