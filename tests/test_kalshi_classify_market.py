"""classify_market: trust Kalshi's EXPLICIT status, fall back to open/close timing.

Regression guard for the 'cur=0 despite an active 15-minute market' discovery bug: Kalshi
reports the open/tradeable market with status='active' (served under the status=open query),
often from the instant it activates — at or marginally before open_time. The old timing-only
rule demoted that tradeable market to UPCOMING at the boundary, so the collector counted cur=0.
We now classify it CURRENT. Conversely an 'initialized' market is UPCOMING even if its open_time
has passed (Kalshi has not activated it -> not tradeable). No trading gate is involved here.
"""
from datetime import datetime, timezone

from btc5m.venues.kalshi.client import MarketPhase, classify_market

WIN = 15 * 60 * 1000
NOW = 1_780_000_000_000


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _m(status, *, open_off, close_off, result="", now=NOW):
    """A market opening at now+open_off ms and closing at now+close_off ms."""
    return {"ticker": "KXBTC15M-26JUN041115-15", "status": status, "result": result,
            "open_time": _iso(now + open_off), "close_time": _iso(now + close_off)}


# ----- explicit tradeable status wins ------------------------------------------------ #
def test_active_market_in_window_is_current():
    assert classify_market(_m("active", open_off=-300_000, close_off=600_000),
                           now_ms=NOW) is MarketPhase.CURRENT_IN_WINDOW


def test_active_market_at_open_boundary_is_current_even_if_now_before_open():
    # THE FIX: Kalshi flipped status to 'active' just before open_time (or clock skew). The
    # market IS tradeable -> CURRENT (old timing-only rule wrongly returned UPCOMING -> cur=0).
    assert classify_market(_m("active", open_off=+500, close_off=WIN),
                           now_ms=NOW) is MarketPhase.CURRENT_IN_WINDOW


def test_open_status_synonym_is_current():
    assert classify_market(_m("open", open_off=-1_000, close_off=WIN),
                           now_ms=NOW) is MarketPhase.CURRENT_IN_WINDOW


def test_active_market_past_close_is_closed_pending_settle():
    assert classify_market(_m("active", open_off=-WIN, close_off=-1_000),
                           now_ms=NOW) is MarketPhase.CLOSED_PENDING_SETTLE


# ----- not-yet-activated stays upcoming ---------------------------------------------- #
def test_initialized_market_is_upcoming_even_if_open_time_passed():
    # Kalshi has NOT activated it (status='initialized') -> not tradeable -> UPCOMING,
    # even though open_time is technically in the past.
    assert classify_market(_m("initialized", open_off=-2_000, close_off=WIN),
                           now_ms=NOW) is MarketPhase.UPCOMING


def test_initialized_future_market_is_upcoming():
    assert classify_market(_m("initialized", open_off=+600_000, close_off=+1_500_000),
                           now_ms=NOW) is MarketPhase.UPCOMING


# ----- terminal states --------------------------------------------------------------- #
def test_finalized_market_is_settled():
    assert classify_market(_m("finalized", open_off=-2 * WIN, close_off=-WIN, result="yes"),
                           now_ms=NOW) is MarketPhase.SETTLED


def test_result_present_is_settled_regardless_of_status():
    assert classify_market(_m("active", open_off=-WIN, close_off=-1_000, result="no"),
                           now_ms=NOW) is MarketPhase.SETTLED


def test_closed_status_is_closed_pending_settle():
    assert classify_market(_m("closed", open_off=-WIN, close_off=-1_000),
                           now_ms=NOW) is MarketPhase.CLOSED_PENDING_SETTLE


# ----- timing fallback when status missing/unknown ----------------------------------- #
def test_unknown_status_falls_back_to_timing_current():
    assert classify_market(_m("", open_off=-300_000, close_off=600_000),
                           now_ms=NOW) is MarketPhase.CURRENT_IN_WINDOW


def test_unknown_status_falls_back_to_timing_upcoming():
    assert classify_market(_m("", open_off=+60_000, close_off=+960_000),
                           now_ms=NOW) is MarketPhase.UPCOMING


def test_missing_times_and_status_is_unknown():
    assert classify_market({"ticker": "X", "status": ""}, now_ms=NOW) is MarketPhase.UNKNOWN


# ----- the boundary handoff never yields cur=0 --------------------------------------- #
def test_window_handoff_keeps_a_current_market():
    # Back-to-back boundary: old market just past close, new market 'active' but opening a
    # moment "later" (pre-activated). Exactly the discovery handoff that produced cur=0.
    old = _m("active", open_off=-WIN, close_off=-200)        # closed 0.2s ago
    new = _m("active", open_off=+200, close_off=WIN + 200)   # active, opens 0.2s "later"
    phases = [classify_market(old, now_ms=NOW), classify_market(new, now_ms=NOW)]
    assert MarketPhase.CURRENT_IN_WINDOW in phases           # cur >= 1, never 0
    assert classify_market(old, now_ms=NOW) is MarketPhase.CLOSED_PENDING_SETTLE


# ----- the kalshi-nearest-markets diagnostic command --------------------------------- #
def test_nearest_markets_command_reports_cur(monkeypatch, capsys):
    from btc5m.cli import main
    from btc5m.venues.kalshi.client import KalshiClient
    cur = {"ticker": "KXBTC15M-A", "status": "active", "_phase": "CURRENT_IN_WINDOW",
           "open_time": "2026-06-04T15:00:00Z", "close_time": "2026-06-04T15:15:00Z",
           "_open_ms": NOW - 60_000, "_close_ms": NOW + 540_000}
    up = {"ticker": "KXBTC15M-B", "status": "initialized", "_phase": "UPCOMING",
          "open_time": "2026-06-04T15:15:00Z", "close_time": "2026-06-04T15:30:00Z",
          "_open_ms": NOW + 540_000, "_close_ms": NOW + 1_440_000}
    monkeypatch.setattr(KalshiClient, "discover", lambda self, **kw: [cur, up])
    monkeypatch.setattr(KalshiClient, "server_date_header",
                        lambda self: "Thu, 04 Jun 2026 15:12:01 GMT")
    rc = main(["kalshi-nearest-markets", "--series", "KXBTC15M"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cur=1" in out and "CURRENT_IN_WINDOW" in out and "KXBTC15M-A" in out
    assert "current UTC" in out      # prints wall clock for the diagnosis
