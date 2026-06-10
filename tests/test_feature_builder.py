"""Offline tests for the point-in-time feature window + builder."""

from btc5m.features.feature_builder import build_feature_row, polymarket_book_features
from btc5m.features.window import UnderlyingWindow


def _ev(ts, etype, **kw):
    base = {"source": "coinbase", "symbol": "BTC-USD", "event_type": etype,
            "exchange_ts_ms": ts, "recv_ms": ts, "price": None, "size": None,
            "side": None, "best_bid": None, "best_ask": None, "bid_size": None,
            "ask_size": None, "spread": None}
    base.update(kw)
    return base


def test_window_no_lookahead_returns():
    w = UnderlyingWindow("coinbase")
    for ts, px in [(1000, 100.0), (2000, 101.0), (3000, 102.0)]:
        w.add_event(_ev(ts, "trade", price=px, size=1.0, side="buy"))
    # As of 2000ms, only sees prices up to 2000 -> last price 101, not 102.
    assert w.last_price(2000) == 101.0
    rets = w.returns(2000, horizons_s=(1,))
    assert rets["ret_1s"] is not None  # 101 vs 100


def test_window_cvd_and_intensity():
    w = UnderlyingWindow("coinbase")
    w.add_event(_ev(1000, "trade", price=100.0, size=2.0, side="buy"))
    w.add_event(_ev(1500, "trade", price=100.0, size=1.0, side="sell"))
    flow = w.flow(2000, horizons_s=(5,))
    assert flow["cvd_cumulative"] == 1.0          # +2 - 1
    assert flow["trade_intensity_5s"] == 2.0


def test_window_book_state_microprice():
    w = UnderlyingWindow("binance_futures")
    w.add_event(_ev(1000, "book", best_bid=100.0, best_ask=100.1, bid_size=30.0, ask_size=10.0))
    bs = w.book_state(2000)
    assert bs["u_spread"] is not None
    # heavier bid -> microprice above mid -> positive divergence
    assert bs["u_microprice_minus_mid"] > 0
    assert bs["u_book_imbalance"] > 0


def test_polymarket_book_features():
    ev = {"best_bid": 0.55, "best_ask": 0.57, "spread": 0.02, "is_crossed": False,
          "ts_ms": 1000, "bids": [[0.55, 200], [0.54, 100]], "asks": [[0.57, 50]]}
    f = polymarket_book_features(ev, as_of_ms=1500, prefix="yes")
    assert f["yes_bid"] == 0.55 and f["yes_ask"] == 0.57
    assert f["yes_depth_bid"] == 300.0 and f["yes_depth_ask"] == 50.0
    assert f["yes_quote_age_ms"] == 500
    assert f["yes_book_imbalance"] > 0  # 200 vs 50


def test_build_feature_row_flags_and_distance():
    spot = UnderlyingWindow("coinbase")
    spot.add_event(_ev(1000, "trade", price=73800.0, size=1.0, side="buy"))
    yes_ev = {"best_bid": 0.55, "best_ask": 0.57, "spread": 0.02, "is_crossed": False,
              "ts_ms": 1000, "bids": [[0.55, 200]], "asks": [[0.57, 100]]}
    no_ev = {"best_bid": 0.43, "best_ask": 0.45, "spread": 0.02, "is_crossed": False,
             "ts_ms": 1000, "bids": [[0.43, 80]], "asks": [[0.45, 90]]}
    line_rec = {"line_price": 73750.0, "line_source_status": "PROVISIONAL_REFERENCE"}
    row = build_feature_row(
        as_of_ms=1200, slug="btc-updown-5m-1", condition_id="0xc",
        window_start_ms=1000, expiry_ms=301000, comparison="GTE",
        yes_event=yes_ev, no_event=no_ev, line_record=line_rec,
        spot_window=spot, perp_window=None,
    )
    assert row["reference_price"] == 73800.0
    assert row["distance_from_line"] == 50.0
    assert row["line_source_status"] == "PROVISIONAL_REFERENCE"
    assert row["mkt_implied_yes_from_ask"] == 0.57
    assert row["stale_yes_quote"] is False
    assert row["line_known"] is True
    assert row["feed_health_ok"] is True


def test_build_feature_row_stale_and_unknown_line():
    yes_ev = {"best_bid": 0.5, "best_ask": 0.52, "spread": 0.02, "is_crossed": False,
              "ts_ms": 1000, "bids": [[0.5, 10]], "asks": [[0.52, 10]]}
    row = build_feature_row(
        as_of_ms=999_999, slug="s", condition_id="c",
        window_start_ms=1000, expiry_ms=301000, comparison="GTE",
        yes_event=yes_ev, no_event=None, line_record=None,
        spot_window=None, perp_window=None, max_quote_age_ms=1500,
    )
    assert row["stale_yes_quote"] is True       # huge quote age
    assert row["missing_no_book"] is True
    assert row["line_known"] is False
    assert row["line_source_status"] == "UNKNOWN"
    assert row["feed_health_ok"] is False
