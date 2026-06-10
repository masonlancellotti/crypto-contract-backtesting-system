"""Polymarket discovery tests.

Network calls are gated: parsing logic is tested offline against a captured
Gamma payload; the live-endpoint test is skipped automatically when offline so
the suite never fails for lack of connectivity (and never fakes success).
"""

import urllib.error
import urllib.request

import pytest

from btc5m.config import load_config
from btc5m.data.polymarket_client import (
    PolymarketClient,
    _comparison_from_description,
    _iso_to_ms,
    _slug_prefix,
)
from btc5m.schemas import Comparison, MarketType, Outcome


def _online() -> bool:
    try:
        req = urllib.request.Request(
            "https://gamma-api.polymarket.com/markets?limit=1",
            headers={"User-Agent": "btc5m-test"},
        )
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False


# Captured shape of a real BTC 5m "Up or Down" Gamma market (trimmed).
_SAMPLE_MARKET = {
    "id": "2392399",
    "question": "Bitcoin Up or Down - May 31, 3:20AM-3:25AM ET",
    "conditionId": "0x3b5c1357bb428ff722116f06bb2c283a74a60e7c7655244ac0360a8c6ed3474a",
    "slug": "btc-updown-5m-1780212000",
    "resolutionSource": "https://data.chain.link/streams/btc-usd",
    "endDate": "2026-05-31T07:25:00Z",
    "eventStartTime": "2026-05-31T07:20:00Z",
    "outcomes": '["Up", "Down"]',
    "clobTokenIds": '["111", "222"]',
    "orderPriceMinTickSize": 0.01,
    "orderMinSize": 5,
    "active": True,
    "closed": False,
    "archived": False,
    "description": (
        "This market will resolve to \"Up\" if the Bitcoin price at the end of the "
        "time range is greater than or equal to the price at the beginning. "
        "Otherwise it will resolve to \"Down\"."
    ),
}


def test_slug_prefix():
    assert _slug_prefix("BTC", "5m") == "btc-updown-5m-"
    assert _slug_prefix("eth", "15m") == "eth-updown-15m-"


def test_iso_to_ms():
    assert _iso_to_ms("2026-05-31T07:25:00Z") == 1780212300000
    assert _iso_to_ms(None) is None
    assert _iso_to_ms("not-a-date") is None


def test_comparison_from_description():
    assert _comparison_from_description("greater than or equal to", Comparison.GT) is Comparison.GTE
    assert _comparison_from_description("strictly greater than", Comparison.GTE) is Comparison.GT
    assert _comparison_from_description("", Comparison.GTE) is Comparison.GTE


def test_parse_market_maps_all_fields():
    cfg = load_config(mode="paper")
    client = PolymarketClient(cfg)
    meta = client._parse_market(_SAMPLE_MARKET, asset="BTC")
    assert meta is not None
    assert meta.market_type is MarketType.UP_DOWN
    assert meta.comparison is Comparison.GTE          # from explicit description wording
    assert meta.condition_id == _SAMPLE_MARKET["conditionId"]
    assert meta.slug == "btc-updown-5m-1780212000"
    assert meta.yes_token_id == "111" and meta.no_token_id == "222"
    assert meta.yes_outcome_label == "Up" and meta.no_outcome_label == "Down"
    assert meta.expiry_ms == 1780212300000
    assert meta.window_start_ms == 1780212000000
    assert meta.tick_size == 0.01 and meta.min_order_size == 5.0
    assert meta.status == "active"
    # UP_DOWN line is not known until the window opens.
    assert meta.line is None
    assert not meta.has_settlement_metadata


@pytest.mark.skipif(not _online(), reason="no network access to Polymarket Gamma API")
def test_live_discovery_smoke():
    cfg = load_config(mode="paper")
    client = PolymarketClient(cfg)
    markets = client.discover_markets(asset="BTC", duration="5m")
    # We cannot assert >0 (markets are short-lived), but the call must succeed
    # and every returned market must be a well-formed up/down BTC 5m contract.
    for m in markets:
        assert m.slug.startswith("btc-updown-5m-")
        assert m.market_type is MarketType.UP_DOWN
        assert m.comparison in (Comparison.GTE, Comparison.GT)
        assert m.expiry_ms > 0
        assert m.yes_token_id and m.no_token_id
    # If at least one market is open, fetching its book must return both sides
    # or a clearly-empty book (never crash).
    if markets:
        m = markets[0]
        book = client.get_book(m.contract_id, Outcome.YES, m.yes_token_id)
        assert book.recv_ms >= book.ts_ms or book.ts_ms > 0
