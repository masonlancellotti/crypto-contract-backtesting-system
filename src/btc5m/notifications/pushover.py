"""Pushover notifier.

Sends short push notifications via the Pushover Messages API using the standard
library (``urllib``) so no third-party dependency is required. Credentials come
from env/config only.

Safety contract:
- Never raises out of :meth:`send` — returns False and logs a safe warning.
- Never logs the app token, user key, or the full auth payload.
- Only builds when explicitly enabled AND both required credentials are present.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from ..config import AppConfig
from .base import Notification, Notifier

_log = logging.getLogger("btc5m.notify")


class PushoverNotifier(Notifier):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        n = config.notifications
        if not n.pushover_configured:
            # Guard: callers should use build_notifier(), which checks first.
            raise ValueError("Pushover is not enabled/configured")
        self._app_token = n.pushover_app_token
        self._user_key = n.pushover_user_key
        self._device = n.pushover_device
        self._priority = n.pushover_priority
        self._sound = n.pushover_sound
        self._api_url = n.pushover_api_url
        # Per-send network timeout (latency-safe; clamped to 0.05-5.0s). The
        # background worker owns this call, so it never blocks the decision path.
        self._timeout_s = min(5.0, max(0.05, (getattr(n, "send_timeout_ms", 750) or 750) / 1000.0))

    def _build_payload(self, note: Notification) -> dict:
        # `title` is short; `message` is the body. Keep messages compact.
        payload = {
            "token": self._app_token,
            "user": self._user_key,
            "title": note.title,
            "message": note.body,
            "priority": self._priority,
        }
        if self._device:
            payload["device"] = self._device
        if self._sound:
            payload["sound"] = self._sound
        return payload

    def send(self, note: Notification) -> bool:
        try:
            data = urllib.parse.urlencode(self._build_payload(note)).encode("utf-8")
            req = urllib.request.Request(
                self._api_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read().decode("utf-8", "replace")
                body = json.loads(raw) if raw else {}
                if resp.status == 200 and body.get("status") == 1:
                    return True
                # Do NOT log the request payload (it contains secrets).
                _log.warning(
                    "Pushover send rejected (http=%s, status=%s); message dropped: %s",
                    resp.status,
                    body.get("status"),
                    note.title,
                )
                return False
        except Exception as exc:  # never raise out of a notifier
            # Log only the exception type/message and the human title — no secrets.
            _log.warning("Pushover send failed (%s); message dropped: %s", exc, note.title)
            return False
