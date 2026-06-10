"""PolymarketClient discovery tests with the network fully mocked (offline).

These prove the FIX: the slug-grid discovery surfaces the currently-live window
(the old order=startDate query missed it), batches by slug, and that timing is
robust to missing Gamma date fields via the slug fallback.
"""

import urllib.error
import urllib.parse

import pytest

from btc5m.config import load_config
from btc5m.data import polymarket_client as pmc
from btc5m.data.polymarket_client import PolymarketClient
from btc5m.discovery import WindowPhase, align_window_start_s, classify_meta, make_slug
from btc5m.schemas import Outcome
from btc5m.timeutils import now_ms


def _market(slug, *, ws_iso=None, exp_iso=None, closed=False, accepting=True):
    m = {
        "id": "1",
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "conditionId": "0xcond_" + slug[-4:],
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["111", "222"]',
        "description": "resolve Up if end >= start",
        "closed": closed,
        "active": not closed,
        "archived": False,
        "acceptingOrders": accepting,
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }
    if ws_iso:
        m["eventStartTime"] = ws_iso
    if exp_iso:
        m["endDate"] = exp_iso
    return m


def _install_fake_http(monkeypatch, registry):
    """Patch _http_get_json so /markets?slug=... returns registered markets."""
    def fake(url, *, timeout=20.0):
        path, _, query = url.partition("?")
        params = urllib.parse.parse_qs(query)
        if path.endswith("/markets"):
            requested = params.get("slug", [])
            closed_filter = params.get("closed", ["false"])[0] == "true"
            out = []
            for s in requested:
                mk = registry.get(s)
                if mk is None:
                    continue
                if closed_filter == bool(mk.get("closed")):
                    out.append(mk)
            return out
        return []
    monkeypatch.setattr(pmc, "_http_get_json", fake)


def test_get_markets_by_slugs_batches_and_dedupes(monkeypatch):
    reg = {
        "btc-updown-5m-1000": _market("btc-updown-5m-1000"),
        "btc-updown-5m-1300": _market("btc-updown-5m-1300"),
        "btc-updown-5m-1600": _market("btc-updown-5m-1600", closed=True),
    }
    _install_fake_http(monkeypatch, reg)
    client = PolymarketClient(load_config(mode="paper"))
    # Without closed -> only the open ones.
    rows = client.get_markets_by_slugs(list(reg), include_closed=False, chunk_size=2)
    slugs = {r["slug"] for r in rows}
    assert slugs == {"btc-updown-5m-1000", "btc-updown-5m-1300"}
    # With closed -> the resolved one is unioned in (needed for labeling).
    rows2 = client.get_markets_by_slugs(list(reg), include_closed=True, chunk_size=2)
    assert {r["slug"] for r in rows2} == set(reg)


def test_discover_markets_finds_the_live_window(monkeypatch):
    """The core regression: discovery must return the currently-in-window market."""
    now = now_ms()
    ws = align_window_start_s(now, 300)        # current 5-min boundary
    cur = make_slug("BTC", "5m", ws)
    nxt = make_slug("BTC", "5m", ws + 300)
    prev = make_slug("BTC", "5m", ws - 300)

    def iso(ts_s):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    reg = {
        cur: _market(cur, ws_iso=iso(ws), exp_iso=iso(ws + 300)),
        nxt: _market(nxt, ws_iso=iso(ws + 300), exp_iso=iso(ws + 600)),
        prev: _market(prev, ws_iso=iso(ws - 300), exp_iso=iso(ws), closed=True),
    }
    _install_fake_http(monkeypatch, reg)
    client = PolymarketClient(load_config(mode="paper"))
    markets = client.discover_markets(asset="BTC", duration="5m")
    by_slug = {m.slug: m for m in markets}
    assert cur in by_slug, "discovery must surface the currently-live window"
    assert nxt in by_slug, "discovery must surface the upcoming window"
    assert prev not in by_slug, "resolved/closed windows are excluded"
    assert classify_meta(by_slug[cur], now_ms=now) is WindowPhase.CURRENTLY_IN_WINDOW


def test_parse_market_window_timing_falls_back_to_slug(monkeypatch):
    """If Gamma omits eventStartTime/endDate, timing comes from the slug ts."""
    client = PolymarketClient(load_config(mode="paper"))
    meta = client._parse_market(_market("btc-updown-5m-1780288800"), asset="BTC")
    assert meta.window_start_ms == 1780288800000          # from slug
    assert meta.expiry_ms == 1780288800000 + 300_000      # start + 5m step


def test_get_raw_book_404_returns_empty(monkeypatch):
    def boom(url, *, timeout=20.0):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(pmc, "_http_get_json", boom)
    client = PolymarketClient(load_config(mode="paper"))
    book = client.get_raw_book("111")  # resolved market's book is gone
    assert book == {"bids": [], "asks": [], "timestamp": None}


def test_get_raw_book_other_errors_propagate(monkeypatch):
    def boom(url, *, timeout=20.0):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
    monkeypatch.setattr(pmc, "_http_get_json", boom)
    client = PolymarketClient(load_config(mode="paper"))
    with pytest.raises(urllib.error.HTTPError):
        client.get_raw_book("111")
