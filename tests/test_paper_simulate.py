"""Tests for non-midpoint paper fill simulation + realized PnL."""

from btc5m.paper.simulate import (
    executable_levels,
    realized_binary_pnl,
    simulate_paper_fill,
)
from btc5m.schemas import Outcome

YES_EV = {"asks": [[0.57, 100], [0.58, 200]], "bids": [[0.55, 100]]}
NO_EV = {"asks": [[0.45, 80], [0.46, 200]], "bids": [[0.43, 50]]}


def test_executable_levels_picks_ask_side():
    out, levels = executable_levels("BUY_YES", YES_EV, NO_EV)
    assert out is Outcome.YES
    assert levels[0].price == 0.57           # YES ask, never midpoint
    out2, levels2 = executable_levels("BUY_NO", YES_EV, NO_EV)
    assert out2 is Outcome.NO and levels2[0].price == 0.45


def test_fill_walks_ask_ladder_not_midpoint():
    fill = simulate_paper_fill("BUY_YES", YES_EV, NO_EV, requested_size=100)
    assert fill.filled_size == 100
    assert fill.avg_price == 0.57            # top ask, above any midpoint (0.56)
    assert fill.is_paper


def test_partial_fill_when_thin():
    fill = simulate_paper_fill("BUY_YES", YES_EV, NO_EV, requested_size=1000)
    assert fill.filled_size == 300           # 100 + 200 visible
    assert fill.status in ("partial", "simulated")


def test_no_liquidity_rejected():
    fill = simulate_paper_fill("BUY_YES", {"asks": []}, NO_EV, requested_size=10)
    assert fill.filled_size == 0
    assert fill.status == "rejected"


def test_realized_pnl_yes_win_and_loss():
    fill = simulate_paper_fill("BUY_YES", YES_EV, NO_EV, requested_size=100)
    win = realized_binary_pnl("BUY_YES", fill, 1)
    lose = realized_binary_pnl("BUY_YES", fill, 0)
    assert abs(win - (1 - 0.57) * 100) < 1e-6
    assert abs(lose - (-0.57) * 100) < 1e-6


def test_realized_pnl_none_when_unknown_or_unfilled():
    fill = simulate_paper_fill("BUY_YES", YES_EV, NO_EV, requested_size=100)
    assert realized_binary_pnl("BUY_YES", fill, None) is None
    empty = simulate_paper_fill("BUY_YES", {"asks": []}, NO_EV, requested_size=10)
    assert realized_binary_pnl("BUY_YES", empty, 1) is None
