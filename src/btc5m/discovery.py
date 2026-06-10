"""Clock-driven discovery + window classification for rolling BTC 5m markets.

Polymarket lists every 5-minute Up/Down window as its own market/event with a
slug of the form ``<asset>-updown-<duration>-<unix_ts>`` where ``<unix_ts>`` is
the **window START** in epoch SECONDS, aligned to the duration step (300s for
5m). This is VERIFIED against the live Gamma API (2026-06-01):

    slug btc-updown-5m-1780288800  ->  eventStartTime 2026-06-01T04:40:00Z
                                       endDate         2026-06-01T04:45:00Z  (start + 300s)

Because the slug timestamp is deterministic, the most reliable discovery is to
ENUMERATE the slugs around "now" and batch-fetch them. This is independent of API
sort order, of Polymarket listing windows ~24h ahead, and of local clock skew.

Why this module exists: the previous discovery sorted ``/markets`` by
``startDate`` descending (newest-CREATED first). Each window is listed ~24h
before it opens, so that query returned only the freshly-listed far-future batch
and systematically MISSED every currently-live window. Live verification:
``order=startDate desc`` returned 1 far-future market; the end-date-window query
returned 0; while the current window (fetched by slug) existed and was accepting
orders. Slug enumeration around "now" returned 15/15 near-term windows.

Nothing here places orders or needs credentials.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

# Default classification horizons (ms). A window opening within the next hour is
# "upcoming" and worth recording; further out it is the pre-listed far-future
# batch. A just-expired window stays "post-window (unresolved)" for an hour
# before it is treated as stale.
DEFAULT_UPCOMING_HORIZON_MS = 60 * 60 * 1000
DEFAULT_POST_WINDOW_HORIZON_MS = 60 * 60 * 1000

# Safety cap so an absurd lookahead can never generate an unbounded slug list.
_MAX_ENUMERATED_WINDOWS = 4000

_SLUG_RE = re.compile(r"^([a-z0-9]+)-updown-(\d+[a-smhd]+)-(\d+)$")
_DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$")

_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class WindowPhase(str, Enum):
    """Timing phase of a market's measurement window relative to ``now``.

    These are TIMING phases derived from window start/expiry + resolution state.
    ``acceptingOrders`` is an ORTHOGONAL venue flag (a market can accept orders
    long before its window opens) and is reported separately — never conflated
    with :attr:`CURRENTLY_IN_WINDOW`.
    """

    UPCOMING_PRE_WINDOW = "UPCOMING_PRE_WINDOW"          # opens within the upcoming horizon
    CURRENTLY_IN_WINDOW = "CURRENTLY_IN_WINDOW"          # window_start <= now <= expiry
    POST_WINDOW_NOT_RESOLVED = "POST_WINDOW_NOT_RESOLVED"  # expired recently, not yet closed
    RESOLVED_OR_CLOSED = "RESOLVED_OR_CLOSED"            # closed/archived/resolved
    STALE_PAST = "STALE_PAST"                            # expired long ago, never closed
    FAR_FUTURE = "FAR_FUTURE"                            # opens beyond the upcoming horizon
    UNKNOWN_TIMING = "UNKNOWN_TIMING"                    # missing window_start / expiry


def duration_to_seconds(duration: str) -> int:
    """Parse a duration token like ``5m`` / ``15m`` / ``1h`` into seconds.

    Defaults to 300 (5m) only for the exact token ``5m``; any other unparseable
    value raises so callers never silently misalign the slug grid.
    """
    m = _DURATION_RE.match((duration or "").strip().lower())
    if not m:
        raise ValueError(f"unrecognized duration {duration!r} (expected e.g. 5m, 15m, 1h)")
    return int(m.group(1)) * _DURATION_UNIT_SECONDS[m.group(2)]


def slug_prefix(asset: str, duration: str) -> str:
    """Slug prefix for the Up/Down series, e.g. BTC + 5m -> ``btc-updown-5m-``."""
    return f"{asset.strip().lower()}-updown-{duration.strip().lower()}-"


def make_slug(asset: str, duration: str, window_start_s: int) -> str:
    """Build the canonical slug for a window-start second."""
    return f"{slug_prefix(asset, duration)}{int(window_start_s)}"


def parse_slug(slug: str) -> Optional[tuple[str, str, int]]:
    """Parse ``<asset>-updown-<duration>-<ts>`` -> (asset, duration, window_start_s).

    Returns None if the slug does not match the Up/Down series pattern.
    """
    if not slug:
        return None
    m = _SLUG_RE.match(slug.strip().lower())
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def slug_window_start_ms(slug: str) -> Optional[int]:
    """Window-start epoch ms derived purely from the slug timestamp (seconds)."""
    parsed = parse_slug(slug)
    return parsed[2] * 1000 if parsed else None


def align_window_start_s(now_ms: int, step_s: int) -> int:
    """Floor ``now`` to the duration grid (e.g. nearest past 5-min boundary)."""
    return (int(now_ms) // 1000 // step_s) * step_s


def enumerate_window_starts(
    now_ms: int, step_s: int, *, lookback_s: int, lookahead_s: int
) -> list[int]:
    """All window-start seconds on the grid within [now-lookback, now+lookahead].

    Inclusive of the current window. Capped at :data:`_MAX_ENUMERATED_WINDOWS`.
    """
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    first = align_window_start_s(now_ms - max(0, lookback_s) * 1000, step_s)
    last = align_window_start_s(now_ms + max(0, lookahead_s) * 1000, step_s)
    out: list[int] = []
    ts = first
    while ts <= last and len(out) < _MAX_ENUMERATED_WINDOWS:
        out.append(ts)
        ts += step_s
    return out


def enumerate_slugs(
    asset: str,
    duration: str,
    now_ms: int,
    *,
    lookback_s: int,
    lookahead_s: int,
) -> list[str]:
    """Slugs for every window on the grid within [now-lookback, now+lookahead]."""
    step = duration_to_seconds(duration)
    return [
        make_slug(asset, duration, ts)
        for ts in enumerate_window_starts(now_ms, step, lookback_s=lookback_s, lookahead_s=lookahead_s)
    ]


def classify_window(
    *,
    now_ms: int,
    window_start_ms: Optional[int],
    expiry_ms: Optional[int],
    closed: bool = False,
    resolved: bool = False,
    upcoming_horizon_ms: int = DEFAULT_UPCOMING_HORIZON_MS,
    post_window_horizon_ms: int = DEFAULT_POST_WINDOW_HORIZON_MS,
) -> WindowPhase:
    """Classify a window's timing phase. Pure; ``acceptingOrders`` is separate.

    Resolution state takes precedence: a closed/resolved market is always
    RESOLVED_OR_CLOSED regardless of its timestamps.
    """
    if closed or resolved:
        return WindowPhase.RESOLVED_OR_CLOSED
    if not window_start_ms or not expiry_ms:
        return WindowPhase.UNKNOWN_TIMING
    if now_ms < window_start_ms:
        if window_start_ms - now_ms <= upcoming_horizon_ms:
            return WindowPhase.UPCOMING_PRE_WINDOW
        return WindowPhase.FAR_FUTURE
    if window_start_ms <= now_ms <= expiry_ms:
        return WindowPhase.CURRENTLY_IN_WINDOW
    # now_ms > expiry_ms
    if now_ms - expiry_ms <= post_window_horizon_ms:
        return WindowPhase.POST_WINDOW_NOT_RESOLVED
    return WindowPhase.STALE_PAST


def classify_meta(meta, *, now_ms: int, **horizons) -> WindowPhase:
    """Classify a :class:`~btc5m.schemas.ContractMeta` by its timing/status."""
    status = (getattr(meta, "status", "") or "").lower()
    return classify_window(
        now_ms=now_ms,
        window_start_ms=getattr(meta, "window_start_ms", None),
        expiry_ms=getattr(meta, "expiry_ms", None),
        closed=status in ("closed", "resolved"),
        resolved=status == "resolved",
        **horizons,
    )


# Phases that represent a market still worth collecting book data for right now.
COLLECTIBLE_PHASES = frozenset(
    {
        WindowPhase.UPCOMING_PRE_WINDOW,
        WindowPhase.CURRENTLY_IN_WINDOW,
        WindowPhase.POST_WINDOW_NOT_RESOLVED,
    }
)


def parse_market_url(url: str) -> Optional[str]:
    """Extract a market/event slug from a Polymarket URL (or a bare slug).

    Handles forms like:
        https://polymarket.com/event/btc-updown-5m-1780288800
        https://polymarket.com/event/<event-slug>/<market-slug>
        https://polymarket.com/market/<slug>?foo=bar
        btc-updown-5m-1780288800   (already a slug)

    Prefers a path segment matching the Up/Down slug pattern; otherwise returns
    the last non-empty, non-routing path segment. Returns None if nothing usable.
    """
    if not url:
        return None
    s = url.strip()
    # Already a bare Up/Down slug?
    if parse_slug(s):
        return s.lower()
    # Strip scheme + host, query, and fragment.
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", s)
    s = s.split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in s.split("/") if p]
    # Drop the leading host (contains a dot) and known routing segments.
    routing = {"event", "events", "market", "markets", "sport", "crypto"}
    segments = []
    for i, p in enumerate(parts):
        if i == 0 and "." in p:  # host like polymarket.com
            continue
        if p.lower() in routing:
            continue
        segments.append(p)
    # Prefer a segment that looks like an Up/Down slug.
    for seg in segments:
        if parse_slug(seg):
            return seg.lower()
    return segments[-1].lower() if segments else None
