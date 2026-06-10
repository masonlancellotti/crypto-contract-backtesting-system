"""Kalshi live-readiness scaffolding — inspect the live path WITHOUT enabling it.

Validates every live gate, builds/validates dry-run order payloads, and reports
exactly what blocks live submission — but **never submits**. ``live_submission_allowed``
is always False; the kill switch, manual-confirmation, model/calibration/backtest/
paper-evidence, and risk gates are all enforced and never bypassed. Credentials are
checked for presence/readability only — no key material, passphrase, or auth header
is ever read or printed.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...execution.risk import RiskManager
from ...schemas import Order, OrderSide, Outcome
from ...timeutils import now_ms

# ----- readiness states (no LIVE_READY_TO_SUBMIT / SUBMITTED / LIVE_FILLED) -----
NOT_CONFIGURED = "NOT_CONFIGURED"
LIVE_DISABLED = "LIVE_DISABLED"
KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
MODEL_NOT_APPROVED = "MODEL_NOT_APPROVED"
CALIBRATOR_NOT_APPROVED = "CALIBRATOR_NOT_APPROVED"
BACKTEST_NOT_APPROVED = "BACKTEST_NOT_APPROVED"
PAPER_EVIDENCE_MISSING = "PAPER_EVIDENCE_MISSING"
RISK_BLOCKED = "RISK_BLOCKED"
SOURCE_HEALTH_BLOCKED = "SOURCE_HEALTH_BLOCKED"
ORDER_PLAN_INVALID = "ORDER_PLAN_INVALID"
MANUAL_CONFIRMATION_REQUIRED = "MANUAL_CONFIRMATION_REQUIRED"
DRY_RUN_READY = "DRY_RUN_READY"
WOULD_SUBMIT_IF_ENABLED = "WOULD_SUBMIT_IF_ENABLED"
BLOCKED = "BLOCKED"


# --------------------------------------------------------------------------- #
# Manual confirmation scaffold (no auto-confirm; absent by default => blocked)
# --------------------------------------------------------------------------- #
@dataclass
class ConfirmationRequired:
    ticker: Optional[str]
    side: Optional[str]
    quantity: Optional[float]
    price: Optional[float]
    expected_max_loss: Optional[float]
    model_version: Optional[str]
    reason_code: str
    timestamp_ms: int
    satisfied: bool = False
    token: Optional[str] = None


class ManualConfirmationProvider(abc.ABC):
    @abc.abstractmethod
    def confirm(self, req: ConfirmationRequired) -> bool:
        """Return True only on an explicit local operator confirmation. Never auto-true."""


class NoConfirmationProvider(ManualConfirmationProvider):
    """Default provider: there is NO way to confirm -> live stays blocked."""

    def confirm(self, req: ConfirmationRequired) -> bool:
        return False


def manual_confirmation_status(config, provider: Optional[ManualConfirmationProvider] = None) -> dict:
    required = bool(config.require_manual_confirmation)
    # No provider is wired by default -> a required confirmation can never be satisfied.
    satisfied = False
    return {"required": required, "provider_present": provider is not None,
            "satisfied": satisfied, "note": "manual confirmation is never auto-granted"}


# --------------------------------------------------------------------------- #
# Credential preflight (presence/readability only; NO secret values)
# --------------------------------------------------------------------------- #
def _readable(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        p = Path(path)
        return p.is_file()
    except OSError:
        return False


def credential_status(config) -> dict:
    k = config.kalshi
    return {
        "key_id_present": bool(k.key_id),
        "private_key_path_present": bool(k.private_key_path),
        "private_key_file_exists": _readable(k.private_key_path),
        "private_key_readable": _readable(k.private_key_path),
        "private_key_parse_check": "skipped (no key material read)",
        "api_base_url_configured": bool(k.api_base),
        "websocket_url_configured": bool(k.ws_url),
        "auth_configured": bool(k.auth_configured),
    }


# --------------------------------------------------------------------------- #
# Paper evidence gate (never auto-approved)
# --------------------------------------------------------------------------- #
def paper_evidence_status(config) -> dict:
    """Read the (optional) live-approval file + gather paper counts. Default: not approved."""
    approval_path = config.data_path() / "models" / "kalshi_live_approval.json"
    approved = False
    meta: dict = {}
    if approval_path.exists():
        try:
            meta = json.loads(approval_path.read_text(encoding="utf-8"))
            approved = bool(meta.get("evidence_approved_for_live", False))
        except Exception:  # noqa: BLE001
            meta = {"error": "approval file unreadable"}
    # Best-effort paper trade counts from the policy paper ledger (no secrets).
    paper_trades = 0
    pdir = config.data_path() / "paper"
    if pdir.exists():
        for p in pdir.glob("kalshi_policy_paper_ledger-*.jsonl"):
            try:
                paper_trades += sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
            except OSError:
                continue
    return {"approval_file_present": approval_path.exists(),
            "evidence_approved_for_live": approved, "paper_trade_count": paper_trades,
            "model_version": meta.get("model_version"),
            "calibration_version": meta.get("calibration_version"),
            "backtest_report_version": meta.get("backtest_report_version"),
            "note": "paper evidence is NEVER auto-approved; requires an explicit approval file"}


def source_health_status(config) -> dict:
    try:
        from .source_health import assess_source_health
        h = assess_source_health(config)
        u = h["underlying"]
        by = {s["source"]: s for s in h["sources"]}
        return {"underlying_ok": u["underlying_ok"], "kalshi_stale": by.get("kalshi", {}).get("stale"),
                "coinbase_stale": by.get("coinbase", {}).get("stale"),
                "binance_stale": by.get("binance", {}).get("stale")}
    except Exception:  # noqa: BLE001
        return {"underlying_ok": False, "error": "source-health unavailable"}


# --------------------------------------------------------------------------- #
# Risk preflight (wires the existing RiskManager + live-specific limits)
# --------------------------------------------------------------------------- #
def risk_preflight(config, order_payload=None) -> dict:
    lr = config.live_readiness
    price = (order_payload.limit_price if order_payload and order_payload.limit_price else 0.5)
    size = (order_payload.quantity if order_payload and order_payload.quantity else 1.0)
    side = order_payload.side if order_payload else "YES"
    ticker = (order_payload.ticker if order_payload else None) or "KXBTC15M-PREFLIGHT"
    order = Order(contract_id=ticker, outcome=(Outcome.YES if side == "YES" else Outcome.NO),
                  side=OrderSide.BUY, price=float(price), size=float(size))
    decision = RiskManager(config).evaluate(order)
    reasons = list(decision.reasons)
    # live-specific caps (in addition to the standard risk manager)
    if size > lr.max_live_order_size:
        reasons.append(f"size {size} > KALSHI_MAX_LIVE_ORDER_SIZE {lr.max_live_order_size}")
    if price * size > lr.max_live_notional:
        reasons.append(f"notional {price*size:.2f} > KALSHI_MAX_LIVE_NOTIONAL {lr.max_live_notional}")
    return {"approved": (decision.approved and len(reasons) == 0), "reasons": reasons}


# --------------------------------------------------------------------------- #
# Validity (reuse the policy runtime's disk assessment)
# --------------------------------------------------------------------------- #
def _validity(config):
    from .policy_runtime import (
        assess_backtest_validity, assess_calibration_validity, assess_model_validity,
    )
    return (assess_model_validity(config), assess_calibration_validity(config),
            assess_backtest_validity(config))


_SWITCH_STATES = {LIVE_DISABLED, KILL_SWITCH_ACTIVE, MANUAL_CONFIRMATION_REQUIRED}
_PRECEDENCE = [LIVE_DISABLED, KILL_SWITCH_ACTIVE, MISSING_CREDENTIALS, MODEL_NOT_APPROVED,
               CALIBRATOR_NOT_APPROVED, BACKTEST_NOT_APPROVED, PAPER_EVIDENCE_MISSING,
               SOURCE_HEALTH_BLOCKED, RISK_BLOCKED, MANUAL_CONFIRMATION_REQUIRED]


def assess_live_readiness(config, *, order_payload=None,
                          manual_provider: Optional[ManualConfirmationProvider] = None) -> dict:
    """Assemble the full live-readiness result. NEVER submits; live_submission_allowed=False."""
    lr = config.live_readiness
    cred = credential_status(config)
    mv, cv, bv = _validity(config)
    paper = paper_evidence_status(config)
    risk = risk_preflight(config, order_payload)
    sh = source_health_status(config)
    conf = manual_confirmation_status(config, manual_provider)

    blockers: list[dict] = []
    codes: set[str] = set()

    def add(code: str, msg: str):
        blockers.append({"code": code, "message": msg})
        codes.add(code)

    # live-enable switches
    if config.trading_mode.lower() != "live":
        add(LIVE_DISABLED, f"TRADING_MODE is '{config.trading_mode}', not 'live'")
    if not config.live_trading_enabled:
        add(LIVE_DISABLED, "LIVE_TRADING_ENABLED is false")
    if not lr.submit_enabled:
        add(LIVE_DISABLED, "KALSHI_LIVE_SUBMIT_ENABLED is false")
    if lr.dry_run_only:
        add(LIVE_DISABLED, "KALSHI_LIVE_DRY_RUN_ONLY is true (dry-run only)")
    if config.kill_switch_enabled:
        add(KILL_SWITCH_ACTIVE, "KILL_SWITCH_ENABLED is true")
    if not cred["auth_configured"]:
        add(MISSING_CREDENTIALS, "Kalshi auth not configured (KALSHI_KEY_ID / KALSHI_PRIVATE_KEY_PATH)")
    elif not cred["private_key_readable"]:
        add(MISSING_CREDENTIALS, "KALSHI_PRIVATE_KEY_PATH set but not readable")
    if lr.require_approved_model and not (mv.exists and mv.trained and not mv.diagnostic_only):
        add(MODEL_NOT_APPROVED, "no approved (trained, non-diagnostic) model artifact")
    if lr.require_valid_calibrator and not (cv.exists and cv.valid and not cv.diagnostic_only):
        add(CALIBRATOR_NOT_APPROVED, "no valid (non-diagnostic) calibrator")
    if lr.require_valid_backtest and not bv.valid:
        add(BACKTEST_NOT_APPROVED, "no valid backtest evidence above gate")
    if lr.require_paper_evidence and not paper["evidence_approved_for_live"]:
        add(PAPER_EVIDENCE_MISSING, "paper evidence not approved for live (no approval file)")
    if lr.require_source_health and not sh.get("underlying_ok"):
        add(SOURCE_HEALTH_BLOCKED, "underlying source health not OK")
    if not risk["approved"]:
        add(RISK_BLOCKED, "risk preflight blocked: " + "; ".join(risk["reasons"][:4]))
    if conf["required"] and not conf["satisfied"]:
        add(MANUAL_CONFIRMATION_REQUIRED, "manual confirmation required and not satisfied")

    # order plan status
    order_plan_status = "NONE"
    if order_payload is not None:
        order_plan_status = "VALID" if order_payload.valid else "INVALID"
        if not order_payload.valid:
            for b in order_payload.blockers:
                add(ORDER_PLAN_INVALID, f"order plan invalid: {b}")

    # headline state
    if not lr.enabled:
        state = NOT_CONFIGURED
    elif order_plan_status == "INVALID":
        state = ORDER_PLAN_INVALID
    elif order_plan_status == "VALID":
        non_switch = codes - _SWITCH_STATES
        state = WOULD_SUBMIT_IF_ENABLED if not non_switch else DRY_RUN_READY
    else:
        state = next((s for s in _PRECEDENCE if s in codes), BLOCKED)

    return {
        "series": getattr(config.kalshi, "series_ticker", "KXBTC15M"),
        "state": state,
        "blockers": blockers,
        "warnings": ([] if cred["auth_configured"] else
                     ["public market data needs no auth; auth only required for live"]),
        "required_next_actions": _next_actions(codes, lr),
        "credential_status_without_values": cred,
        "model_status": {"exists": mv.exists, "trained": mv.trained,
                         "diagnostic_only": mv.diagnostic_only, "version": mv.version},
        "calibration_status": {"exists": cv.exists, "valid": cv.valid,
                               "diagnostic_only": cv.diagnostic_only},
        "backtest_status": {"exists": bv.exists, "valid": bv.valid, "windows": bv.windows},
        "paper_evidence_status": paper,
        "risk_status": risk,
        "source_health_status": sh,
        "order_plan_status": order_plan_status,
        "kill_switch_status": {"active": bool(config.kill_switch_enabled)},
        "manual_confirmation_status": conf,
        "readiness_enabled": lr.enabled,
        "dry_run_only": True,
        "live_submission_allowed": False,
    }


def _next_actions(codes: set, lr) -> list[str]:
    actions = []
    if MODEL_NOT_APPROVED in codes:
        actions.append("train + approve a non-diagnostic model (kalshi-train-baselines above gate)")
    if CALIBRATOR_NOT_APPROVED in codes:
        actions.append("fit a valid calibrator (kalshi-calibrate-model above gate)")
    if BACKTEST_NOT_APPROVED in codes:
        actions.append("produce a valid non-diagnostic executable backtest above gate")
    if PAPER_EVIDENCE_MISSING in codes:
        actions.append("accumulate paper evidence + create data/models/kalshi_live_approval.json (manual)")
    if MISSING_CREDENTIALS in codes:
        actions.append("set KALSHI_KEY_ID + KALSHI_PRIVATE_KEY_PATH (env-only; never in chat)")
    actions.append("a SEPARATE future prompt must explicitly enable live after evidence; not now")
    return actions


# --------------------------------------------------------------------------- #
# Audit logging (sanitized; no secrets)
# --------------------------------------------------------------------------- #
def write_audit_log(config, result: dict, *, ticker: Optional[str] = None,
                    order_payload=None) -> str:
    d = config.data_path() / "audit"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_live_readiness_{day}.jsonl"
    row = {
        "timestamp": now_ms(), "series": result.get("series"), "ticker": ticker,
        "dry_run": True, "live_submission_allowed": False,
        "readiness_state": result.get("state"),
        "blockers": [b["code"] for b in result.get("blockers", [])],
        "order_payload": (order_payload.payload if order_payload else None),
        "order_payload_checksum": (order_payload.checksum if order_payload else None),
        "order_plan_status": result.get("order_plan_status"),
        "risk_status": result.get("risk_status"),
        "model_version": result.get("model_status", {}).get("version"),
        "calibration_valid": result.get("calibration_status", {}).get("valid"),
        "backtest_valid": result.get("backtest_status", {}).get("valid"),
        "credentials_present": result.get("credential_status_without_values", {}).get("auth_configured"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return str(path)


# --------------------------------------------------------------------------- #
# Optional read-only private preflight (safe; no orders/cancels/mutations)
# --------------------------------------------------------------------------- #
def kalshi_private_read_preflight(config, *, allow_private_read: bool = False) -> dict:
    """Report whether read-only private endpoints could be called. Calls NONE here.

    This build does not implement authenticated private reads, so it reports a clear
    blocker. It NEVER submits or cancels and NEVER prints secrets.
    """
    cred = credential_status(config)
    if not cred["auth_configured"]:
        return {"status": "MISSING_CREDENTIALS", "called_any_endpoint": False,
                "credentials_present": False, "live_submission_allowed": False}
    if not (allow_private_read and config.live_readiness.allow_private_reads):
        return {"status": "PRIVATE_READS_DISABLED", "called_any_endpoint": False,
                "note": "set KALSHI_LIVE_ALLOW_PRIVATE_READS=true AND pass --allow-private-read",
                "live_submission_allowed": False}
    return {"status": "NOT_IMPLEMENTED", "called_any_endpoint": False,
            "note": "authenticated private read endpoints are a scaffold (RSA signing not wired); "
                    "no network call made; no orders; no secrets printed",
            "live_submission_allowed": False}
