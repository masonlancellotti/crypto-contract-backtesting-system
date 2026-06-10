"""Tests for live/imminent window selection (focuses recording on usable data)."""

from btc5m.data.polymarket_client import PolymarketClient, select_live_or_imminent
from btc5m.schemas import Comparison, ContractMeta, MarketType


def _meta(slug, window_start_ms, expiry_ms):
    return ContractMeta(
        contract_id=slug, title="t", asset="BTC", line=None, expiry_ms=expiry_ms,
        slug=slug, market_type=MarketType.UP_DOWN, comparison=Comparison.GTE,
        window_start_ms=window_start_ms,
    )


def test_is_window_live():
    now = 1_000_000
    live = _meta("live", now - 1000, now + 60_000)
    upcoming = _meta("up", now + 3_600_000, now + 3_900_000)
    expired = _meta("ex", now - 600_000, now - 300_000)
    assert PolymarketClient.is_window_live(live, ref_ms=now)
    assert not PolymarketClient.is_window_live(upcoming, ref_ms=now)
    assert not PolymarketClient.is_window_live(expired, ref_ms=now)


def test_select_live_or_imminent():
    now = 1_000_000
    metas = [
        _meta("live", now - 1000, now + 200_000),          # live -> keep
        _meta("imminent", now + 20_000, now + 320_000),    # starts in 20s (<30s) -> keep
        _meta("soon_but_late", now + 90_000, now + 390_000),  # starts in 90s -> drop
        _meta("far", now + 24 * 3_600_000, now + 24 * 3_600_000 + 300_000),  # ~24h -> drop
        _meta("expired", now - 600_000, now - 1000),       # expired -> drop
    ]
    out = select_live_or_imminent(metas, lead_seconds=30, ref_ms=now)
    slugs = [m.slug for m in out]
    assert slugs == ["live", "imminent"]   # sorted by expiry, only live/imminent


def test_select_live_empty_when_only_upcoming():
    now = 1_000_000
    metas = [_meta("far", now + 24 * 3_600_000, now + 24 * 3_600_000 + 300_000)]
    assert select_live_or_imminent(metas, ref_ms=now) == []
