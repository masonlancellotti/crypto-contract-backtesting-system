"""select_collection_targets: phase-prioritized collector target selection.

Regression guard for 'the active CURRENT_IN_WINDOW market is never recorded'. With a limited
--max-markets the active market must always be chosen FIRST and never displaced by an upcoming
or just-closed market (a just-closed market has a PAST close, i.e. a smaller close_ms, so a naive
'sort kept markets by close-time' would put it ahead of the active market). Upcoming markets fill
the remaining slots / are used only when no active market exists (recorded for backfill, never
scored). No trading gate is involved here.
"""
from btc5m.venues.kalshi.client import select_collection_targets

WIN = 15 * 60 * 1000
NOW = 1_780_000_000_000


def _mk(ticker, phase, *, close_ms, open_ms=None):
    return {"ticker": ticker, "_phase": phase, "_close_ms": close_ms,
            "_open_ms": open_ms if open_ms is not None else close_ms - WIN}


def _current():
    return _mk("CUR", "CURRENT_IN_WINDOW", close_ms=NOW + 300_000)


def _up(n, mins):
    return _mk(f"UP{n}", "UPCOMING", close_ms=NOW + mins * 60_000)


def _closed(n, mins_ago):
    return _mk(f"CL{n}", "CLOSED_PENDING_SETTLE", close_ms=NOW - mins_ago * 60_000)


def test_active_always_selected_with_max_markets_1():
    # discovered deliberately lists just-closed markets (past close -> smaller close_ms) BEFORE
    # the active market — the exact ordering that displaced the active market under one slot.
    discovered = [_closed(1, 5), _closed(2, 1), _current(), _up(1, 30), _up(2, 45)]
    sel = select_collection_targets(discovered, max_markets=1)
    assert [m["ticker"] for m in sel["targets"]] == ["CUR"]      # active first, not the closed one


def test_upcoming_selected_only_if_no_active_exists():
    discovered = [_closed(1, 3), _up(2, 45), _up(1, 30)]         # no CURRENT
    sel = select_collection_targets(discovered, max_markets=1)
    assert [m["ticker"] for m in sel["targets"]] == ["UP1"]      # nearest upcoming (soonest open)
    assert sel["current"] == []


def test_active_then_upcoming_ordering_is_stable():
    discovered = [_up(2, 45), _current(), _up(1, 30), _closed(1, 2)]
    sel = select_collection_targets(discovered, max_markets=3)
    assert [m["ticker"] for m in sel["targets"]] == ["CUR", "UP1", "UP2"]   # current, then upcoming by open


def test_closed_collected_only_after_current_and_upcoming():
    discovered = [_closed(1, 2), _current(), _up(1, 30)]
    sel = select_collection_targets(discovered, max_markets=0)   # 0 => all
    assert [m["ticker"] for m in sel["targets"]] == ["CUR", "UP1", "CL1"]


def test_two_current_markets_keep_soonest_close_first():
    a = _mk("CUR_A", "CURRENT_IN_WINDOW", close_ms=NOW + 60_000)
    b = _mk("CUR_B", "CURRENT_IN_WINDOW", close_ms=NOW + 30_000)
    sel = select_collection_targets([a, b], max_markets=1)
    assert sel["targets"][0]["ticker"] == "CUR_B"               # soonest-closing active first


def test_settled_only_falls_back_without_crashing():
    discovered = [_mk("S1", "SETTLED", close_ms=NOW - 99_000)]
    sel = select_collection_targets(discovered, max_markets=1)
    assert sel["current"] == [] and sel["upcoming"] == [] and sel["closed"] == []
    assert [m["ticker"] for m in sel["targets"]] == ["S1"]      # nothing phased -> fall back, no crash


def test_max_markets_none_returns_all_phase_ordered():
    discovered = [_up(1, 30), _closed(1, 2), _current()]
    sel = select_collection_targets(discovered, max_markets=None)
    assert [m["ticker"] for m in sel["targets"]] == ["CUR", "UP1", "CL1"]


# ----- cycle cadence: end the cycle when the active market closes (rediscover at boundary) ----- #
def test_cycle_deadline_caps_at_active_market_close():
    from btc5m.venues.kalshi.collector import _cycle_deadline
    # active market closes in 120s; a 900s cycle must end ~120s+grace, NOT 900s, so the next cycle
    # rediscovers at the window boundary instead of recording the just-closed market for ~13 more min.
    targets = [_mk("CUR", "CURRENT_IN_WINDOW", close_ms=NOW + 120_000)]
    d = _cycle_deadline(targets, seconds_per_cycle=900.0, mono_now=1000.0, now=NOW)
    assert d == 1000.0 + 120.0 + 3.0


def test_cycle_deadline_full_when_no_current_target():
    from btc5m.venues.kalshi.collector import _cycle_deadline
    targets = [_mk("UP1", "UPCOMING", close_ms=NOW + 1_000_000)]
    d = _cycle_deadline(targets, seconds_per_cycle=60.0, mono_now=1000.0, now=NOW)
    assert d == 1000.0 + 60.0          # cur=0 -> full seconds_per_cycle (record upcoming for backfill)


def test_cycle_deadline_never_exceeds_seconds_per_cycle():
    from btc5m.venues.kalshi.collector import _cycle_deadline
    targets = [_mk("CUR", "CURRENT_IN_WINDOW", close_ms=NOW + 1_000_000)]   # closes far away
    d = _cycle_deadline(targets, seconds_per_cycle=60.0, mono_now=1000.0, now=NOW)
    assert d == 1000.0 + 60.0          # seconds_per_cycle is the upper bound
