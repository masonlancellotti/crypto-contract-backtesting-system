"""Tests for path-based auxiliary labels."""

from btc5m.labels.time_to_cross import (
    max_adverse_move_before_expiry,
    max_favorable_move_before_expiry,
    path_label_stats,
    time_to_cross_above,
    time_to_cross_below,
)

# window start at 1000ms; points every 1000ms
PATH = [(1000, 100.0), (2000, 101.0), (3000, 99.0), (4000, 100.5), (5000, 98.0)]
LINE = 100.0
START = 1000


def test_cross_above():
    # first point >= 100 is at ts=1000 (inclusive GTE) -> 0ms
    assert time_to_cross_above(PATH, LINE, start_ms=START) == 0
    # strict above first at ts=2000 -> 1000ms
    assert time_to_cross_above(PATH, LINE, start_ms=START, inclusive=False) == 1000


def test_cross_below():
    # strict below first at ts=3000 (99.0) -> 2000ms
    assert time_to_cross_below(PATH, LINE, start_ms=START) == 2000


def test_mfe_mae():
    assert max_favorable_move_before_expiry(PATH, LINE) == 1.0    # 101 - 100
    assert max_adverse_move_before_expiry(PATH, LINE) == -2.0     # 98 - 100


def test_path_label_stats_missing_line():
    stats = path_label_stats(PATH, None, window_start_ms=START, expiry_ms=6000)
    assert stats["time_to_cross_above_line_ms"] is None
    assert stats["max_favorable_move_before_expiry"] is None
    assert stats["path_points"] == 5


def test_path_label_stats_full():
    stats = path_label_stats(PATH, LINE, window_start_ms=START, expiry_ms=6000)
    assert stats["max_favorable_move_before_expiry"] == 1.0
    assert stats["max_adverse_move_before_expiry"] == -2.0
    assert stats["time_to_cross_below_line_ms"] == 2000


def test_no_cross_returns_none():
    rising = [(1000, 101.0), (2000, 102.0)]
    assert time_to_cross_below(rising, 100.0, start_ms=1000) is None
