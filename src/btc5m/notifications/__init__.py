"""Notifications: Pushover with a graceful Noop fallback.

The system never blocks or fails because Pushover credentials are missing — it
falls back to the NoopNotifier (console/log). Use :func:`build_notifier` to get
the right notifier for the current config.
"""

from __future__ import annotations

from ..config import AppConfig
from .base import Notifier
from .noop import NoopNotifier


def build_notifier(config: AppConfig) -> Notifier:
    """Return a Pushover notifier if enabled+configured, else a Noop fallback."""
    provider = config.notifications.provider.lower()
    if provider == "noop":
        return NoopNotifier(config)
    if provider in ("auto", "pushover") and config.notifications.pushover_configured:
        try:
            from .pushover import PushoverNotifier

            return PushoverNotifier(config)
        except Exception:
            # Never let a notifier failure take down the system.
            return NoopNotifier(config)
    return NoopNotifier(config)


__all__ = ["Notifier", "NoopNotifier", "build_notifier"]
