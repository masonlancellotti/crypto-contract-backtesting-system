"""Validation utilities (scaffold).

Walk-forward / purged k-fold validation for overlapping-label time series. Must
be used for any reported model metric; naive CV leaks across 5-minute windows.
"""

from __future__ import annotations

from typing import Any


def walk_forward_splits(*args: Any, **kwargs: Any) -> Any:
    """Yield leakage-safe walk-forward train/test splits. Scaffold."""
    raise NotImplementedError("walk_forward_splits is a scaffold.")
