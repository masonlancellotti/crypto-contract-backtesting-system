"""Active-window / status gating for the Kalshi paper-decision loop.

Regression coverage for the post-close / out-of-window evaluation bug: closed,
pre-open and out-of-window markets are SKIPPED *before* scoring (collection-only)
and must never be mislabeled as book problems or reach PAPER_CANDIDATE.

All offline (synthetic); no network, no credentials, no orders.
"""

import pytest

from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.paper import (
    EMPTY_OR_INCOMPLETE_BOOK,
    MANUAL_REVIEW,
    MARKET_CLOSED,
    MARKET_NOT_OPEN,
    OUTSIDE_DECISION_WINDOW,
    PAPER_CANDIDATE,
    REJECTED,
    SKIPPED,
    decide_kalshi,
    decision_window_skip_reason,
)

FM = KalshiFeeModel()


def _row(**over):
    """A minimal, valid, in-window decision target (15-minute market)."""
    r = {
        "status": None,                 # recorded snapshots usually omit status
        "seconds_to_close": 300.0,
        "book_ok": True,
        "yes_ask": 0.30,
        "no_ask": 0.65,
        "yes_ask_size": 50,
        "no_ask_size": 50,
        "quote_age_ms": 100,
        "thin_book": False,
    }
    r.update(over)
    return r


# --------------------------------------------------------------------------- #
# Pure gate function
# --------------------------------------------------------------------------- #
def test_gate_active_window_ok():
    assert decision_window_skip_reason(_row(seconds_to_close=300.0)) is None
    assert decision_window_skip_reason(_row(seconds_to_close=900.0)) is None  # last in-window sec
    assert decision_window_skip_reason(_row(seconds_to_close=1.0)) is None


def test_gate_post_close():
    assert decision_window_skip_reason(_row(seconds_to_close=-10.0)) == MARKET_CLOSED
    assert decision_window_skip_reason(_row(seconds_to_close=0.0)) == MARKET_CLOSED


def test_gate_pre_open_out_of_window():
    assert decision_window_skip_reason(_row(seconds_to_close=901.0)) == OUTSIDE_DECISION_WINDOW
    assert decision_window_skip_reason(_row(seconds_to_close=1800.0)) == OUTSIDE_DECISION_WINDOW


def test_gate_accept_upcoming_allows_far_window_but_not_closed():
    assert decision_window_skip_reason(_row(seconds_to_close=1800.0), accept_upcoming=True) is None
    assert decision_window_skip_reason(_row(seconds_to_close=-5.0), accept_upcoming=True) == MARKET_CLOSED


def test_gate_status_closed_overrides_time():
    assert decision_window_skip_reason(_row(status="settled", seconds_to_close=300.0)) == MARKET_CLOSED
    assert decision_window_skip_reason(_row(status="closed", seconds_to_close=300.0)) == MARKET_CLOSED


def test_gate_status_not_open_or_not_accepting():
    assert decision_window_skip_reason(_row(status="unopened", seconds_to_close=300.0)) == MARKET_NOT_OPEN
    assert decision_window_skip_reason(_row(accepting_orders=False, seconds_to_close=300.0)) == MARKET_NOT_OPEN


def test_gate_missing_seconds_is_not_open():
    assert decision_window_skip_reason(_row(seconds_to_close=None)) == MARKET_NOT_OPEN


def test_gate_custom_duration_five_minute_market():
    assert decision_window_skip_reason(_row(seconds_to_close=301.0), market_duration_seconds=300) == OUTSIDE_DECISION_WINDOW
    assert decision_window_skip_reason(_row(seconds_to_close=299.0), market_duration_seconds=300) is None


# --------------------------------------------------------------------------- #
# decide_kalshi integration — gate precedes scoring and the book check
# --------------------------------------------------------------------------- #
def test_post_close_empty_book_is_market_closed_not_book_error():
    """THE BUG: a post-close market has an empty book; it must be reported as
    MARKET_CLOSED (timing), not INVALID/EMPTY_OR_INCOMPLETE_BOOK."""
    dec = decide_kalshi(
        _row(seconds_to_close=-120.0, book_ok=False, yes_ask=None, no_ask=None),
        model_p_yes=0.7, calibrated=True, fee_model=FM)
    assert dec["decision_state"] == SKIPPED
    assert dec["reason_codes"] == [MARKET_CLOSED]


def test_pre_open_is_skipped():
    dec = decide_kalshi(_row(seconds_to_close=1500.0), model_p_yes=0.8, calibrated=True, fee_model=FM)
    assert dec["decision_state"] == SKIPPED
    assert dec["reason_codes"] == [OUTSIDE_DECISION_WINDOW]


def test_empty_book_in_window_is_book_rejection():
    dec = decide_kalshi(
        _row(seconds_to_close=300.0, book_ok=False, yes_ask=None, no_ask=None),
        model_p_yes=0.7, calibrated=True, fee_model=FM)
    assert dec["decision_state"] == REJECTED
    assert dec["reason_codes"] == [EMPTY_OR_INCOMPLETE_BOOK]


def test_active_uncalibrated_is_manual_review():
    dec = decide_kalshi(
        _row(seconds_to_close=300.0), model_p_yes=0.80, calibrated=False, fee_model=FM)
    assert dec["decision_state"] == MANUAL_REVIEW
    assert "UNCALIBRATED_MODEL" in dec["reason_codes"]


def test_active_calibrated_with_edge_is_candidate():
    dec = decide_kalshi(
        _row(seconds_to_close=300.0), model_p_yes=0.80, calibrated=True, fee_model=FM)
    assert dec["decision_state"] == PAPER_CANDIDATE
    assert dec["side"] == "BUY_YES"


# --------------------------------------------------------------------------- #
# Zero-trade safety across the whole window lifecycle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("secs", [-300.0, -1.0, 0.0, 901.0, 1800.0])
def test_never_trades_outside_window_even_when_calibrated(secs):
    dec = decide_kalshi(
        _row(seconds_to_close=secs), model_p_yes=0.95, calibrated=True,
        allow_uncalibrated_candidates=True, fee_model=FM)
    assert dec["decision_state"] == SKIPPED
    assert dec["fill_status"] == "not_traded"


def test_uncalibrated_never_candidate_in_window():
    dec = decide_kalshi(
        _row(seconds_to_close=300.0, yes_ask=0.05, no_ask=0.90),
        model_p_yes=0.99, calibrated=False, fee_model=FM)
    assert dec["decision_state"] != PAPER_CANDIDATE
    assert dec["fill_status"] == "not_traded"
