"""Post-decision, latency-safe decision explanations.

Explanations are generated **after** a decision/order-intent exists, from the
already-computed structured reason codes + features — never before, and never on
the hot path. The generator is a deterministic offline template:

    model score -> decide/order  -> store structured reason  -> explain() later

NEVER do: model score -> explain()/LLM -> decide. There is intentionally no
LLM / external-API call here. If one is ever added it MUST be offline, run only
in a background worker, and be disabled by default (see ``EXPLANATION_BACKEND``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Optional

# Only "template" is implemented. An LLM/API backend is deliberately absent; any
# future backend must be background-only and disabled by default.
EXPLANATION_BACKEND = "template"


@dataclass
class DecisionExplanationInput:
    """Structured, post-decision input for an explanation (no look-ahead)."""
    timestamp_ms: int
    series: str
    ticker: Optional[str] = None
    decision_state: Optional[str] = None
    selected_side: Optional[str] = None
    model_probability_yes: Optional[float] = None
    executable_yes_price: Optional[float] = None
    executable_no_price: Optional[float] = None
    raw_edge: Optional[float] = None
    net_edge: Optional[float] = None
    fees: Optional[float] = None
    uncertainty_buffer_cents: Optional[float] = None
    book_age_ms: Optional[float] = None
    underlying_age_ms: Optional[float] = None
    deribit_age_ms: Optional[float] = None
    source_health_flags: dict = field(default_factory=dict)
    reason_codes: list = field(default_factory=list)
    model_version: Optional[str] = None
    calibrator_version: Optional[str] = None
    backtest_version: Optional[str] = None
    min_net_edge_cents: Optional[float] = None
    live_submission_allowed: bool = False
    # Affirms this was produced AFTER the decision; explain() never runs pre-decision.
    generated_after_decision: bool = True


def build_explanation_input(decision: dict, *, series: str,
                            freshness: Optional[dict] = None,
                            versions: Optional[dict] = None,
                            min_net_edge_cents: Optional[float] = None) -> DecisionExplanationInput:
    """Map a decision dict (+ optional freshness/versions) to a structured input.

    Tolerant of missing keys — anything absent stays None. Pure; safe to call
    immediately after a decision when assembling a background notification."""
    fr = freshness or {}
    ver = versions or {}
    return DecisionExplanationInput(
        timestamp_ms=int(decision.get("timestamp_ms") or decision.get("created_at_ms") or 0),
        series=series,
        ticker=decision.get("market_ticker") or decision.get("ticker"),
        decision_state=decision.get("decision_state"),
        selected_side=decision.get("selected_side") or decision.get("side"),
        model_probability_yes=decision.get("model_probability_yes") or decision.get("model_probability"),
        executable_yes_price=decision.get("executable_yes_price"),
        executable_no_price=decision.get("executable_no_price"),
        raw_edge=decision.get("raw_edge"),
        net_edge=decision.get("net_edge"),
        fees=decision.get("fee_estimate"),
        uncertainty_buffer_cents=decision.get("uncertainty_buffer_cents"),
        book_age_ms=decision.get("book_age_ms") or fr.get("book_age_ms"),
        underlying_age_ms=decision.get("underlying_age_ms") or fr.get("underlying_age_ms"),
        deribit_age_ms=decision.get("deribit_age_ms") or fr.get("deribit_age_ms"),
        source_health_flags=fr.get("source_health_flags") or {},
        reason_codes=list(decision.get("reason_codes") or []),
        model_version=ver.get("model_version") or decision.get("model_version"),
        calibrator_version=ver.get("calibrator_version") or decision.get("calibration_status"),
        backtest_version=ver.get("backtest_version"),
        min_net_edge_cents=min_net_edge_cents,
        live_submission_allowed=False,  # always false in this build
    )


def _c(x) -> str:
    return f"{x * 100:+.1f}c" if isinstance(x, (int, float)) else "n/a"


def _ms(x) -> str:
    return f"{x:.0f}ms" if isinstance(x, (int, float)) else "n/a"


def _side_h(side: Optional[str]) -> str:
    return {"BUY_YES": "YES", "BUY_NO": "NO", "YES": "YES", "NO": "NO"}.get(side or "", side or "")


def explain(inp) -> str:
    """Return a one-line plain-English explanation from structured reason codes.

    Deterministic, offline, microsecond-cheap. Accepts a
    :class:`DecisionExplanationInput` or a plain dict. Missing fields degrade to
    'n/a' rather than raising. NO network / LLM call.
    """
    d = asdict(inp) if is_dataclass(inp) else dict(inp or {})
    state = d.get("decision_state")
    rc = [str(r) for r in (d.get("reason_codes") or [])]
    side = _side_h(d.get("selected_side") or d.get("side"))
    net = d.get("net_edge")
    minc = d.get("min_net_edge_cents")
    min_txt = f"{minc:.1f}c" if isinstance(minc, (int, float)) else "the configured minimum"
    live = "" if d.get("live_submission_allowed") else " Live submission disabled."

    def has(prefix: str) -> bool:
        return any(r.startswith(prefix) for r in rc)

    # 1) Timing / status skips (post-close / pre-open / not open).
    if has("MARKET_CLOSED") or has("WINDOW_CLOSED"):
        return "Skipped: market already closed (outside the active 15m window); collection only." + live
    if has("OUTSIDE_DECISION_WINDOW"):
        return "Skipped: market not yet in its active trading window (pre-open); collection only." + live
    if has("MARKET_NOT_OPEN"):
        return "Skipped: market not open / not accepting orders; not a decision target." + live
    if has("WINDOW_CLOSING"):
        return "Skipped: too close to window close to act safely." + live
    # 2) Book / liquidity.
    if has("EMPTY_OR_INCOMPLETE_BOOK") or has("INVALID_OR_INCOMPLETE_BOOK") or has("NO_EXECUTABLE_ASK"):
        return "Rejected: order book empty/incomplete — no executable quote to price an edge." + live
    if has("STALE_BOOK"):
        return f"Rejected: order book stale (age {_ms(d.get('book_age_ms'))}) beyond the freshness limit." + live
    if has("STALE_UNDERLYING"):
        return f"Rejected: underlying feed stale (age {_ms(d.get('underlying_age_ms'))}); refusing to act on stale data." + live
    if has("STALE_QUOTE"):
        return "Held: quote age exceeded the freshness limit; downgraded to watch." + live
    if has("MISSING_START_REFERENCE"):
        return "Rejected: missing window start reference price; cannot compute distance/edge." + live
    if has("INSUFFICIENT_DEPTH") or has("THIN_BOOK"):
        return "Rejected: book too thin (insufficient executable depth) to fill safely." + live
    # 3) Model.
    if has("NO_MODEL_PROB"):
        return "Watch: model returned no probability for this snapshot; nothing to act on." + live
    # 4) Edge below threshold (WATCH / NO_ACTION).
    if has("EDGE_BELOW_MIN") or state in ("WATCH", "NO_ACTION"):
        return (f"No action: net {side} edge {_c(net)} is below the {min_txt} "
                f"threshold after fees and the uncertainty buffer." + live)
    # 5) Uncalibrated cap.
    if has("UNCALIBRATED_MODEL") or state == "MANUAL_REVIEW":
        return (f"Manual review: {side} edge {_c(net)} looks tradable, but the model is "
                f"uncalibrated — capped below PAPER_CANDIDATE." + live)
    # 6) Candidate.
    if state == "PAPER_CANDIDATE" or has("NET_EDGE_OK"):
        return (f"Paper candidate: calibrated {side} probability exceeded the executable ask by "
                f"{_c(net)} after fees and freshness gates." + live)
    return f"Decision {state or 'UNKNOWN'} (reasons: {', '.join(rc) or 'n/a'})." + live
