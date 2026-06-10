"""Tests for the READ-ONLY Kalshi market-data WebSocket feasibility spike.

Covers: missing-credentials clean block, secrets never printed, no order endpoints touched,
read-only subscribe message, active-ticker selection, mocked snapshot/delta -> active-book
normalization, REST fallback preserved when WS unavailable, and check-live-disabled. No network.
"""

import inspect
import json
from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.client import MarketPhase, select_collection_targets
from btc5m.venues.kalshi.hires import (
    HiResConfig, build_sources, run_ws_feasibility, ws_book_available, auth_headers,
    subscribe_message, KalshiBook, normalize_ws_book, KalshiWSBookSource, READ_ONLY_BANNER,
)
from btc5m.venues.kalshi.hires import kalshi_ws as kw
from btc5m.venues.kalshi.hires import sources as sm

ACTIVE = {"ticker": "KXBTC15M-26JUN081630-30", "event_ticker": "KXBTC15M-26JUN081630",
          "status": "active", "close_time": "2026-06-08T16:30:00Z",
          "_phase": MarketPhase.CURRENT_IN_WINDOW.value}


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    for name in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_PRIVATE_KEY_PASSPHRASE",
                 "KALSHI_USE_WEBSOCKET"):
        monkeypatch.delenv(name, raising=False)
    return load_config(mode="paper", load_env=False)


# --------------------------------------------------------------------------- #
# Safety: missing creds blocks, secrets never printed, no order endpoints
# --------------------------------------------------------------------------- #
def test_missing_credentials_blocks_cleanly(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(kw, "_discover_active", lambda *a, **k: ACTIVE)   # no network
    r = run_ws_feasibility(cfg, series="KXBTC15M", seconds=1)
    assert r["status"] == "BLOCKED_MISSING_CREDENTIALS"
    assert r["no_orders"] is True and r["market_data_only"] is True
    assert r["live_submission_allowed"] is False
    assert "KALSHI_KEY_ID" in r["required_env_vars"] and "KALSHI_PRIVATE_KEY_PATH" in r["required_env_vars"]
    assert r["credentials"]["auth_configured"] is False
    assert Path(r["report_md"]).exists()


def test_secrets_are_never_printed(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    monkeypatch.setenv("KALSHI_KEY_ID", "SUPER_SECRET_KEY_ID_XYZ")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(tmp_path / "nope_secret_path.pem"))
    monkeypatch.setattr(kw, "_discover_active", lambda *a, **k: ACTIVE)
    cfg = load_config(mode="paper", load_env=False)       # reload so env is picked up
    r = run_ws_feasibility(cfg, series="KXBTC15M", seconds=1)
    blob = json.dumps(r) + Path(r["report_md"]).read_text(encoding="utf-8")
    assert "SUPER_SECRET_KEY_ID_XYZ" not in blob          # value never leaks
    assert "nope_secret_path.pem" not in blob             # path value never leaks
    assert r["credentials"]["key_id_present"] is True      # presence reported as a bool only
    # dummy/unreadable key -> blocks at signing, no network, no order endpoint
    assert r["status"] in ("BLOCKED_SIGNING", "BLOCKED_CONNECT", "BLOCKED_MISSING_CREDENTIALS")


def test_module_never_references_order_endpoints():
    src = inspect.getsource(kw)
    assert ".submit(" not in src and ".cancel(" not in src
    assert '"cmd": "order"' not in src and "place_order" not in src
    assert kw.MARKET_DATA_CHANNELS == ["orderbook_delta"]          # read-only channel only


def test_subscribe_message_is_read_only():
    m = subscribe_message("KXBTC15M-X")
    assert m["cmd"] == "subscribe" and m["params"]["channels"] == ["orderbook_delta"]
    assert m["params"]["market_tickers"] == ["KXBTC15M-X"]


def test_auth_headers_and_ws_available_block_without_creds(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    hdrs, reason = auth_headers(cfg)
    ok, reason2 = ws_book_available(cfg)
    assert reason == "missing_credentials"
    assert hdrs is None, "auth headers should be absent when credentials are missing"
    assert ok is False and reason2 == "missing_credentials"


def test_connect_kwargs_supports_header_argument_variants():
    hdrs = {"KALSHI-ACCESS-KEY": "redacted-by-caller"}

    def connect_additional(uri, *, additional_headers=None, open_timeout=None,
                           close_timeout=None, max_queue=None):
        return uri, additional_headers, open_timeout, close_timeout, max_queue

    kwargs, header_arg = kw._connect_kwargs(hdrs, connect_fn=connect_additional)
    assert header_arg == "additional_headers"
    assert kwargs == {"additional_headers": hdrs, "open_timeout": 10, "close_timeout": 5, "max_queue": 512}

    def connect_extra(uri, *, extra_headers=None, open_timeout=None):
        return uri, extra_headers, open_timeout

    kwargs, header_arg = kw._connect_kwargs(hdrs, connect_fn=connect_extra)
    assert header_arg == "extra_headers"
    assert kwargs == {"extra_headers": hdrs, "open_timeout": 10}
    assert "additional_headers" not in kwargs and "close_timeout" not in kwargs and "max_queue" not in kwargs

    def connect_without_headers(uri, *, open_timeout=None):
        return uri, open_timeout

    with pytest.raises(TypeError, match="does not support auth headers"):
        kw._connect_kwargs(hdrs, connect_fn=connect_without_headers)


def test_typeerror_reporting_is_sanitized_in_result_and_report(tmp_path, monkeypatch):
    import websockets.sync.client as ws_client

    cfg = _env(tmp_path, monkeypatch)
    secret_key = "SUPER_SECRET_KEY_ID_XYZ"
    secret_path = str(tmp_path / "private_secret_key.pem")
    cfg.kalshi.key_id = secret_key
    cfg.kalshi.private_key_path = secret_path
    cfg.kalshi.private_key_passphrase = "SECRET_PASSPHRASE_XYZ"
    monkeypatch.setattr(kw, "_discover_active", lambda *a, **k: ACTIVE)
    monkeypatch.setattr(kw, "auth_headers",
                        lambda _cfg: ({"KALSHI-ACCESS-KEY": secret_key,
                                       "KALSHI-ACCESS-SIGNATURE": "SECRET_SIGNATURE_XYZ",
                                       "KALSHI-ACCESS-TIMESTAMP": "SECRET_TIMESTAMP_XYZ"}, None))

    def connect_boom(uri, *, additional_headers=None, open_timeout=None, close_timeout=None, max_queue=None):
        raise TypeError(f"bad header kw for {secret_key} at {secret_path} "
                        "KALSHI-ACCESS-SIGNATURE: SECRET_SIGNATURE_XYZ")

    monkeypatch.setattr(ws_client, "connect", connect_boom)
    r = run_ws_feasibility(cfg, series="KXBTC15M", seconds=0.01)
    report = Path(r["report_md"]).read_text(encoding="utf-8")
    blob = json.dumps(r) + report
    assert r["status"] == "BLOCKED_CONNECT"
    assert r["exception_type"] == "TypeError"
    assert "bad header kw" in r["exception_message"]
    assert "## Sanitized traceback" in report and "connect_boom" in report
    assert secret_key not in blob
    assert secret_path not in blob
    assert "SECRET_SIGNATURE_XYZ" not in blob


# --------------------------------------------------------------------------- #
# Active ticker selection (active-first)
# --------------------------------------------------------------------------- #
def test_active_ticker_selection(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)

    class _FakeClient:
        def discover(self, **kw_):
            return [{"ticker": "OLD", "_phase": MarketPhase.CLOSED_PENDING_SETTLE.value, "_close_ms": 1, "_open_ms": 0},
                    {"ticker": "CUR", "_phase": MarketPhase.CURRENT_IN_WINDOW.value, "_close_ms": 9, "_open_ms": 2}]

    active = kw._discover_active(cfg, "KXBTC15M", client=_FakeClient())
    assert active["ticker"] == "CUR"


# --------------------------------------------------------------------------- #
# Mocked WS messages -> normalized active-book rows
# --------------------------------------------------------------------------- #
def test_book_snapshot_and_delta_normalize():
    book = KalshiBook()
    book.apply_snapshot({"yes": [[40, 10]], "no": [[59, 20]]})       # cents
    row = normalize_ws_book(book, ACTIVE, recv=1_780_000_000_000, series="KXBTC15M",
                            line_lookup=lambda _t: 100.0)
    # yes_ask = 1 - best_no_bid(0.59) = 0.41 ; no_ask = 1 - best_yes_bid(0.40) = 0.60
    assert abs(row["yes_ask"] - 0.41) < 1e-9 and abs(row["no_ask"] - 0.60) < 1e-9
    assert row["yes_ask_size"] == 20 and row["no_ask_size"] == 10
    assert row["stream"] == "hires_kalshi_active_book" and row["book_source"] == "websocket"
    assert row["book_age_basis"] == "recv_ms" and row["book_age_ms"] == 0
    assert row["reference_start_price"] == 100.0 and row["live_submission_allowed"] is False
    # a delta that removes the NO bid -> yes_ask becomes None (no synthetic ask)
    book.apply_delta({"side": "no", "price": 59, "delta": -20})
    row2 = normalize_ws_book(book, ACTIVE, recv=1_780_000_000_500, series="KXBTC15M")
    assert row2["yes_ask"] is None


def test_book_accepts_kalshi_fixed_point_ws_payloads():
    book = KalshiBook()
    book.apply_snapshot({"yes_dollars_fp": [["0.4000", "10.00"]],
                         "no_dollars_fp": [["0.5900", "20.00"]]})
    row = normalize_ws_book(book, ACTIVE, recv=1_780_000_000_000, series="KXBTC15M")
    assert abs(row["yes_ask"] - 0.41) < 1e-9 and abs(row["no_ask"] - 0.60) < 1e-9
    assert row["yes_ask_size"] == 20 and row["no_ask_size"] == 10
    assert book.apply_delta({"side": "no", "price_dollars": "0.5900", "delta_fp": "-20.00"}) is True
    row2 = normalize_ws_book(book, ACTIVE, recv=1_780_000_000_500, series="KXBTC15M")
    assert row2["yes_ask"] is None
    assert book.apply_delta({"side": "no", "delta_fp": "1.00"}) is False


# --------------------------------------------------------------------------- #
# REST fallback preserved when WS unavailable / not opted-in
# --------------------------------------------------------------------------- #
def test_rest_fallback_when_ws_unavailable(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    hcfg = HiResConfig()
    hcfg.kalshi_book_source = "websocket"            # opt-in, but no creds -> must fall back to REST
    sources, blockers = build_sources(cfg, hcfg, line_lookup=lambda _t: None)
    kalshi_src = [s for s in sources if getattr(s, "name", "") == "kalshi"][0]
    assert isinstance(kalshi_src, sm.KalshiRESTBookSource)
    assert any("REST polling fallback" in b for b in blockers)


def test_ws_source_class_is_read_only_book_source():
    assert issubclass(KalshiWSBookSource, sm.BaseSource)
    assert KalshiWSBookSource.stream == "hires_kalshi_active_book"


def test_banner_is_no_orders():
    assert "NO ORDERS" in READ_ONLY_BANNER and "READ-ONLY" in READ_ONLY_BANNER


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    assert cfg.live_blockers() and cfg.live_permitted is False
