"""Notifier interface and shared message formatting.

Notifiers must NEVER raise out of :meth:`send` and must NEVER log secrets/tokens.
Convenience helpers produce the project's standard short message formats for
candidates, fills, rejections, the kill switch, watches, and the EOD summary.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from ..config import AppConfig


@dataclass
class Notification:
    event: str       # short event name (suffixed onto the configured prefix)
    title: str
    body: str
    data: dict | None = None


class Notifier(abc.ABC):
    def __init__(self, config: AppConfig):
        self.config = config
        self.prefix = config.notifications.event_prefix or "btc5m"

    def event_name(self, suffix: str) -> str:
        return f"{self.prefix}_{suffix}" if suffix else self.prefix

    @abc.abstractmethod
    def send(self, note: Notification) -> bool:
        """Send a notification. Returns True on success. Must never raise."""

    # ----- Standard message helpers ----------------------------------------
    def paper_candidate(self, body: str) -> bool:
        # e.g. "BUY YES @ 0.57 | model 0.63 | net edge +3.5c | expires 00:35"
        return self.send(Notification("paper_candidate", "BTC 5m PAPER_CANDIDATE", body))

    def fill(self, body: str) -> bool:
        return self.send(Notification("fill", "BTC 5m FILL", body))

    def rejection(self, body: str) -> bool:
        # e.g. "model edge +4.0c rejected: stale quote / thin depth"
        return self.send(Notification("rejection", "BTC 5m WATCH", body))

    # Alias kept for readability at call sites that mean the same thing.
    def watch(self, body: str) -> bool:
        return self.send(Notification("watch", "BTC 5m WATCH", body))

    def kill(self, body: str) -> bool:
        return self.send(Notification("kill", "BTC 5m KILL", body))

    def eod(self, body: str) -> bool:
        return self.send(Notification("eod", "BTC 5m EOD", body))
