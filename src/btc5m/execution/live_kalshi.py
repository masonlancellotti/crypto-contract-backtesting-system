"""Live Kalshi execution adapter — DISABLED by default; refuses every order.

This implements only dry-run / live-disabled checks. It NEVER places an order in
this build. Live would require ALL gates clear: live mode + enabled + kill switch
off + Kalshi auth configured + (risk/calibration/fresh-book checks done upstream).
Secrets are never printed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class LiveKalshiExecutionAdapter:
    """Refuses orders unless every live gate is clear (never clear by default)."""

    venue = "kalshi"

    def __init__(self, config):
        self.config = config

    def live_blockers(self) -> list[str]:
        c = self.config
        k = c.kalshi
        lr = getattr(c, "live_readiness", None)
        blockers: list[str] = []
        if c.trading_mode.lower() != "live":
            blockers.append(f"TRADING_MODE is '{c.trading_mode}', not 'live'")
        if not c.live_trading_enabled:
            blockers.append("LIVE_TRADING_ENABLED is false")
        if not bool(getattr(lr, "submit_enabled", False)):
            blockers.append("KALSHI_LIVE_SUBMIT_ENABLED is false")
        if bool(getattr(lr, "dry_run_only", True)):
            blockers.append("KALSHI_LIVE_DRY_RUN_ONLY is true (dry-run only)")
        if c.kill_switch_enabled:
            blockers.append("KILL_SWITCH_ENABLED is true (kill switch active)")
        if not k.auth_configured:
            blockers.append("Kalshi auth not configured (KALSHI_KEY_ID / KALSHI_PRIVATE_KEY_PATH)")
        elif not _readable(k.private_key_path):
            blockers.append("KALSHI_PRIVATE_KEY_PATH is set but not readable")
        if c.require_manual_confirmation:
            blockers.append("manual confirmation required but no confirmation handler set")
        return blockers

    def preflight(self, order=None, ctx=None) -> list[str]:
        """Return the list of reasons an order would be refused (empty => allowed)."""
        return self.live_blockers()

    def _refusal(self, action: str) -> dict:
        return {"status": "rejected", "is_paper": True, "venue": self.venue, "action": action,
                "reason": "live trading disabled", "live_submission_allowed": False,
                "blockers": self.live_blockers()}

    def submit(self, order=None, ctx=None) -> dict:
        """ALWAYS refuses — no HTTP mutation is ever issued in this build."""
        # No network call is made here; the safe terminal posture is NO live order.
        return self._refusal("submit")

    def cancel(self, order_id=None, ctx=None) -> dict:
        """ALWAYS refuses — no cancel HTTP mutation is ever issued in this build."""
        return self._refusal("cancel")

    def _http_mutation(self, *args, **kwargs):  # pragma: no cover - guard
        """Hard guard: any attempt to issue a mutating order request raises."""
        raise RuntimeError("live order mutation is blocked in this build (live disabled)")


def _readable(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= 0
    except OSError:
        return False


def kalshi_auth_smoke(config) -> dict:
    """Inspect Kalshi auth configuration WITHOUT printing any secret or signing
    a live request. Reports presence/readability only."""
    k = config.kalshi
    try:
        import cryptography  # noqa: F401
        signing_lib = True
    except Exception:  # noqa: BLE001
        signing_lib = False
    return {
        "env": k.env,
        "api_base": k.api_base,
        "ws_url": k.ws_url,
        "series_ticker": k.series_ticker,
        "key_id_present": bool(k.key_id),
        "private_key_path_present": bool(k.private_key_path),
        "private_key_readable": _readable(k.private_key_path),
        "auth_configured": k.auth_configured,
        "rsa_signing_lib_available": signing_lib,
        "public_market_data_usable_without_auth": True,
        "live_trading_enabled": config.live_trading_enabled,
        "note": "public REST market data needs no auth; auth only for WS/account/live. "
                "No secrets printed; no orders placed.",
    }
