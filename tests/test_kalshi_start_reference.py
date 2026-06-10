import math

from btc5m.timeutils import now_ms
from btc5m.venues.kalshi.features import UnderlyingMicrostructureState
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.orderbook import normalize_orderbook
from btc5m.venues.kalshi.paper import build_feature_row
from btc5m.venues.kalshi.paper_runtime import _decision_eligibility
from btc5m.venues.kalshi.start_reference import PENDING, StartReferenceResolver


class _PC:
    max_seconds_to_close = 900
    min_seconds_to_close = 5
    min_top_depth_contracts = 1.0


def _market(tk="KXBTC15M-X", *, window_start_ms=1_000_000, subtitle="Target price: TBD"):
    return {
        "ticker": tk,
        "event_ticker": f"{tk}-E",
        "status": "active",
        "window_start_ms": window_start_ms,
        "yes_sub_title": subtitle,
    }


def _spot(ts, px):
    return {
        "source": "coinbase",
        "symbol": "BTC-USD",
        "event_type": "ticker",
        "recv_ms": ts,
        "exchange_ts_ms": ts,
        "price": px,
        "best_bid": px - 0.5,
        "best_ask": px + 0.5,
    }


def test_explicit_kalshi_target_price_wins():
    micro = UnderlyingMicrostructureState()
    ref = StartReferenceResolver().resolve(
        _market(subtitle="Target Price: $63,812.34"),
        as_of_ms=1_001_000,
        micro_state=micro,
    )
    assert ref.price == 63812.34
    assert ref.source == "kalshi:yes_sub_title"
    assert ref.method == "kalshi_metadata_target_price"
    assert ref.source_status == "EXPLICIT"


def test_start_reference_uses_no_future_data():
    micro = UnderlyingMicrostructureState()
    micro.ingest(_spot(1_001_000, 63_800.0))
    resolver = StartReferenceResolver()

    pending = resolver.resolve(_market(), as_of_ms=1_000_000, micro_state=micro)
    assert pending.price is None
    assert pending.missing_reason == PENDING

    captured = resolver.resolve(_market(), as_of_ms=1_001_000, micro_state=micro)
    assert captured.price == 63_800.0
    assert captured.ts_ms == 1_001_000
    assert captured.method == "underlying_nearest_window_start_proxy"
    assert captured.source_status == "PROVISIONAL_REFERENCE"


def test_start_reference_prefers_preopen_average_and_persists_for_ticker():
    micro = UnderlyingMicrostructureState()
    for i, px in enumerate((100.0, 101.0, 102.0, 103.0)):
        micro.ingest(_spot(940_000 + i * 10_000, px))
    resolver = StartReferenceResolver()
    first = resolver.resolve(_market(), as_of_ms=1_001_000, micro_state=micro)
    assert first.price == 101.5
    assert first.ts_ms == 1_000_000
    assert first.method == "underlying_preopen_60s_average_proxy"

    micro.ingest(_spot(1_000_500, 999.0))
    second = resolver.resolve(_market(), as_of_ms=1_002_000, micro_state=micro)
    assert second.price == first.price
    assert second.ts_ms == first.ts_ms
    assert second.method == first.method


def test_build_feature_row_carries_reference_provenance_and_distances():
    raw = {"orderbook_fp": {"yes_dollars": [["0.40", "10"]], "no_dollars": [["0.58", "10"]]}}
    norm = normalize_orderbook(raw, market_ticker="KX", recv_ms=1_000, close_ms=10_000)
    prov = {
        "reference_start_price_source": "coinbase:BTC-USD",
        "reference_start_price_ts_ms": 1_000,
        "reference_start_price_age_ms": 500,
        "reference_start_price_method": "underlying_nearest_window_start_proxy",
        "reference_start_price_confidence": 0.6,
        "reference_start_price_source_status": "PROVISIONAL_REFERENCE",
    }
    row = build_feature_row(
        norm,
        as_of_ms=1_500,
        reference_price=101.0,
        sigma_per_sqrt_s=0.001,
        start_reference=100.0,
        fee_model=KalshiFeeModel(),
        start_reference_provenance=prov,
    )
    assert row["has_start_reference"] is True
    assert row["distance_to_start"] == 1.0
    assert row["distance_to_line_vol_normalized"] is not None
    assert math.isfinite(row["distance_to_line_vol_normalized"])
    assert row["reference_start_price_source"] == "coinbase:BTC-USD"
    assert row["reference_missing_reason"] is None


def test_active_missing_start_reference_is_rejected():
    now = now_ms()
    row = {
        "status": "active",
        "market_close_ts_ms": now + 600_000,
        "as_of_ts_ms": now - 100,
        "book_ok": True,
        "yes_ask": 0.42,
        "no_ask": 0.60,
        "yes_ask_size": 10.0,
        "no_ask_size": 10.0,
        "reference_start_price": None,
        "reference_missing_reason": PENDING,
    }
    ok, reasons, flags = _decision_eligibility(
        row, pc=_PC(), market_duration_seconds=900, feature_row_max_age_ms=10_000, now=now)
    assert ok is False
    assert "MISSING_START_REFERENCE" in reasons
    assert flags["reference_missing_reason"] == PENDING


def test_active_with_start_reference_and_depth_is_eligible():
    now = now_ms()
    row = {
        "status": "active",
        "market_close_ts_ms": now + 600_000,
        "as_of_ts_ms": now - 100,
        "book_ok": True,
        "yes_ask": 0.42,
        "no_ask": 0.60,
        "yes_ask_size": 10.0,
        "no_ask_size": 10.0,
        "reference_start_price": 70_000.0,
    }
    ok, reasons, flags = _decision_eligibility(
        row, pc=_PC(), market_duration_seconds=900, feature_row_max_age_ms=10_000, now=now)
    assert ok is True
    assert reasons == []
    assert flags["start_reference"] is True
    assert flags["executable_depth"] is True


def test_thin_book_keeps_insufficient_depth_rejection():
    now = now_ms()
    row = {
        "status": "active",
        "market_close_ts_ms": now + 600_000,
        "as_of_ts_ms": now - 100,
        "book_ok": True,
        "yes_ask": 0.42,
        "no_ask": 0.60,
        "yes_ask_size": 0.0,
        "no_ask_size": 0.0,
        "reference_start_price": 70_000.0,
    }
    ok, reasons, flags = _decision_eligibility(
        row, pc=_PC(), market_duration_seconds=900, feature_row_max_age_ms=10_000, now=now)
    assert ok is False
    assert "INSUFFICIENT_DEPTH" in reasons
    assert flags["depth_missing_reason"] == "INSUFFICIENT_DEPTH"
