"""Time utilities — UTC-first, with explicit handling of expiry and clock skew.

The system reasons about exact expiry timestamps for 5-minute binaries; never
approximate these. All internal timestamps are UTC epoch milliseconds unless a
function name says otherwise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

FIVE_MIN_SECONDS = 300
FIVE_MIN_MS = FIVE_MIN_SECONDS * 1000


def now_utc() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_ms() -> int:
    """Current UTC time as epoch milliseconds."""
    return int(now_utc().timestamp() * 1000)


def to_ms(dt: datetime) -> int:
    """Convert a timezone-aware datetime to epoch milliseconds."""
    if dt.tzinfo is None:
        raise ValueError("Refusing to convert a naive datetime; attach tzinfo (UTC).")
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    """Convert epoch milliseconds to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def age_ms(event_ms: int, *, ref_ms: int | None = None) -> int:
    """Age in milliseconds of an event timestamp relative to `ref_ms` (or now)."""
    ref = now_ms() if ref_ms is None else ref_ms
    return ref - event_ms


def clock_skew_ms(remote_ms: int, *, local_ms: int | None = None) -> int:
    """Signed skew between a remote/server timestamp and local clock (ms).

    Positive => local clock is ahead of remote.
    """
    local = now_ms() if local_ms is None else local_ms
    return local - remote_ms


def floor_to_bucket(dt: datetime, *, seconds: int = FIVE_MIN_SECONDS) -> datetime:
    """Floor a datetime to the start of its N-second bucket (UTC)."""
    if dt.tzinfo is None:
        raise ValueError("Refusing to bucket a naive datetime; attach tzinfo (UTC).")
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def next_expiry(dt: datetime, *, seconds: int = FIVE_MIN_SECONDS) -> datetime:
    """Next N-second boundary strictly after `dt` (a candidate expiry)."""
    return floor_to_bucket(dt, seconds=seconds) + timedelta(seconds=seconds)


def seconds_to_expiry(expiry: datetime, *, ref: datetime | None = None) -> float:
    """Seconds remaining until `expiry`. Negative if already expired."""
    r = now_utc() if ref is None else ref
    return (expiry - r).total_seconds()


def local_tz(name: str):
    """Return a tzinfo for an IANA name, falling back to UTC if unavailable."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone.utc
