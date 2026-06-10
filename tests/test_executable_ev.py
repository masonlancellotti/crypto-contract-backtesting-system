"""Tests for executable-EV and realized-PnL labels."""

from btc5m.labels.executable_ev import (
    binary_trade_pnl,
    executable_ev_labels,
    expected_value_after_costs,
)


def test_binary_trade_pnl_yes():
    assert abs(binary_trade_pnl("BUY_YES", 0.57, 1) - 0.43) < 1e-9    # win 1 - 0.57
    assert abs(binary_trade_pnl("BUY_YES", 0.57, 0) - (-0.57)) < 1e-9  # lose entry
    assert abs(binary_trade_pnl("BUY_NO", 0.40, 0) - 0.60) < 1e-9     # NO wins when YES=0
    assert abs(binary_trade_pnl("BUY_NO", 0.40, 1) - (-0.40)) < 1e-9


def test_executable_ev_labels_win_lose():
    lab = executable_ev_labels(1, yes_ask=0.57, no_ask=0.45, outcome_source_status="OFFICIAL")
    assert lab.would_buy_yes_at_ask_have_positive_result is True
    assert lab.would_buy_no_at_ask_have_positive_result is False
    assert lab.best_executable_side == "BUY_YES"
    assert abs(lab.realized_pnl_buy_yes_at_ask - 0.43) < 1e-9
    assert lab.reason_code == "OK"
    assert lab.label_source_status == "OFFICIAL"


def test_executable_ev_labels_missing_outcome():
    lab = executable_ev_labels(None, yes_ask=0.5, no_ask=0.5)
    assert lab.reason_code == "MISSING_OUTCOME"
    assert lab.executable_ev_label_after_costs is None


def test_executable_ev_labels_missing_price():
    lab = executable_ev_labels(1, yes_ask=None, no_ask=None)
    assert lab.reason_code == "MISSING_PRICE"


def test_executable_ev_labels_invalid_price():
    lab = executable_ev_labels(1, yes_ask=1.5, no_ask=0.5)
    assert lab.reason_code == "INVALID_PRICE"


def test_fees_reduce_pnl():
    lab = executable_ev_labels(1, yes_ask=0.57, no_ask=0.45, fee_per_contract=0.01,
                               outcome_source_status="OFFICIAL")
    assert abs(lab.realized_pnl_buy_yes_at_ask - 0.42) < 1e-9   # 0.43 - 0.01


def test_expected_value_after_costs():
    ev = expected_value_after_costs(0.63, yes_ask=0.57, no_ask=0.45)
    assert abs(ev.ev_buy_yes_at_ask - 0.06) < 1e-9              # 0.63 - 0.57
    assert ev.best_side == "BUY_YES"
    # NO side EV = (1-0.63) - 0.45 = -0.08
    assert abs(ev.ev_buy_no_at_ask - (-0.08)) < 1e-9


def test_expected_value_prefers_no_when_cheap():
    ev = expected_value_after_costs(0.30, yes_ask=0.55, no_ask=0.50)
    # EV yes = -0.25; EV no = 0.70 - 0.50 = 0.20 -> NO
    assert ev.best_side == "BUY_NO"
