"""End-of-day summary builder + sender.

Aggregates the day's signals/fills into the project's standard EOD message and
sends it via the resolved notifier (Pushover or Noop). The summary builder is
implemented for a simple in-memory stats dict; richer aggregation over recorded
data is a future step.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from . import build_notifier


@dataclass
class EodStats:
    signals: int = 0
    paper_fills: int = 0
    net_paper_pnl: float = 0.0
    hit_rate: float | None = None
    best_bucket_cents: float | None = None
    main_reject_reason: str = "n/a"


def format_eod(stats: EodStats) -> str:
    """Render the standard EOD line.

    e.g. "42 signals | 9 paper fills | net +$12.40 paper | hit 56% |
          main reject: stale quotes"
    """
    hit = f"{stats.hit_rate * 100:.0f}%" if stats.hit_rate is not None else "n/a"
    parts = [
        f"{stats.signals} signals",
        f"{stats.paper_fills} paper fills",
        f"net ${stats.net_paper_pnl:+.2f} paper",
        f"hit {hit}",
    ]
    if stats.best_bucket_cents is not None:
        parts.append(f"best bucket +{stats.best_bucket_cents:.1f}c")
    parts.append(f"main reject: {stats.main_reject_reason}")
    return " | ".join(parts)


def send_eod_summary(config: AppConfig, stats: EodStats) -> bool:
    """Build and send the EOD summary; returns True on send success."""
    notifier = build_notifier(config)
    return notifier.eod(format_eod(stats))
