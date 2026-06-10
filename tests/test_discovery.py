"""Pure discovery logic: slug grid, window classification, URL parsing.

All offline. These lock in the VERIFIED Polymarket semantics: the slug timestamp
is the window START in epoch seconds, aligned to the duration step.
"""

import pytest

from btc5m.discovery import (
    WindowPhase,
    align_window_start_s,
    classify_window,
    duration_to_seconds,
    enumerate_slugs,
    enumerate_window_starts,
    make_slug,
    parse_market_url,
    parse_slug,
    slug_prefix,
    slug_window_start_ms,
)


def test_duration_to_seconds():
    assert duration_to_seconds("5m") == 300
    assert duration_to_seconds("15m") == 900
    assert duration_to_seconds("1h") == 3600
    assert duration_to_seconds("30s") == 30
    with pytest.raises(ValueError):
        duration_to_seconds("banana")


def test_slug_roundtrip():
    assert slug_prefix("BTC", "5m") == "btc-updown-5m-"
    assert make_slug("BTC", "5m", 1780288800) == "btc-updown-5m-1780288800"
    assert parse_slug("btc-updown-5m-1780288800") == ("btc", "5m", 1780288800)
    assert parse_slug("eth-updown-15m-123") == ("eth", "15m", 123)
    assert parse_slug("not-a-market") is None
    assert parse_slug("") is None


def test_slug_window_start_ms_matches_event_start():
    # Verified live: slug 1780288800 == eventStartTime 2026-06-01T04:40:00Z.
    assert slug_window_start_ms("btc-updown-5m-1780288800") == 1780288800000
    assert slug_window_start_ms("garbage") is None


def test_align_and_enumerate():
    # 04:40:07Z -> floor to the 04:40:00Z 5-min boundary.
    now_ms = 1780288807000
    assert align_window_start_s(now_ms, 300) == 1780288800
    starts = enumerate_window_starts(now_ms, 300, lookback_s=300, lookahead_s=600)
    # [now-5m, now+10m] on the 5-min grid -> 04:35, 04:40, 04:45, 04:50.
    assert starts == [1780288500, 1780288800, 1780289100, 1780289400]
    slugs = enumerate_slugs("BTC", "5m", now_ms, lookback_s=0, lookahead_s=300)
    assert slugs == ["btc-updown-5m-1780288800", "btc-updown-5m-1780289100"]


def test_enumerate_is_bounded():
    # An absurd lookahead must not produce an unbounded list.
    starts = enumerate_window_starts(0, 300, lookback_s=0, lookahead_s=10**12)
    assert len(starts) <= 4000


# ---- classification ------------------------------------------------------- #
WS = 100_000      # window start ms
EXP = 400_000     # expiry ms (5 min later in this toy scale)


def test_classify_currently_in_window():
    assert classify_window(now_ms=250_000, window_start_ms=WS, expiry_ms=EXP) is WindowPhase.CURRENTLY_IN_WINDOW
    # boundaries are inclusive
    assert classify_window(now_ms=WS, window_start_ms=WS, expiry_ms=EXP) is WindowPhase.CURRENTLY_IN_WINDOW
    assert classify_window(now_ms=EXP, window_start_ms=WS, expiry_ms=EXP) is WindowPhase.CURRENTLY_IN_WINDOW


def test_classify_upcoming_vs_far_future():
    # opens in 10 min -> upcoming (default horizon 60 min)
    assert classify_window(now_ms=0, window_start_ms=600_000, expiry_ms=900_000) is WindowPhase.UPCOMING_PRE_WINDOW
    # opens in 2 h -> far future
    assert classify_window(now_ms=0, window_start_ms=7_200_000, expiry_ms=7_500_000) is WindowPhase.FAR_FUTURE


def test_classify_post_window_vs_stale():
    # expired 10 min ago, not closed -> post-window (unresolved)
    assert classify_window(now_ms=EXP + 600_000, window_start_ms=WS, expiry_ms=EXP) is WindowPhase.POST_WINDOW_NOT_RESOLVED
    # expired 2 h ago, never closed -> stale
    assert classify_window(now_ms=EXP + 7_200_000, window_start_ms=WS, expiry_ms=EXP) is WindowPhase.STALE_PAST


def test_classify_resolved_takes_precedence():
    # closed/resolved wins regardless of timestamps (even mid-window)
    assert classify_window(now_ms=250_000, window_start_ms=WS, expiry_ms=EXP, closed=True) is WindowPhase.RESOLVED_OR_CLOSED
    assert classify_window(now_ms=250_000, window_start_ms=WS, expiry_ms=EXP, resolved=True) is WindowPhase.RESOLVED_OR_CLOSED


def test_classify_unknown_timing():
    assert classify_window(now_ms=1, window_start_ms=None, expiry_ms=EXP) is WindowPhase.UNKNOWN_TIMING
    assert classify_window(now_ms=1, window_start_ms=WS, expiry_ms=0) is WindowPhase.UNKNOWN_TIMING


def test_accepting_orders_not_conflated_with_in_window():
    # A pre-window market can accept orders; classification is purely timing.
    phase = classify_window(now_ms=0, window_start_ms=600_000, expiry_ms=900_000)
    assert phase is WindowPhase.UPCOMING_PRE_WINDOW
    assert phase is not WindowPhase.CURRENTLY_IN_WINDOW


# ---- URL parsing ---------------------------------------------------------- #
def test_parse_market_url():
    assert parse_market_url("https://polymarket.com/event/btc-updown-5m-1780288800") == "btc-updown-5m-1780288800"
    assert parse_market_url(
        "https://polymarket.com/event/some-wrapper/btc-updown-5m-1780288800?tid=9"
    ) == "btc-updown-5m-1780288800"
    assert parse_market_url("btc-updown-5m-1780288800") == "btc-updown-5m-1780288800"
    assert parse_market_url("https://polymarket.com/market/btc-updown-5m-1780288800#book") == "btc-updown-5m-1780288800"
    # No Up/Down slug present -> last meaningful path segment (caller reports blocker).
    assert parse_market_url("https://polymarket.com/event/weird-landing-page") == "weird-landing-page"
    assert parse_market_url("") is None
