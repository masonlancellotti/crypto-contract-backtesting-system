"""Order-planning scaffold — produces PLANNED (never submitted) Kalshi orders.

This generates structured order intents for paper simulation / future live wiring.
Every planned order has ``live_submission_allowed=False``; the live adapter still
refuses real submission. No network, no orders. This prompt only simulates.

No-chase rule: ``max_acceptable_price`` is pinned to the executable ask at plan
time, so a fill is only acceptable at or below the price we already saw — we never
chase a moving book.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Planning modes (all paper/simulated or a dry-run live OBJECT — never a live order).
PLAN_MODES = ("paper_limit", "paper_fok_sim", "paper_ioc_sim", "dry_run_live_object")

_MODE_TIF = {
    "paper_limit": "fill_or_kill",
    "paper_fok_sim": "fill_or_kill",
    "paper_ioc_sim": "immediate_or_cancel",
    "dry_run_live_object": "fill_or_kill",
}


@dataclass
class PlannedOrder:
    ticker: Optional[str]
    series_ticker: Optional[str]
    side: Optional[str]            # "YES" | "NO"
    action: str                   # "buy"
    size: float
    limit_price: Optional[float]
    time_in_force: str
    post_only: bool
    max_acceptable_price: Optional[float]
    no_chase: bool
    quote_age_ms: Optional[float]
    expected_fee: Optional[float]
    expected_notional: Optional[float]
    mode: str
    reason_codes: list = field(default_factory=list)
    live_submission_allowed: bool = False   # ALWAYS False in this build


def plan_order(
    *,
    decision: dict,
    row: dict,
    fee_model: Any,
    config: Any,
    mode: str = "paper_limit",
    size: Optional[float] = None,
    post_only: bool = False,
) -> Optional[PlannedOrder]:
    """Build a PlannedOrder from a decision + feature row, or None if not actionable.

    Only constructs an intent when a side + executable price exist; it does not
    require (and cannot reach) live submission. Honors the configured allowed
    time-in-force list and the no-chase rule.
    """
    if mode not in PLAN_MODES:
        raise ValueError(f"mode must be one of {PLAN_MODES}, got {mode!r}")
    side = decision.get("side")
    exec_price = decision.get("executable_price")
    if not side or exec_price is None:
        return None

    side_yn = "YES" if "YES" in str(side).upper() else "NO"
    tif = _MODE_TIF[mode]
    allowed = tuple(getattr(getattr(config, "low_latency", None), "allowed_time_in_force",
                            ("fill_or_kill", "immediate_or_cancel")))
    reasons = list(decision.get("reason_codes", []))
    if tif not in allowed:
        reasons.append(f"TIF_NOT_ALLOWED({tif})")
        tif = allowed[0] if allowed else tif

    sz = float(size) if size is not None else float(decision.get("order_size") or 1.0)
    fee = None
    try:
        fee = fee_model.per_contract_fee(exec_price, sz) if hasattr(fee_model, "per_contract_fee") else None
    except Exception:  # noqa: BLE001
        fee = None
    notional = exec_price * sz if exec_price is not None else None

    return PlannedOrder(
        ticker=row.get("market_ticker"),
        series_ticker=row.get("series_ticker"),
        side=side_yn,
        action="buy",
        size=sz,
        limit_price=exec_price,
        time_in_force=tif,
        post_only=post_only,
        max_acceptable_price=exec_price,   # no-chase: never pay above the seen ask
        no_chase=True,
        quote_age_ms=row.get("quote_age_ms"),
        expected_fee=fee,
        expected_notional=notional,
        mode=mode,
        reason_codes=reasons,
        live_submission_allowed=False,
    )


# --------------------------------------------------------------------------- #
# Dry-run live order payload (NEVER submitted; sanitized; live-disabled)
# --------------------------------------------------------------------------- #
import hashlib  # noqa: E402
import json as _json  # noqa: E402
import uuid  # noqa: E402

# The real Kalshi order endpoint — DOCUMENTED for parity; this build NEVER calls it.
KALSHI_ORDER_ENDPOINT = "/trade-api/v2/portfolio/orders"
KALSHI_ORDER_METHOD = "POST"
_TIF_ALIASES = {"fok": "fill_or_kill", "ioc": "immediate_or_cancel"}


@dataclass
class DryRunOrderPayload:
    ticker: Optional[str]
    side: Optional[str]                  # "YES" | "NO"
    action: str                          # "buy" | "sell"
    quantity: Optional[float]
    limit_price: Optional[float]         # decimal 0..1
    time_in_force: str
    client_order_id: str
    post_only: bool
    expiration_ts_ms: Optional[int]
    reason_codes: list
    source_quote_ts_ms: Optional[int]
    model_version: Optional[str]
    policy_decision_id: Optional[str]
    valid: bool
    blockers: list
    endpoint: str
    method: str
    payload: dict                        # sanitized; no secrets
    checksum: str
    venue: str = "kalshi"
    dry_run: bool = True
    live_submission_allowed: bool = False


def _norm_price(p, price_is_cents: Optional[bool]) -> Optional[float]:
    if p is None:
        return None
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if price_is_cents is True or (price_is_cents is None and v > 1.5):
        v = v / 100.0
    return v


def build_dry_run_order_payload(
    *, config, ticker, side, quantity, limit_price, tif, action="buy",
    client_order_id=None, post_only=False, expiration_ts_ms=None, reason_codes=None,
    source_quote_ts_ms=None, model_version=None, policy_decision_id=None,
    price_is_cents=None, order_type="limit",
) -> DryRunOrderPayload:
    """Validate + assemble a sanitized dry-run Kalshi order payload. NEVER submits."""
    lr = getattr(config, "live_readiness", None)
    require_fok_or_ioc = bool(getattr(lr, "require_fok_or_ioc", True))
    require_limit = bool(getattr(lr, "require_limit_order", True))
    allow_market = bool(getattr(lr, "allow_market_orders", False))
    max_size = float(getattr(lr, "max_live_order_size", 1.0))
    max_notional = float(getattr(lr, "max_live_notional", 10.0))

    blockers: list[str] = []
    side_u = (side or "").upper()
    act = (action or "").lower()
    tif_l = (tif or "").lower()
    tif_norm = _TIF_ALIASES.get(tif_l, tif_l)
    price = _norm_price(limit_price, price_is_cents)

    if not ticker:
        blockers.append("MISSING_TICKER")
    if quantity is None or float(quantity) <= 0:
        blockers.append("INVALID_QUANTITY")
    if (order_type or "").lower() == "market" or tif_norm == "market":
        if not allow_market:
            blockers.append("MARKET_ORDER_NOT_ALLOWED")
    if require_limit and price is None:
        blockers.append("MISSING_LIMIT_PRICE")
    if price is not None and not (0.0 < price < 1.0):
        blockers.append("PRICE_OUT_OF_BOUNDS")
    if side_u not in ("YES", "NO"):
        blockers.append("INVALID_SIDE")
    if act not in ("buy", "sell"):
        blockers.append("INVALID_ACTION")
    if require_fok_or_ioc and tif_norm not in ("fill_or_kill", "immediate_or_cancel"):
        blockers.append("TIF_REQUIRED_FOK_OR_IOC")
    if quantity and float(quantity) > max_size:
        blockers.append("ORDER_SIZE_OVER_LIVE_MAX")
    notional = (price * float(quantity)) if (price is not None and quantity) else None
    if notional is not None and notional > max_notional:
        blockers.append("NOTIONAL_OVER_LIVE_MAX")

    coid = client_order_id or f"btc5m-dryrun-{uuid.uuid4().hex[:16]}"
    price_cents = int(round(price * 100)) if price is not None else None
    # Kalshi order shape (sanitized; contains NO secrets). yes_price/no_price in cents.
    payload = {
        "ticker": ticker, "action": act, "side": side_u.lower(),
        "count": (int(quantity) if quantity is not None else None),
        "type": (order_type or "limit"),
        "time_in_force": tif_norm, "client_order_id": coid,
        "post_only": bool(post_only),
    }
    if side_u == "YES":
        payload["yes_price"] = price_cents
    elif side_u == "NO":
        payload["no_price"] = price_cents
    if expiration_ts_ms is not None:
        payload["expiration_ts"] = expiration_ts_ms
    checksum = hashlib.sha256(_json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    return DryRunOrderPayload(
        ticker=ticker, side=(side_u if side_u in ("YES", "NO") else None), action=act,
        quantity=quantity, limit_price=price, time_in_force=tif_norm, client_order_id=coid,
        post_only=bool(post_only), expiration_ts_ms=expiration_ts_ms,
        reason_codes=list(reason_codes or []), source_quote_ts_ms=source_quote_ts_ms,
        model_version=model_version, policy_decision_id=policy_decision_id,
        valid=(not blockers), blockers=blockers, endpoint=KALSHI_ORDER_ENDPOINT,
        method=KALSHI_ORDER_METHOD, payload=payload, checksum=checksum,
        live_submission_allowed=False)


def payload_from_intent(intent, config, *, model_version=None, policy_decision_id=None) -> DryRunOrderPayload:
    """Convert a policy CandidateOrderIntent or a LockOrderIntent into a dry-run payload (parity)."""
    side = getattr(intent, "side", None) or getattr(intent, "side_to_buy", None)
    qty = getattr(intent, "size", None)
    if qty is None:
        qty = getattr(intent, "quantity", None)
    return build_dry_run_order_payload(
        config=config, ticker=getattr(intent, "ticker", None), side=side, action="buy",
        quantity=qty, limit_price=getattr(intent, "limit_price", None),
        tif=getattr(intent, "time_in_force", "fill_or_kill"),
        reason_codes=list(getattr(intent, "reason_codes", []) or []),
        model_version=model_version, policy_decision_id=policy_decision_id, price_is_cents=False)
