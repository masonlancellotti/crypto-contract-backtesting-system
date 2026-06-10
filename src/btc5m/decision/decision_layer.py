"""Decision layer — gated trade candidates from a feature row + model prob.

Given a point-in-time feature row and a model P(YES), this computes the
executable expected value after costs (never midpoint), applies data-quality and
safety gates, and emits a Candidate dict in the project's standard schema with
explicit reason codes and a decision state:

    NO_ACTION | WATCH | MANUAL_REVIEW | PAPER_CANDIDATE | LIVE_CANDIDATE

LIVE_CANDIDATE is only ever produced when ``allow_live`` is explicitly set AND
all live preconditions hold; default output never exceeds PAPER_CANDIDATE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..labels.executable_ev import expected_value_after_costs
from ..timeutils import now_ms


class Decision(str, Enum):
    NO_ACTION = "NO_ACTION"
    WATCH = "WATCH"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    LIVE_CANDIDATE = "LIVE_CANDIDATE"


@dataclass
class DecisionConfig:
    min_net_edge: float = 0.03          # required net edge (prob units) to trade
    fee_per_contract: float = 0.0
    cost_buffer: float = 0.02           # slippage/adverse-selection cushion
    max_quote_age_ms: int = 1500
    thin_depth: float = 50.0
    wide_spread: float = 0.03
    min_seconds_to_expiry: float = 20.0  # too close to execute below this
    allow_uncalibrated: bool = False     # uncalibrated model caps at WATCH
    allow_provisional_line_paper: bool = True  # paper may use provisional line
    allow_live: bool = False             # never emit LIVE_CANDIDATE unless True


def _confidence_bucket(net_edge: float) -> str:
    e = abs(net_edge)
    if e >= 0.06:
        return "high"
    if e >= 0.04:
        return "medium_high"
    if e >= 0.02:
        return "medium"
    return "low"


def _regime(row: dict) -> str:
    if row.get("stale_yes_quote") or row.get("missing_yes_book"):
        return "stale"
    if row.get("crossed_yes_book"):
        return "invalid_book"
    if row.get("thin_yes_book"):
        return "thin"
    if row.get("wide_yes_spread"):
        return "wide_spread"
    if row.get("near_expiry_30s"):
        return "near_expiry"
    return "calm_liquid"


def evaluate_candidate(
    row: dict,
    p_yes: float,
    *,
    calibrated: bool,
    line_source_status: str = "UNKNOWN",
    label_source_status: str = "UNKNOWN",
    cfg: Optional[DecisionConfig] = None,
) -> dict:
    """Evaluate one feature row + model probability into a Candidate dict."""
    cfg = cfg or DecisionConfig()
    yes_ask = row.get("yes_ask")
    no_ask = row.get("no_ask")
    secs = row.get("seconds_to_expiry")
    reasons: list[str] = []

    ev = expected_value_after_costs(p_yes, yes_ask, no_ask, fee_per_contract=cfg.fee_per_contract)
    side = ev.best_side
    raw_edge = ev.best_net_edge  # EV at ask before extra cost buffer (already net of ask)
    estimated_costs = cfg.fee_per_contract + cfg.cost_buffer
    net_edge = (raw_edge - cfg.cost_buffer) if raw_edge is not None else None
    market_yes_ask = yes_ask

    # ---- hard, evaluation-blocking conditions -----------------------------
    if side is None or raw_edge is None:
        reasons.append("no_executable_price")
        return _candidate(row, Decision.NO_ACTION, side, p_yes, market_yes_ask, raw_edge,
                          estimated_costs, net_edge, line_source_status, label_source_status,
                          reasons, cfg)
    if row.get("line_source_status", line_source_status) == "UNKNOWN" or not row.get("line_known", True):
        reasons.append("line_unknown")
        return _candidate(row, Decision.MANUAL_REVIEW, side, p_yes, market_yes_ask, raw_edge,
                          estimated_costs, net_edge, line_source_status, label_source_status,
                          reasons, cfg)

    # ---- positive-edge reason codes ---------------------------------------
    if side == "BUY_YES":
        reasons.append("model_prob_above_yes_ask")
    else:
        reasons.append("model_prob_below_implied_for_no")
    if row.get("distance_from_line") is not None:
        reasons.append("distance_vol_time_supports_" + ("yes" if (row["distance_from_line"] or 0) >= 0 else "no"))
    if row.get("spot_cvd_60s") is not None and row["spot_cvd_60s"] != 0:
        reasons.append("cvd_" + ("positive" if row["spot_cvd_60s"] > 0 else "negative"))
    if row.get("spot_microprice_minus_mid") is not None and row["spot_microprice_minus_mid"]:
        reasons.append("spot_microprice_skew")

    # ---- soft gates (downgrade) -------------------------------------------
    liquidity_ok = not (row.get("thin_yes_book") or row.get("wide_yes_spread") or row.get("missing_yes_book"))
    freshness_ok = not row.get("stale_yes_quote") and bool(row.get("feed_health_ok"))

    decision = Decision.PAPER_CANDIDATE
    if net_edge is None or net_edge < cfg.min_net_edge:
        reasons.append("edge_below_threshold")
        decision = Decision.WATCH if (net_edge is not None and net_edge > 0) else Decision.NO_ACTION
    if not freshness_ok:
        reasons.append("stale_quote_or_bad_feed")
        decision = _min_decision(decision, Decision.WATCH)
    if not liquidity_ok:
        reasons.append("thin_or_wide_book")
        decision = _min_decision(decision, Decision.WATCH)
    if secs is not None and secs < cfg.min_seconds_to_expiry:
        reasons.append("too_close_to_expiry")
        decision = _min_decision(decision, Decision.WATCH)
    if not calibrated and not cfg.allow_uncalibrated:
        reasons.append("model_uncalibrated")
        decision = _min_decision(decision, Decision.WATCH)
    if line_source_status == "PROVISIONAL_REFERENCE":
        reasons.append("provisional_line")
        if not cfg.allow_provisional_line_paper:
            decision = _min_decision(decision, Decision.MANUAL_REVIEW)

    # ---- live is never reached by default ---------------------------------
    if decision is Decision.PAPER_CANDIDATE and cfg.allow_live:
        live_ok = (
            calibrated
            and line_source_status == "OFFICIAL"
            and freshness_ok
            and liquidity_ok
            and (secs is None or secs >= cfg.min_seconds_to_expiry)
        )
        if live_ok:
            decision = Decision.LIVE_CANDIDATE
            reasons.append("all_live_preconditions_met")

    return _candidate(row, decision, side, p_yes, market_yes_ask, raw_edge, estimated_costs,
                      net_edge, line_source_status, label_source_status, reasons, cfg,
                      liquidity_ok=liquidity_ok, freshness_ok=freshness_ok)


def _min_decision(current: Decision, cap: Decision) -> Decision:
    order = [Decision.NO_ACTION, Decision.WATCH, Decision.MANUAL_REVIEW,
             Decision.PAPER_CANDIDATE, Decision.LIVE_CANDIDATE]
    # MANUAL_REVIEW is a sink that should not be auto-traded; treat as a cap too.
    if cap is Decision.MANUAL_REVIEW:
        return Decision.MANUAL_REVIEW
    return current if order.index(current) <= order.index(cap) else cap


def _candidate(row, decision, side, p_yes, market_yes_ask, raw_edge, estimated_costs,
               net_edge, line_source_status, label_source_status, reasons, cfg,
               *, liquidity_ok=None, freshness_ok=None) -> dict:
    return {
        "timestamp_ms": row.get("as_of_ms", now_ms()),
        "contract_id": row.get("condition_id"),
        "slug": row.get("slug"),
        "side": side,
        "model_yes_probability": round(p_yes, 6) if p_yes is not None else None,
        "market_yes_ask": market_yes_ask,
        "raw_edge": round(raw_edge, 6) if raw_edge is not None else None,
        "estimated_costs": round(estimated_costs, 6),
        "net_edge": round(net_edge, 6) if net_edge is not None else None,
        "confidence_bucket": _confidence_bucket(net_edge) if net_edge is not None else "low",
        "regime": _regime(row),
        "liquidity_ok": liquidity_ok if liquidity_ok is not None
        else not (row.get("thin_yes_book") or row.get("wide_yes_spread")),
        "quote_freshness_ok": freshness_ok if freshness_ok is not None
        else not row.get("stale_yes_quote"),
        "line_source_status": line_source_status,
        "label_source_status": label_source_status,
        "decision": decision.value,
        "reason_codes": reasons,
    }


def candidate_message(c: dict) -> str:
    """Short notification string for a candidate (matches project examples)."""
    side = c.get("side") or "?"
    net = c.get("net_edge")
    net_c = f"{net*100:+.1f}c" if net is not None else "n/a"
    p = c.get("model_yes_probability")
    ask = c.get("market_yes_ask")
    decision = c.get("decision")
    if decision == Decision.PAPER_CANDIDATE.value:
        return (f"BTC 5m PAPER_CANDIDATE: {side} @ {ask} | model {p} | "
                f"net edge {net_c} | {c.get('slug')}")
    if decision in (Decision.WATCH.value, Decision.NO_ACTION.value):
        why = ", ".join(c.get("reason_codes", [])[-2:]) or "no edge"
        return f"BTC 5m WATCH: edge {net_c} rejected: {why}"
    if decision == Decision.MANUAL_REVIEW.value:
        return f"BTC 5m MANUAL_REVIEW: {c.get('slug')} | {', '.join(c.get('reason_codes', []))}"
    return f"BTC 5m {decision}: {side} {net_c} | {c.get('slug')}"
