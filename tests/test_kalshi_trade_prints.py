"""Tests for public trade-print collection (read-only; no auth; no orders).

Covers the client pagination params, the collector-side poller (series filter,
trade_id dedupe, watermark advance, throttle, missing-method tolerance), and
row normalization.
"""

from btc5m.venues.kalshi.collector import _TradePoller, _fnum


class _Rec:
    def __init__(self):
        self.rows = []

    def record_normalized(self, stream, row):
        self.rows.append((stream, row))


class _Client:
    def __init__(self, trades):
        self.trades = trades
        self.calls = []

    def get_trades(self, **kw):
        self.calls.append(kw)
        return self.trades


def _trade(tid, ticker="KXBTC15M-26JUN101145-45", ts="2026-06-10T15:30:44.672447Z",
           yes="0.5500", taker="yes"):
    return {"trade_id": tid, "ticker": ticker, "created_time": ts,
            "yes_price_dollars": yes, "no_price_dollars": "0.4500",
            "count_fp": "100.00", "taker_side": taker, "is_block_trade": False}


def test_poller_records_normalized_rows_and_dedupes():
    rec = _Rec()
    cl = _Client([_trade("a"), _trade("a"), _trade("b")])
    p = _TradePoller(cl, "KXBTC15M", poll_interval_s=0.0)
    wrote, errs = p.poll(rec, mono_now=100.0, recv_ms=1)
    assert (wrote, errs) == (2, 0)
    stream, row = rec.rows[0]
    assert stream == "kalshi_trades"
    assert row["yes_price"] == 0.55 and row["no_price"] == 0.45 and row["count"] == 100.0
    assert row["taker_side"] == "yes" and row["market_ticker"].startswith("KXBTC15M")
    # second poll: same ids -> nothing new
    wrote2, _ = p.poll(rec, mono_now=200.0, recv_ms=2)
    assert wrote2 == 0


def test_poller_filters_other_series_and_advances_watermark():
    rec = _Rec()
    cl = _Client([_trade("x", ticker="KXETH15M-26JUN101145-45"), _trade("y")])
    p = _TradePoller(cl, "KXBTC15M", poll_interval_s=0.0)
    wrote, _ = p.poll(rec, mono_now=1.0, recv_ms=1)
    assert wrote == 1
    assert p._watermark_s is not None and p._watermark_s > 0
    # next call passes min_ts (watermark) to the client
    p.poll(rec, mono_now=2.0, recv_ms=2)
    assert cl.calls[-1]["min_ts"] == p._watermark_s


def test_poller_throttles_and_tolerates_missing_method_and_errors():
    rec = _Rec()
    p = _TradePoller(_Client([_trade("a")]), "KXBTC15M", poll_interval_s=60.0)
    p._last_poll_mono = 100.0
    assert p.poll(rec, mono_now=130.0, recv_ms=1) == (0, 0)  # throttled

    class _NoMethod:
        pass
    p2 = _TradePoller(_NoMethod(), "KXBTC15M", poll_interval_s=0.0)
    assert p2.poll(rec, mono_now=1.0, recv_ms=1) == (0, 0)

    class _Boom:
        def get_trades(self, **kw):
            raise RuntimeError("network down")
    p3 = _TradePoller(_Boom(), "KXBTC15M", poll_interval_s=0.0)
    assert p3.poll(rec, mono_now=1.0, recv_ms=1) == (0, 1)


def test_fnum_handles_strings_none_and_garbage():
    assert _fnum("0.55") == 0.55
    assert _fnum(None) is None
    assert _fnum("n/a") is None


def test_client_get_trades_paginates(monkeypatch):
    from btc5m.config import load_config
    from btc5m.venues.kalshi.client import KalshiClient
    cfg = load_config(mode="paper")
    cl = KalshiClient(cfg)
    pages = [
        {"trades": [_trade("1")], "cursor": "c2"},
        {"trades": [_trade("2")], "cursor": None},
    ]
    calls = []

    def fake_get(path, params=None, **kw):
        calls.append((path, dict(params or {})))
        return pages[len(calls) - 1]

    monkeypatch.setattr(cl, "_get", fake_get)
    out = cl.get_trades(min_ts=123, limit=200)
    assert [t["trade_id"] for t in out] == ["1", "2"]
    assert calls[0][0] == "/markets/trades"
    assert calls[0][1]["min_ts"] == 123
    assert calls[1][1]["cursor"] == "c2"
