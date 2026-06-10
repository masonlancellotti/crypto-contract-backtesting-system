"""Kalshi CLI registration, safety (live disabled, auth, dormant Polymarket),
and an offline paper-pipeline run. All offline; network fully mocked."""

from datetime import datetime, timedelta, timezone

import pytest

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config


def test_kalshi_commands_registered():
    for name in (
        "kalshi-discover", "kalshi-inspect", "kalshi-record",
        "kalshi-backfill-settlements", "kalshi-data-readiness",
        "kalshi-auth-smoke", "run-kalshi-paper-pipeline",
    ):
        assert name in _COMMANDS


def test_kalshi_live_adapter_refuses_by_default():
    from btc5m.execution.live_kalshi import LiveKalshiExecutionAdapter
    cfg = load_config(mode="paper")
    adapter = LiveKalshiExecutionAdapter(cfg)
    blockers = adapter.preflight()
    fill = adapter.submit()
    assert blockers and fill["status"] == "rejected"
    assert any("LIVE_TRADING_ENABLED" in b for b in blockers)


def test_kalshi_auth_smoke_no_keys_and_no_secret_print(capsys, monkeypatch):
    from btc5m import cli as cli_mod

    for v in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_PRIVATE_KEY_PASSPHRASE"):
        monkeypatch.delenv(v, raising=False)
    real_load_config = cli_mod.load_config
    monkeypatch.setattr(cli_mod, "load_config", lambda mode=None: real_load_config(mode=mode, load_env=False))
    assert main(["kalshi-auth-smoke"]) == 0
    out = capsys.readouterr().out
    assert "auth_configured: False" in out
    assert "public_market_data_usable_without_auth: True" in out


def test_check_live_disabled_passes():
    assert main(["check-live-disabled"]) == 0


def test_kalshi_data_readiness_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    assert main(["kalshi-data-readiness"]) == 0


def _fixture_market():
    now = datetime.now(timezone.utc)
    return {
        "ticker": "KXBTC15M-26JUN010345-45",
        "event_ticker": "KXBTC15M-26JUN010345",
        "title": "BTC price up in next 15 mins?",
        "yes_sub_title": "Target Price: $72,901.10",
        "status": "active",
        "result": "",
        "open_time": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_time": (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiration_time": (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules_primary": "If the simple average ... is at least the simple average ...",
        "updated_time": "2026-06-01T07:31:00Z",
        "_phase": "CURRENT_IN_WINDOW",
    }


def test_run_kalshi_paper_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    from btc5m import cli
    from btc5m.venues.kalshi.client import KalshiClient

    market = _fixture_market()
    raw_ob = {"orderbook_fp": {"yes_dollars": [["0.40", "500"]], "no_dollars": [["0.58", "500"]]}}
    monkeypatch.setattr(KalshiClient, "discover", lambda self, **kw: [market])
    monkeypatch.setattr(KalshiClient, "get_orderbook", lambda self, t, **kw: raw_ob)
    monkeypatch.setattr(KalshiClient, "get_market", lambda self, t: market)
    monkeypatch.setattr(KalshiClient, "server_date_header", lambda self: "Mon, 01 Jun 2026 07:30:00 GMT")
    # No underlying network: force build_underlying_client to fail (spot None, no sources).
    def _no_underlying(name, cfg, **kw):
        raise ValueError(f"unknown source {name}")
    monkeypatch.setattr(cli, "build_underlying_client", _no_underlying)

    rc = main(["run-kalshi-paper-pipeline", "--series", "KXBTC15M", "--seconds", "0",
               "--max-markets", "1", "--sources", "coinbase"])
    assert rc == 0
    ledger = list((tmp_path / "paper").glob("kalshi_paper_ledger-*.jsonl"))
    summary = list((tmp_path / "reports" / "paper").glob("kalshi_session_summary-*.md"))
    assert ledger, "paper pipeline must write a Kalshi ledger"
    assert summary, "paper pipeline must write a Kalshi session summary"
    # Uncalibrated baseline -> never a PAPER_CANDIDATE.
    import json
    rows = [json.loads(l) for l in ledger[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and all(r["decision_state"] != "PAPER_CANDIDATE" for r in rows)
    assert all(r["is_paper"] is True for r in rows)


def test_kalshi_inspect_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    from btc5m.venues.kalshi.client import KalshiClient
    market = _fixture_market()
    raw_ob = {"orderbook_fp": {"yes_dollars": [["0.40", "500"]], "no_dollars": [["0.58", "500"]]}}
    monkeypatch.setattr(KalshiClient, "get_market", lambda self, t: market)
    monkeypatch.setattr(KalshiClient, "get_orderbook", lambda self, t, **kw: raw_ob)
    assert main(["kalshi-inspect", "--ticker", "KXBTC15M-26JUN010345-45"]) == 0
