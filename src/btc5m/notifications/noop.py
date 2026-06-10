"""No-op notifier — logs to console/logger instead of sending.

This is the safe fallback used whenever Pushover is not enabled/configured. It
always succeeds and never raises, so missing credentials never block the system.
"""

from __future__ import annotations

import logging

from .base import Notification, Notifier

_log = logging.getLogger("btc5m.notify")


class NoopNotifier(Notifier):
    def send(self, note: Notification) -> bool:
        try:
            _log.info("[NOOP NOTIFY] %s :: %s | %s", note.title, note.event, note.body)
            # Also print so smoke tests show output without logging config.
            print(f"[NOOP NOTIFY] {note.title} :: {note.event} | {note.body}")
        except Exception:
            pass
        return True
