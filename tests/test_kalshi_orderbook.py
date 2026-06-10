"""Kalshi orderbook normalization — the yes/no-bid -> executable-ask conversion.

All offline. Locks in the VERIFIED semantics: best bid = max price; executable
asks come from the opposite side's best bid; Decimal parsing; depth walking; no
midpoint fills; explicit invalid/thin/missing flags.
"""

from decimal import Decimal

from btc5m.venues.kalshi.orderbook import (
    asks_from_opposite_bids,
    depth_walk,
    executable_buy,
    normalize_orderbook,
    parse_levels,
)


def _raw(yes, no):
    return {"orderbook_fp": {"yes_dollars": yes, "no_dollars": no}}


def test_parse_levels_decimal_and_filtering():
    lv = parse_levels([["0.40", "100"], ["0.39", "200.5"], ["1.5", "9"], ["-0.1", "9"], ["x", "y"]])
    assert len(lv) == 2  # out-of-range and malformed dropped
    assert lv[0].price == Decimal("0.40") and lv[0].size == Decimal("100")
    assert isinstance(lv[0].price, Decimal)


def test_executable_ask_from_opposite_best_bid():
    raw = _raw([["0.40", "100"], ["0.39", "200"]], [["0.55", "300"], ["0.58", "150"]])
    n = normalize_orderbook(raw, market_ticker="KXBTC15M-X", recv_ms=1000)
    # best yes bid = 0.40, best no bid = 0.58
    assert n["yes_bid"] == 0.40 and n["no_bid"] == 0.58
    # yes_ask = 1 - best_no_bid ; no_ask = 1 - best_yes_bid
    assert abs(n["yes_ask"] - 0.42) < 1e-9
    assert abs(n["no_ask"] - 0.60) < 1e-9
    # ask sizes come from the OPPOSITE bid level that gets lifted
    assert n["yes_ask_size"] == 150.0   # the no-bid@0.58 size
    assert n["no_ask_size"] == 100.0    # the yes-bid@0.40 size
    assert n["executable_yes_buy_price"] == n["yes_ask"]


def test_no_midpoint_fills():
    raw = _raw([["0.40", "100"]], [["0.58", "150"]])
    n = normalize_orderbook(raw, market_ticker="KXBTC15M-X", recv_ms=1)
    mid = n["mid_yes"]
    assert abs(mid - 0.41) < 1e-9          # (0.40 + 0.42) / 2, exact via Decimal
    # executable buy is the ASK, never the midpoint
    assert n["executable_yes_buy_price"] == n["yes_ask"] != mid


def test_depth_walk_buy_yes():
    # NO bids -> synthetic YES asks: (1-0.55=0.45,300),(1-0.58=0.42,150)
    raw = _raw([["0.40", "100"]], [["0.55", "300"], ["0.58", "150"]])
    walk = executable_buy(raw, "yes", qty=200)
    # fill 150 @ 0.42 then 50 @ 0.45 -> avg 0.4275 over 200, 2 levels, full
    assert walk["filled_size"] == 200.0
    assert walk["levels_consumed"] == 2
    assert walk["fully_filled"] is True
    assert abs(walk["avg_price"] - 0.4275) < 1e-9


def test_depth_walk_partial_when_book_thin():
    raw = _raw([["0.40", "100"]], [["0.58", "150"]])
    walk = executable_buy(raw, "yes", qty=500)  # only 150 available
    assert walk["filled_size"] == 150.0
    assert walk["fully_filled"] is False


def test_asks_sorted_cheapest_first():
    asks = asks_from_opposite_bids(parse_levels([["0.55", "300"], ["0.58", "150"]]))
    prices = [float(a.price) for a in asks]
    assert prices == sorted(prices)  # ascending (best/cheapest ask first)


def test_missing_side_flags_incomplete():
    raw = _raw([["0.40", "100"]], [])  # no NO bids -> cannot buy YES
    n = normalize_orderbook(raw, market_ticker="KXBTC15M-X", recv_ms=1)
    assert n["yes_ask"] is None
    assert n["no_bid"] is None
    assert n["book_validity_flags"]["incomplete_book"] is True
    assert n["book_validity_flags"]["no_side_present"] is False


def test_thin_flag_and_depth_counts():
    raw = _raw([["0.40", "5"]], [["0.58", "5"]])  # tiny sizes
    n = normalize_orderbook(raw, market_ticker="KXBTC15M-X", recv_ms=1, thin_size=50.0)
    assert n["book_validity_flags"]["thin_yes"] is True
    assert n["yes_depth_levels"] == 1 and n["no_depth_levels"] == 1


def test_quote_age_from_source_ts():
    raw = _raw([["0.40", "100"]], [["0.58", "150"]])
    n = normalize_orderbook(raw, market_ticker="KXBTC15M-X", recv_ms=5000, source_ts_ms=4200)
    assert n["quote_age_ms"] == 800


def test_depth_walk_empty_or_zero_qty():
    assert depth_walk([], Decimal("10"))["avg_price"] is None
    raw = _raw([["0.40", "100"]], [["0.58", "150"]])
    assert executable_buy(raw, "yes", qty=0)["filled_size"] == 0.0
