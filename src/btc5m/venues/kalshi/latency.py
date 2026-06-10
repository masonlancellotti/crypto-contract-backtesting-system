"""Lightweight latency instrumentation for the Kalshi hot path.

Bounded-memory percentile tracking + a rejection-by-reason counter + a timing
context manager. No third-party deps, no file I/O — safe to use inside the hot
scoring loop. Percentiles are computed only on demand (e.g. at summary time).
"""

from __future__ import annotations

import time
from collections import Counter, deque
from typing import Optional


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile (q in [0, 1]); None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class LatencyTracker:
    """Records per-phase latency samples (bounded deques) + rejection reasons."""

    def __init__(self, maxlen: int = 20_000) -> None:
        self.maxlen = maxlen
        self._samples: dict[str, deque] = {}
        self.rejections: Counter = Counter()

    def record(self, phase: str, ms: float) -> None:
        buf = self._samples.get(phase)
        if buf is None:
            buf = self._samples[phase] = deque(maxlen=self.maxlen)
        buf.append(float(ms))

    def reject(self, reason: str) -> None:
        self.rejections[reason] += 1

    def stopwatch(self, phase: str) -> "Stopwatch":
        return Stopwatch(self, phase)

    def summary(self) -> dict:
        out: dict[str, dict] = {}
        for phase, buf in self._samples.items():
            vals = list(buf)
            out[phase] = {
                "count": len(vals),
                "p50": percentile(vals, 0.50),
                "p90": percentile(vals, 0.90),
                "p99": percentile(vals, 0.99),
                "max": max(vals) if vals else None,
                "mean": (sum(vals) / len(vals)) if vals else None,
            }
        return out


class Stopwatch:
    """Context manager that records elapsed wall time (ms) into a tracker phase.

    ``with tracker.stopwatch("score") as sw: ...`` then read ``sw.ms``. A None
    tracker just times without recording (handy for ad-hoc measurement).
    """

    __slots__ = ("tracker", "phase", "ms", "_t0")

    def __init__(self, tracker: Optional[LatencyTracker], phase: str) -> None:
        self.tracker = tracker
        self.phase = phase
        self.ms = 0.0
        self._t0 = 0.0

    def __enter__(self) -> "Stopwatch":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> bool:
        self.ms = (time.perf_counter() - self._t0) * 1000.0
        if self.tracker is not None:
            self.tracker.record(self.phase, self.ms)
        return False
