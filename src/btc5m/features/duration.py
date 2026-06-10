"""Duration / time-to-expiry features.

Short-dated binaries are dominated by remaining time. Implemented helpers map
seconds-to-expiry into normalized features; regime interactions are scaffolds.
"""

from __future__ import annotations

from ..timeutils import FIVE_MIN_SECONDS


def duration_features(seconds_to_expiry: float, *, window: int = FIVE_MIN_SECONDS) -> dict:
    """Normalized time features for a 5-minute window."""
    frac_remaining = max(0.0, min(1.0, seconds_to_expiry / window)) if window else 0.0
    return {
        "seconds_to_expiry": seconds_to_expiry,
        "frac_remaining": frac_remaining,
        "frac_elapsed": 1.0 - frac_remaining,
        "is_final_30s": seconds_to_expiry <= 30.0,
        "is_expired": seconds_to_expiry <= 0.0,
    }
