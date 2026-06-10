"""Path-based auxiliary labels over a BTC price path within a 5m window.

These describe how the underlying moved relative to the line during the window:
first cross above/below, time to return to the line, and the max favorable /
adverse excursions (signed distance from the line). They are diagnostic /
secondary targets. Their settlement-grade status follows the price source: if
the path is built from Coinbase/Binance they are PROVISIONAL_REFERENCE, not the
official Chainlink path.

A ``path`` is a list of ``(ts_ms, price)`` tuples in non-decreasing ts order.
"""

from __future__ import annotations

from typing import Optional, Sequence

Path = Sequence[tuple[int, float]]


def _first_ts_where(path: Path, predicate) -> Optional[int]:
    for ts, px in path:
        if predicate(px):
            return ts
    return None


def first_cross_above_ms(path: Path, line: float, *, inclusive: bool = True) -> Optional[int]:
    """Timestamp of the first point at/above the line (inclusive=GTE)."""
    pred = (lambda px: px >= line) if inclusive else (lambda px: px > line)
    return _first_ts_where(path, pred)


def first_cross_below_ms(path: Path, line: float, *, inclusive: bool = False) -> Optional[int]:
    """Timestamp of the first point below (or at-or-below) the line."""
    pred = (lambda px: px <= line) if inclusive else (lambda px: px < line)
    return _first_ts_where(path, pred)


def time_to_cross_above(path: Path, line: float, *, start_ms: int, inclusive: bool = True):
    ts = first_cross_above_ms(path, line, inclusive=inclusive)
    return None if ts is None else ts - start_ms


def time_to_cross_below(path: Path, line: float, *, start_ms: int, inclusive: bool = False):
    ts = first_cross_below_ms(path, line, inclusive=inclusive)
    return None if ts is None else ts - start_ms


def time_to_return_to_line(path: Path, line: float, *, start_ms: int, tol: float = 0.0):
    """Time from start until price returns within ``tol`` of the line.

    Uses the first point after the path has moved off the line by > tol and then
    comes back within tol. Returns ms-from-start or None.
    """
    moved_off = False
    for ts, px in path:
        if abs(px - line) > tol:
            moved_off = True
        elif moved_off and abs(px - line) <= tol:
            return ts - start_ms
    return None


def max_favorable_move_before_expiry(path: Path, line: float) -> Optional[float]:
    """Largest amount the price was ABOVE the line (signed; >=0 if ever above)."""
    if not path:
        return None
    return max(px - line for _, px in path)


def max_adverse_move_before_expiry(path: Path, line: float) -> Optional[float]:
    """Most the price was BELOW the line (signed; <=0 if ever below)."""
    if not path:
        return None
    return min(px - line for _, px in path)


def path_label_stats(
    path: Path, line: Optional[float], *, window_start_ms: int, expiry_ms: int
) -> dict:
    """Bundle the path-based labels with explicit None on missing inputs."""
    if line is None or not path:
        return {
            "time_to_cross_above_line_ms": None,
            "time_to_cross_below_line_ms": None,
            "time_to_return_to_line_ms": None,
            "max_favorable_move_before_expiry": None,
            "max_adverse_move_before_expiry": None,
            "path_points": len(path) if path else 0,
        }
    return {
        "time_to_cross_above_line_ms": time_to_cross_above(path, line, start_ms=window_start_ms),
        "time_to_cross_below_line_ms": time_to_cross_below(path, line, start_ms=window_start_ms),
        "time_to_return_to_line_ms": time_to_return_to_line(path, line, start_ms=window_start_ms),
        "max_favorable_move_before_expiry": max_favorable_move_before_expiry(path, line),
        "max_adverse_move_before_expiry": max_adverse_move_before_expiry(path, line),
        "path_points": len(path),
    }
