"""Offline tests for Coinbase/Binance normalization (fixture payloads)."""

import pytest

from btc5m.data.underlying import (
    BinanceFuturesClient,
    CoinbaseSpotClient,
    build_underlying_client,
)

# Captured shapes (trimmed) of real public payloads.
_CB_TICKER = {
    "ask": "73768.03", "bid": "73768.02", "price": "73768.03", "size": "0.00002589",
    "trade_id": 1026970168, "time": "2026-05-31T07:42:38.279764185Z",
}
_CB_TRADE = {
    "trade_id": 1026970168, "side": "buy", "size": "0.01375932",
    "price": "73768.02000000", "time": "2026-05-31T07:42:39.376814Z",
}
_BN_BOOK = {
    "symbol": "BTCUSDT", "bidPrice": "73853.00", "bidQty": "3.238",
    "askPrice": "73853.10", "askQty": "13.584", "time": 1780213360229,
    "lastUpdateId": 10670068747319,
}
_BN_TRADE = {
    "id": 7705193402, "price": "73853.10", "qty": "0.062", "quoteQty": "4578.89",
    "time": 1780213360481, "isBuyerMaker": False,
}


def test_coinbase_ticker_normalization():
    ev = CoinbaseSpotClient().normalize_ticker(_CB_TICKER)
    assert ev.source == "coinbase" and ev.symbol == "BTC-USD"
    assert ev.event_type == "ticker"
    assert ev.best_bid == 73768.02 and ev.best_ask == 73768.03
    assert ev.price == 73768.03
    assert ev.spread == pytest.approx(0.01)
    assert ev.exchange_ts_ms is not None and ev.exchange_ts_ms > 0
    assert ev.mid == pytest.approx((73768.02 + 73768.03) / 2)


def test_coinbase_trade_side_is_aggressor():
    # Coinbase reports MAKER side 'buy' -> aggressor is 'sell'.
    ev = CoinbaseSpotClient().normalize_trade(_CB_TRADE)
    assert ev.event_type == "trade"
    assert ev.side == "sell"
    assert ev.price == 73768.02


def test_binance_book_normalization():
    ev = BinanceFuturesClient().normalize_book_ticker(_BN_BOOK)
    assert ev.source == "binance_futures" and ev.symbol == "BTCUSDT"
    assert ev.event_type == "book"
    assert ev.best_bid == 73853.0 and ev.best_ask == 73853.1
    assert ev.bid_size == 3.238 and ev.ask_size == 13.584
    assert ev.spread == pytest.approx(0.1)
    assert ev.exchange_ts_ms == 1780213360229


def test_binance_trade_side_inference():
    # isBuyerMaker False -> buyer is taker -> aggressor 'buy'.
    ev = BinanceFuturesClient().normalize_trade(_BN_TRADE)
    assert ev.side == "buy"
    ev2 = BinanceFuturesClient().normalize_trade({**_BN_TRADE, "isBuyerMaker": True})
    assert ev2.side == "sell"


def test_price_at_uses_candle_open(monkeypatch):
    client = CoinbaseSpotClient()
    # [time, low, high, open, close, volume]; target minute = 1780212000
    rows = [
        [1780212060, 1, 2, 73836.29, 73835.06, 0.1],
        [1780212000, 1, 2, 73841.11, 73836.29, 0.5],
        [1780211940, 1, 2, 73843.67, 73841.11, 0.2],
    ]
    monkeypatch.setattr(client, "fetch_candles_raw", lambda *a, **k: rows)
    price, detail = client.price_at(1780212000 * 1000)
    assert price == 73841.11
    assert detail["field"] == "open"


def test_price_at_fallback_to_earlier_close(monkeypatch):
    client = CoinbaseSpotClient()
    rows = [[1780211940, 1, 2, 73843.67, 73841.11, 0.2]]  # only an earlier candle
    monkeypatch.setattr(client, "fetch_candles_raw", lambda *a, **k: rows)
    price, detail = client.price_at(1780212000 * 1000)
    assert price == 73841.11  # close of earlier candle
    assert detail["field"] == "close_fallback"


def test_build_underlying_client():
    assert isinstance(build_underlying_client("coinbase"), CoinbaseSpotClient)
    assert isinstance(build_underlying_client("binance"), BinanceFuturesClient)
    with pytest.raises(ValueError):
        build_underlying_client("kraken")
