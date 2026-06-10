"""Rich Kalshi underlying microstructure features (offline, deterministic).

Verifies returns / realized-vol / basis / microprice / queue-imbalance / OFI /
CVD are computed from recorded events, that un-derivable features are reported
missing with reason codes (never invented), and that build_feature_row carries
feature_set_version + the new contract fields + merges underlying_extra.
"""

from btc5m.venues.kalshi.features import FEATURE_SET_VERSION, UnderlyingMicrostructureState
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.paper import build_feature_row


def _spot(ts, price):
    return {"source": "coinbase", "symbol": "BTC-USD", "event_type": "ticker",
            "recv_ms": ts, "exchange_ts_ms": ts, "price": price,
            "best_bid": price - 0.5, "best_ask": price + 0.5}


def _spot_trade(ts, price, size, side):
    return {"source": "coinbase", "event_type": "trade", "recv_ms": ts,
            "price": price, "size": size, "side": side}


def _perp_book(ts, bid, ask, bs, as_):
    return {"source": "binance_futures", "event_type": "book", "recv_ms": ts,
            "best_bid": bid, "best_ask": ask, "bid_size": bs, "ask_size": as_}


def _perp_trade(ts, price, size, side):
    return {"source": "binance_futures", "event_type": "trade", "recv_ms": ts,
            "price": price, "size": size, "side": side}


def _state_with_history():
    st = UnderlyingMicrostructureState()
    base = 1_000_000
    # 61 spot samples over 60s with drift + alternating wiggle (gives nonzero vol)
    for i in range(0, 61):
        wig = 0.05 if i % 2 == 0 else -0.05
        st.ingest(_spot(base + i * 1000, 100.0 * (1.0 + 0.0003 * i) + wig))
    # two perp books (so OFI has a previous snapshot); perp mid above spot
    st.ingest(_perp_book(base + 58_000, 103.0, 103.2, 10.0, 4.0))
    st.ingest(_perp_book(base + 59_000, 103.1, 103.3, 20.0, 3.0))
    # trades for CVD / intensity
    st.ingest(_perp_trade(base + 55_000, 103.0, 2.0, "buy"))
    st.ingest(_perp_trade(base + 56_000, 103.0, 1.0, "sell"))
    return st, base


def test_returns_and_realized_vol_present():
    st, base = _state_with_history()
    f = st.features(as_of_ms=base + 60_000, window_start_ms=base)
    assert f["spot_return_30s"] is not None and f["spot_return_30s"] > 0
    assert f["spot_return_since_window_start"] is not None and f["spot_return_since_window_start"] > 0
    assert f["realized_vol_30s"] is not None
    assert f["realized_vol_window_to_date"] is not None


def test_basis_microprice_queue_imbalance_ofi():
    st, base = _state_with_history()
    f = st.features(as_of_ms=base + 60_000)
    assert f["spot_perp_basis"] is not None and f["spot_perp_basis"] > 0  # perp above spot
    # binance has sizes -> microprice + imbalance derivable; bid_size>ask_size -> imbalance>0
    assert f["binance_microprice"] is not None
    assert f["binance_queue_imbalance"] is not None and f["binance_queue_imbalance"] > 0
    assert f["binance_ofi_best"] is not None  # two snapshots present


def test_cvd_and_trade_intensity():
    st, base = _state_with_history()
    f = st.features(as_of_ms=base + 60_000)
    assert f["perp_cvd_60s"] is not None
    assert f["perp_signed_trade_imbalance_60s"] is not None
    assert f["perp_trade_intensity_60s"] is not None and f["perp_trade_intensity_60s"] > 0


def test_missing_features_reported_not_invented():
    st = UnderlyingMicrostructureState()
    # only one spot sample: returns/vol/basis cannot be computed
    st.ingest(_spot(2_000_000, 100.0))
    f = st.features(as_of_ms=2_000_001)
    assert f["spot_return_30s"] is None
    assert "spot_return_30s" in f["underlying_missing_features"]
    # coinbase ticker never has sizes -> spot microprice missing w/ reason
    assert f["coinbase_microprice"] is None
    assert "COINBASE_TICKER_HAS_NO_SIZES" in f["underlying_missing_reason_codes"]
    # no perp feed -> basis missing + reason
    assert f["spot_perp_basis"] is None
    assert "NO_PERP_FEED" in f["underlying_missing_reason_codes"]


def _norm_ob():
    return {
        "market_ticker": "KXBTC15M-26JUN010345-45", "series_ticker": "KXBTC15M",
        "event_ticker": "KXBTC15M-26JUN010345", "status": "active",
        "close_ms": 5_000_000 + 600_000,
        "yes_bid": 0.40, "yes_ask": 0.42, "no_bid": 0.58, "no_ask": 0.60,
        "spread_yes": 0.02, "spread_no": 0.02,
        "yes_bid_size": 500.0, "no_bid_size": 300.0, "yes_ask_size": 300.0, "no_ask_size": 500.0,
        "yes_depth_levels": 3, "no_depth_levels": 2, "mid_yes": 0.41,
        "executable_yes_buy_price": 0.42, "executable_no_buy_price": 0.60,
        "quote_age_ms": 120,
        "book_validity_flags": {"yes_side_present": True, "no_side_present": True,
                                "incomplete_book": False, "yes_crossed": False,
                                "no_crossed": False, "prices_in_range": True,
                                "thin_yes": False, "thin_no": False},
    }


def test_build_feature_row_is_rich_and_merges_underlying():
    st, base = _state_with_history()
    und = st.features(as_of_ms=base + 60_000, window_start_ms=base)
    row = build_feature_row(
        _norm_ob(), as_of_ms=5_000_000, reference_price=72000.0,
        sigma_per_sqrt_s=0.0005, start_reference=71900.0,
        fee_model=KalshiFeeModel(), underlying_extra=und)
    assert row["feature_set_version"] == FEATURE_SET_VERSION
    assert row["no_spread"] == 0.02
    assert row["depth_imbalance"] is not None       # yes_bid_size vs no_bid_size
    assert row["distance_to_line_vol_normalized"] is not None
    assert row["distance_to_start"] == 100.0
    # merged underlying microstructure is present on the contract row
    assert "spot_perp_basis" in row and "binance_microprice" in row
    assert row["has_spot_feed"] is True
    # diagnostic-only midpoint is labelled, never an executable price
    assert row["mid_yes_diagnostic"] == 0.41
    assert row["executable_yes_buy_price"] == 0.42
