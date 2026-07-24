"""Tests for kalshi-backfill-trades chunk sizing: fractional --chunk-hours
(e.g. 0.25 for dense tape periods that hit the page cap at 1h), the > 0
guard, and that the trade_id dedupe stays idempotent across reruns. Offline:
the Kalshi client is stubbed; no network, no orders.
"""

import json

import pytest

from btc5m import cli
from btc5m.config import load_config
from btc5m.venues.kalshi import backfill_trades as bt

DAY = "20260601"
DAY_START_S = 1_780_272_000  # 2026-06-01T00:00:00Z


class _FakeClient:
    """Records get_trades chunk boundaries; serves a fixed tape."""

    calls: list[tuple[int, int]] = []
    tape: list[dict] = []

    def __init__(self, config):
        pass

    def get_trades(self, *, min_ts, max_ts, limit, max_pages):
        _FakeClient.calls.append((min_ts, max_ts))
        return [t for t in _FakeClient.tape
                if min_ts <= bt.iso_to_ms(t["created_time"]) // 1000 < max_ts]


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(bt, "KalshiClient", _FakeClient)
    _FakeClient.calls = []
    _FakeClient.tape = []
    return _FakeClient


def _trade(tid: str, ts_s: int, ticker: str = "KXBTC15M-26JUN011830-30") -> dict:
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(ts_s, tz=timezone.utc).isoformat()
    return {"ticker": ticker, "trade_id": tid, "created_time": iso,
            "yes_price": 50, "no_price": 50, "count": 1, "taker_side": "yes",
            "is_block_trade": False}


def test_fractional_chunk_hours_makes_15_minute_chunks(fake_client):
    cfg = load_config()
    r = bt.backfill_trades(cfg, series="KXBTC15M", start_date=DAY,
                           end_date=DAY, chunk_hours=0.25, emit=lambda *a: None)
    assert r["chunks"] == 96  # 24h / 15min
    assert len(fake_client.calls) == 96
    starts = [c[0] for c in fake_client.calls]
    assert starts[0] == DAY_START_S
    assert all(b - a == 900 for a, b in zip(starts, starts[1:]))
    assert fake_client.calls[-1][1] == DAY_START_S + 86_400


def test_chunk_hours_must_be_positive(fake_client):
    cfg = load_config()
    for bad in (0, 0.0, -1, -0.5, None):
        with pytest.raises(ValueError):
            bt.backfill_trades(cfg, series="KXBTC15M", start_date=DAY,
                               end_date=DAY, chunk_hours=bad,
                               emit=lambda *a: None)
    assert fake_client.calls == []  # rejected before any fetch


def test_fractional_chunks_preserve_trade_id_dedupe(fake_client, tmp_path):
    cfg = load_config()
    fake_client.tape = [_trade("t1", DAY_START_S + 100),
                        _trade("t2", DAY_START_S + 1_000),
                        _trade("skip-other-series", DAY_START_S + 200,
                               ticker="KXETH15M-26JUN011830-30")]
    kw = dict(series="KXBTC15M", start_date=DAY, end_date=DAY,
              chunk_hours=0.25, emit=lambda *a: None)
    r1 = bt.backfill_trades(cfg, **kw)
    assert r1["written"] == 2 and r1["duplicates_skipped"] == 0
    r2 = bt.backfill_trades(cfg, **kw)  # rerun: idempotent
    assert r2["written"] == 0 and r2["duplicates_skipped"] == 2

    path = tmp_path / "data" / "normalized" / f"kalshi_trades-{DAY}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(row["event"]["trade_id"] for row in rows) == ["t1", "t2"]
    assert all(row["event"]["backfilled"] for row in rows)


def test_cli_accepts_chunk_hours_0_25(fake_client, monkeypatch, capsys):
    seen = {}

    def _spy(cfg, **kwargs):
        seen.update(kwargs)
        return {"chunks": 96, "fetched": 0, "series_matched": 0, "written": 0,
                "duplicates_skipped": 0, "errors": 0, "days_touched": 0}

    monkeypatch.setattr(bt, "backfill_trades", _spy)
    rc = cli.main(["kalshi-backfill-trades", "--series", "KXBTC15M",
                   "--start-date", DAY, "--end-date", DAY,
                   "--chunk-hours", "0.25"])
    assert rc == 0
    assert seen["chunk_hours"] == 0.25


@pytest.mark.parametrize("bad", ["0", "-0.5"])
def test_cli_rejects_nonpositive_chunk_hours(fake_client, monkeypatch, capsys, bad):
    called = []
    monkeypatch.setattr(bt, "backfill_trades",
                        lambda cfg, **kw: called.append(kw))
    rc = cli.main(["kalshi-backfill-trades", "--series", "KXBTC15M",
                   "--start-date", DAY, "--chunk-hours", bad])
    assert rc == 1
    assert called == []
    assert "must be > 0" in capsys.readouterr().out
