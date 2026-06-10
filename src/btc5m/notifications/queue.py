"""Latency-safe notification queue.

The hot / decision path calls :meth:`NotificationQueue.enqueue`, which records an
in-memory event and returns immediately (microseconds) — it never performs a
network send. A single background daemon thread drains the queue and performs the
actual best-effort, timeout-bounded send via the wrapped :class:`Notifier`
(Pushover or Noop). Nothing in this module can block model scoring, policy / lock
evaluation, or order-intent generation.

Design rules
------------
- **Bounded.** When full: low/medium events are dropped (or coalesced); a HIGH
  priority event evicts the oldest low-priority event to make room.
- **Coalesced.** Repetitive low-priority events (WATCH / REJECTED / NO_ACTION /
  uncalibrated spam) are folded into a count instead of N pushes.
- **Failure-safe.** A send failure / timeout can never crash the caller; the
  worker swallows everything and records sanitized metrics.
- **Secret-safe.** Only event names and sanitized error strings are ever logged —
  never tokens, user keys, headers, or full payloads.
- **Explanations are background.** If an ``explanation_input`` is attached, the
  explanation text is generated *in the worker thread* (post-decision, offline,
  template-based — never an LLM/API call), then appended to the message body.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from enum import IntEnum
from typing import Callable, Deque, Optional, Tuple

from ..config import AppConfig
from .base import Notification, Notifier

_log = logging.getLogger("btc5m.notify")


class Priority(IntEnum):
    LOW = 10
    MEDIUM = 20
    HIGH = 30


# Event-name -> priority. Anything unmapped is MEDIUM. Keep in sync with docs.
_HIGH_EVENTS = frozenset({
    "PAPER_CANDIDATE", "PAPER_FILLED", "PAPER_REJECTED_IMPORTANT",
    "LOCK_FULL", "LOCK_PARTIAL", "LOCK_REJECTED_IMPORTANT",
    "LIVE_SAFETY_WARNING", "COLLECTOR_STALE", "SOURCE_STALE_CRITICAL", "ERROR",
})
_LOW_EVENTS = frozenset({
    "WATCH", "NO_ACTION", "REJECTED", "UNCALIBRATED_MODEL", "rejection", "watch",
})


def classify_priority(event: str) -> Priority:
    """Map an event name to a priority class (default MEDIUM)."""
    e = (event or "").strip()
    if e in _HIGH_EVENTS:
        return Priority.HIGH
    if e in _LOW_EVENTS:
        return Priority.LOW
    return Priority.MEDIUM


def _percentile(values, q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo) if lo != hi else s[lo]


class NotificationQueue:
    """Bounded, failure-safe, background notification sender.

    ``enqueue`` is hot-path-safe and non-blocking. The background worker performs
    the real send. Use as a context manager or call :meth:`close` to stop cleanly.
    """

    def __init__(
        self,
        notifier: Notifier,
        *,
        async_enabled: bool = True,
        maxsize: int = 500,
        send_timeout_ms: int = 750,
        drop_low_priority_when_full: bool = True,
        coalesce_low: bool = True,
        explain_fn: Optional[Callable[[object], str]] = None,
        start_worker: bool = True,
    ) -> None:
        self.notifier = notifier
        self.async_enabled = bool(async_enabled)
        self.maxsize = max(1, int(maxsize))
        self.send_timeout_ms = int(send_timeout_ms)
        self.drop_low_priority_when_full = bool(drop_low_priority_when_full)
        self.coalesce_low = bool(coalesce_low)
        self._explain_fn = explain_fn

        # Two FIFO lanes under one lock; HIGH drains before LOW/MEDIUM.
        self._high: Deque[Tuple[Notification, object]] = deque()
        self._lowmed: Deque[Tuple[Priority, Notification, object]] = deque()
        self._pending_low: Counter = Counter()    # event -> count currently queued
        self._coalesced_extra: Counter = Counter()  # event -> extra (folded) count
        self._cv = threading.Condition()
        self._stop = False
        self._sending = False

        self._metrics: Counter = Counter()
        self._enqueue_samples: Deque[float] = deque(maxlen=5000)
        self._send_samples: Deque[float] = deque(maxlen=5000)
        self._max_depth = 0
        self._last_send_ms: Optional[float] = None
        self._last_error: Optional[str] = None

        self.provider = type(notifier).__name__
        self._worker: Optional[threading.Thread] = None
        if self.async_enabled and start_worker:
            self._worker = threading.Thread(
                target=self._run, name="btc5m-notify-worker", daemon=True)
            self._worker.start()

    # ------------------------------------------------------------------ #
    # Hot-path API (non-blocking)
    # ------------------------------------------------------------------ #
    def enqueue(
        self,
        note: Notification,
        *,
        priority: Optional[Priority] = None,
        explanation_input: object = None,
    ) -> bool:
        """Record an event and return immediately. Never sends, never blocks.

        Returns True if the event was accepted (queued or coalesced), False if it
        was dropped or async is disabled. Always cheap and exception-safe.
        """
        t0 = time.perf_counter()
        try:
            pr = priority if priority is not None else classify_priority(note.event)
            with self._cv:
                if not self.async_enabled:
                    self._metrics["suppressed_async_disabled"] += 1
                    return False
                # Every routed event is one blocking send avoided on the hot path.
                self._metrics["blocking_sends_prevented"] += 1
                accepted = self._offer_locked(pr, note, explanation_input)
                if accepted:
                    self._cv.notify()
                self._max_depth = max(self._max_depth, len(self._high) + len(self._lowmed))
                return accepted
        except Exception:  # never raise out of the hot path
            self._metrics["enqueue_errors"] += 1
            return False
        finally:
            self._enqueue_samples.append((time.perf_counter() - t0) * 1000.0)

    def _offer_locked(self, pr: Priority, note: Notification, expl: object) -> bool:
        total = len(self._high) + len(self._lowmed)
        if pr >= Priority.HIGH:
            if total >= self.maxsize and not self._evict_one_low_locked("dropped_low_for_high"):
                self._metrics["dropped_high_full"] += 1
                return False
            self._high.append((note, expl))
            self._metrics["enqueued_high"] += 1
            return True
        # LOW: coalesce repeats of the same event into a count.
        if pr <= Priority.LOW and self.coalesce_low and self._pending_low[note.event] >= 1:
            self._coalesced_extra[note.event] += 1
            self._metrics["coalesced"] += 1
            return True
        if total >= self.maxsize:
            if pr <= Priority.LOW:
                if self.drop_low_priority_when_full:
                    self._metrics["dropped_low_full"] += 1
                    return False
                if not self._evict_one_low_locked("dropped_low_for_low"):
                    self._metrics["dropped_low_full"] += 1
                    return False
            elif not self._evict_one_low_locked("dropped_low_for_medium"):
                self._metrics["dropped_medium_full"] += 1
                return False
        self._lowmed.append((pr, note, expl))
        if pr <= Priority.LOW:
            self._pending_low[note.event] += 1
        self._metrics["enqueued_lowmed"] += 1
        return True

    def _evict_one_low_locked(self, metric: str) -> bool:
        """Drop the oldest LOW item to free space for a higher-priority event."""
        for idx, (pr, note, _expl) in enumerate(self._lowmed):
            if pr <= Priority.LOW:
                del self._lowmed[idx]
                self._pending_low[note.event] = max(0, self._pending_low[note.event] - 1)
                self._metrics[metric] += 1
                return True
        return False

    # ------------------------------------------------------------------ #
    # Background worker
    # ------------------------------------------------------------------ #
    def _next_locked(self):
        if self._high:
            note, expl = self._high.popleft()
            return Priority.HIGH, note, expl
        if self._lowmed:
            pr, note, expl = self._lowmed.popleft()
            if pr <= Priority.LOW:
                self._pending_low[note.event] = max(0, self._pending_low[note.event] - 1)
            return pr, note, expl
        return None

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._stop and not self._high and not self._lowmed:
                    self._cv.wait(timeout=1.0)
                if self._stop and not self._high and not self._lowmed:
                    return
                item = self._next_locked()
                if item is None:
                    continue
                self._sending = True
            pr, note, expl = item
            self._send_one(note, expl)
            with self._cv:
                self._sending = False
                self._cv.notify_all()

    def _send_one(self, note: Notification, expl: object) -> None:
        # Fold any coalesced repeats + (offline) explanation into the body — done
        # here in the WORKER, never on the decision path.
        try:
            extra = self._coalesced_extra.pop(note.event, 0)
            if extra:
                note = Notification(note.event, note.title,
                                    f"{note.body} (+{extra} more)", note.data)
            if expl is not None and self._explain_fn is not None:
                try:
                    text = self._explain_fn(expl)
                    if text:
                        note = Notification(note.event, note.title,
                                            f"{note.body} — {text}", note.data)
                except Exception:  # explanation is best-effort, never fatal
                    self._metrics["explanation_errors"] += 1
        except Exception:
            pass
        t0 = time.perf_counter()
        ok = False
        try:
            ok = bool(self.notifier.send(note))
        except Exception as exc:  # notifier.send shouldn't raise, but be defensive
            self._last_error = type(exc).__name__
            self._metrics["send_exceptions"] += 1
        dt = (time.perf_counter() - t0) * 1000.0
        self._send_samples.append(dt)
        self._last_send_ms = dt
        self._metrics["sent" if ok else "failed"] += 1
        if not ok and self._last_error is None:
            self._last_error = "send_returned_false"

    # ------------------------------------------------------------------ #
    # Lifecycle + introspection
    # ------------------------------------------------------------------ #
    def flush(self, timeout: float = 5.0) -> bool:
        """Block (test/shutdown helper, NOT for the hot path) until drained."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._high or self._lowmed or self._sending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(timeout=min(0.05, remaining))
            return True

    def close(self, timeout: float = 2.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        w = self._worker
        if w is not None and w.is_alive():
            w.join(timeout=timeout)

    def __enter__(self) -> "NotificationQueue":
        return self

    def __exit__(self, *exc: object) -> bool:
        self.flush(timeout=2.0)
        self.close()
        return False

    @property
    def depth(self) -> int:
        with self._cv:
            return len(self._high) + len(self._lowmed)

    def health(self) -> dict:
        m = self._metrics
        send = list(self._send_samples)
        enq = list(self._enqueue_samples)
        dropped = (m["dropped_low_full"] + m["dropped_medium_full"]
                   + m["dropped_high_full"] + m["dropped_low_for_high"]
                   + m["dropped_low_for_medium"])
        return {
            "provider": self.provider,
            "async_enabled": self.async_enabled,
            "queue_depth": self.depth,
            "queue_maxsize": self.maxsize,
            "max_depth_seen": self._max_depth,
            "send_timeout_ms": self.send_timeout_ms,
            "drop_low_priority_when_full": self.drop_low_priority_when_full,
            "coalesce_low": self.coalesce_low,
            "sent": m["sent"],
            "failed": m["failed"],
            "dropped": dropped,
            "dropped_by_reason": {
                "low_full": m["dropped_low_full"],
                "medium_full": m["dropped_medium_full"],
                "high_full": m["dropped_high_full"],
                "low_evicted_for_high": m["dropped_low_for_high"],
                "low_evicted_for_medium": m["dropped_low_for_medium"],
            },
            "coalesced": m["coalesced"],
            "suppressed_async_disabled": m["suppressed_async_disabled"],
            "blocking_sends_prevented": m["blocking_sends_prevented"],
            "enqueue_latency_ms": {"p50": _percentile(enq, 0.50),
                                   "p95": _percentile(enq, 0.95),
                                   "max": max(enq) if enq else None,
                                   "n": len(enq)},
            "send_latency_ms": {"p50": _percentile(send, 0.50),
                                "p95": _percentile(send, 0.95),
                                "max": max(send) if send else None,
                                "n": len(send)},
            "latest_send_latency_ms": self._last_send_ms,
            "last_error": self._last_error,  # sanitized (type/short string only)
        }


def build_notification_queue(
    cfg: AppConfig,
    *,
    notifier: Optional[Notifier] = None,
    explain_fn: Optional[Callable[[object], str]] = None,
    start_worker: bool = True,
) -> NotificationQueue:
    """Build a queue wrapping the resolved notifier (Pushover if configured else Noop).

    Honors ``cfg.notifications`` async settings. Default is Noop + async, so it is
    safe and silent unless Pushover is explicitly enabled+configured.
    """
    if notifier is None:
        from . import build_notifier
        notifier = build_notifier(cfg)
    if explain_fn is None:
        try:
            from .explanations import explain
            explain_fn = explain
        except Exception:  # explanations are optional
            explain_fn = None
    n = cfg.notifications
    return NotificationQueue(
        notifier,
        async_enabled=getattr(n, "async_enabled", True),
        maxsize=getattr(n, "queue_maxsize", 500),
        send_timeout_ms=getattr(n, "send_timeout_ms", 750),
        drop_low_priority_when_full=getattr(n, "drop_low_priority_when_full", True),
        coalesce_low=getattr(n, "coalesce_watch", True),
        explain_fn=explain_fn,
        start_worker=start_worker,
    )
