"""Offline tests for window-start line capture + persistence."""

from btc5m.config import load_config
from btc5m.data.line_capture import (
    capture_historical_line,
    capture_live_line,
    load_line_records,
    make_line_record,
    write_line_record,
)
from btc5m.data.recorder import Recorder
from btc5m.schemas import Comparison, ContractMeta, LineSourceStatus, MarketType


def _meta(window_start_ms=1_000_000, expiry_ms=1_300_000):
    return ContractMeta(
        contract_id="cond1",
        title="Bitcoin Up or Down",
        asset="BTC",
        line=None,
        expiry_ms=expiry_ms,
        resolution_source="https://data.chain.link/streams/btc-usd",
        market_id="mid1",
        condition_id="cond1",
        slug="btc-updown-5m-1000",
        market_type=MarketType.UP_DOWN,
        comparison=Comparison.GTE,
        window_start_ms=window_start_ms,
    )


class _FakeLiveClient:
    source = "coinbase"
    symbol = "BTC-USD"

    def __init__(self, price):
        self._price = price

    def reference_price_now(self):
        if self._price is None:
            return None, "coinbase:BTC-USD", {}
        return self._price, "coinbase:BTC-USD", {"price": self._price}


class _FakeCandleClient:
    source = "coinbase"
    symbol = "BTC-USD"

    def __init__(self, price):
        self._price = price

    def price_at(self, ts_ms):
        if self._price is None:
            return None, {"reason": "no_candle"}
        return self._price, {"candle_time": ts_ms // 1000, "field": "open"}


def test_make_line_record_fields():
    rec = make_line_record(
        _meta(), line_price=60000.0, line_source="coinbase:BTC-USD",
        status=LineSourceStatus.PROVISIONAL_REFERENCE, captured_at_ms=1_000_500,
    )
    assert rec.slug == "btc-updown-5m-1000"
    assert rec.line_price == 60000.0
    assert rec.line_source_status is LineSourceStatus.PROVISIONAL_REFERENCE
    assert rec.comparison is Comparison.GTE
    assert rec.condition_id == "cond1"


def test_capture_live_line_provisional():
    rec = capture_live_line(_meta(), _FakeLiveClient(73000.0), ref_ms=1_000_400)
    assert rec.line_price == 73000.0
    assert rec.line_source_status is LineSourceStatus.PROVISIONAL_REFERENCE
    assert "proxy" in rec.detail.lower()


def test_capture_live_line_unknown_when_no_price():
    rec = capture_live_line(_meta(), _FakeLiveClient(None), ref_ms=1_000_400)
    assert rec.line_price is None
    assert rec.line_source_status is LineSourceStatus.UNKNOWN


def test_capture_line_unknown_when_window_start_missing():
    meta = _meta(window_start_ms=None)
    rec = capture_live_line(meta, _FakeLiveClient(73000.0))
    assert rec.line_source_status is LineSourceStatus.UNKNOWN
    assert rec.line_price is None


def test_capture_historical_line():
    rec = capture_historical_line(_meta(), _FakeCandleClient(72950.5), ref_ms=2_000_000)
    assert rec.line_price == 72950.5
    assert rec.line_source_status is LineSourceStatus.PROVISIONAL_REFERENCE
    assert rec.line_source.startswith("coinbase:")


def test_capture_historical_line_unknown():
    rec = capture_historical_line(_meta(), _FakeCandleClient(None))
    assert rec.line_price is None
    assert rec.line_source_status is LineSourceStatus.UNKNOWN


def test_write_and_load_round_trip(tmp_path):
    cfg = load_config(mode="paper")
    cfg.data_dir = str(tmp_path)
    rec = make_line_record(
        _meta(), line_price=60000.0, line_source="coinbase:BTC-USD",
        status=LineSourceStatus.PROVISIONAL_REFERENCE, captured_at_ms=1_000_500,
    )
    with Recorder(cfg) as r:
        write_line_record(r, rec)
    loaded = load_line_records(tmp_path / "normalized")
    assert "btc-updown-5m-1000" in loaded
    ev = loaded["btc-updown-5m-1000"]
    assert ev["line_price"] == 60000.0
    assert ev["line_source_status"] == "PROVISIONAL_REFERENCE"
    assert ev["comparison"] == "GTE"
