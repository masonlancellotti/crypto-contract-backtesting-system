"""CLI tests for manual override + diagnostics + continuous collection.

Network is fully mocked; these run offline and never place orders.
"""

import urllib.parse

from btc5m.cli import _COMMANDS, main
from btc5m.data import polymarket_client as pmc
from btc5m.discovery import align_window_start_s, make_slug
from btc5m.timeutils import now_ms


def _iso(ts_s):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _live_market(slug, ws, dur=300):
    return {
        "id": "1", "slug": slug, "question": "Bitcoin Up or Down",
        "conditionId": "0xcond", "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["111", "222"]',
        "description": "resolve Up if end >= start",
        "closed": False, "active": True, "archived": False, "acceptingOrders": True,
        "eventStartTime": _iso(ws), "endDate": _iso(ws + dur),
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }


def _install(monkeypatch, registry):
    def fake_http(url, *, timeout=20.0):
        path, _, query = url.partition("?")
        params = urllib.parse.parse_qs(query)
        if path.endswith("/book"):
            # Real Polymarket CLOB levels are dicts with string price/size.
            return {
                "bids": [{"price": "0.45", "size": "120"}, {"price": "0.44", "size": "300"}],
                "asks": [{"price": "0.46", "size": "150"}, {"price": "0.47", "size": "400"}],
                "timestamp": now_ms(),
            }
        if path.endswith("/markets"):
            requested = params.get("slug", [])
            if not requested:
                return []  # legacy startDate query -> nothing
            closed_filter = params.get("closed", ["false"])[0] == "true"
            return [registry[s] for s in requested
                    if s in registry and bool(registry[s].get("closed")) == closed_filter]
        return []
    monkeypatch.setattr(pmc, "_http_get_json", fake_http)
    monkeypatch.setattr(pmc, "_http_server_date", lambda url, timeout=10.0: "Mon, 01 Jun 2026 00:00:00 GMT")


def test_new_commands_registered():
    for name in ("debug-discovery", "inspect-market", "record-market", "collect-continuous"):
        assert name in _COMMANDS


def test_inspect_market_by_slug(monkeypatch, capsys):
    now = now_ms()
    ws = align_window_start_s(now, 300)
    slug = make_slug("BTC", "5m", ws)
    _install(monkeypatch, {slug: _live_market(slug, ws)})
    rc = main(["inspect-market", "--slug", slug])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CURRENTLY_IN_WINDOW" in out
    assert "YES token" in out and "111" in out
    assert "NO orders placed" in out


def test_inspect_market_by_url(monkeypatch):
    now = now_ms()
    ws = align_window_start_s(now, 300)
    slug = make_slug("BTC", "5m", ws)
    _install(monkeypatch, {slug: _live_market(slug, ws)})
    rc = main(["inspect-market", "--url", f"https://polymarket.com/event/{slug}"])
    assert rc == 0


def test_inspect_market_missing_slug_blocks():
    # No --slug/--url -> precise blocker, non-zero, no crash.
    assert main(["inspect-market"]) == 1


def test_inspect_market_not_found(monkeypatch):
    _install(monkeypatch, {})  # registry empty -> not found
    assert main(["inspect-market", "--slug", "btc-updown-5m-999"]) == 1


def test_record_market_by_slug_writes_data(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    now = now_ms()
    ws = align_window_start_s(now, 300)
    slug = make_slug("BTC", "5m", ws)
    _install(monkeypatch, {slug: _live_market(slug, ws)})
    # --seconds 0 -> one poll cycle; --no-line-capture avoids the underlying feed.
    rc = main(["record-market", "--slug", slug, "--seconds", "0", "--no-line-capture"])
    assert rc == 0
    books = list((tmp_path / "raw").glob("polymarket_book-*.jsonl"))
    markets = list((tmp_path / "raw").glob("polymarket_markets-*.jsonl"))
    assert books and markets, "record-market must persist raw market + book data"


def test_debug_discovery_runs_offline(monkeypatch, capsys):
    now = now_ms()
    ws = align_window_start_s(now, 300)
    slug = make_slug("BTC", "5m", ws)
    _install(monkeypatch, {slug: _live_market(slug, ws)})
    rc = main(["debug-discovery", "--asset", "BTC", "--duration", "5m", "--lookahead-hours", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CURRENTLY_IN_WINDOW" in out
    assert "slug interpretation" in out
    assert "mismatch check" in out


def test_collect_continuous_bounded(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    now = now_ms()
    ws = align_window_start_s(now, 300)
    slug = make_slug("BTC", "5m", ws)
    _install(monkeypatch, {slug: _live_market(slug, ws)})
    # Bogus sources/line-source -> no underlying network; mocked book/markets only.
    rc = main([
        "collect-continuous", "--asset", "BTC", "--duration", "5m",
        "--max-cycles", "1", "--max-markets", "1", "--interval", "0",
        "--rediscover-seconds", "0", "--process-seconds", "0",
        "--sources", "bogus", "--line-source", "bogus",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "collect-continuous summary" in out
    assert "no orders placed" in out
    # The live window's book must have been recorded.
    assert list((tmp_path / "raw").glob("polymarket_book-*.jsonl"))
