"""CLI tests for the new commands — must be safe/offline."""

from btc5m.cli import _COMMANDS, main


def test_new_commands_registered():
    for name in (
        "discover-markets",
        "record",
        "record-underlying",
        "backfill-settlements",
        "backfill-official-chainlink",
        "build-features",
        "decide",
        "data-readiness",
        "paper-backtest",
        "run-paper-pipeline",
        "label-status",
    ):
        assert name in _COMMANDS


def test_paper_backtest_blocked_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # No usable labeled rows -> blocked, returns 0, no fabricated P&L, no network.
    assert main(["paper-backtest", "--asset", "BTC", "--duration", "5m"]) == 0


def test_data_readiness_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Empty data dir -> reports blocked readiness, returns 0, no network.
    assert main(["data-readiness", "--asset", "BTC", "--duration", "5m"]) == 0


def test_run_paper_pipeline_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # --no-network: skip discovery/recording; run decide+ledger+summary safely.
    rc = main(["run-paper-pipeline", "--asset", "BTC", "--duration", "5m", "--no-network"])
    assert rc == 0
    # Session summary must be written even with no data.
    summaries = list((tmp_path / "reports" / "paper").glob("session_summary-*.md"))
    assert summaries, "expected a session summary file"


def test_backfill_official_chainlink_blocked_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    for v in ("CHAINLINK_STREAMS_API_KEY", "CHAINLINK_STREAMS_API_SECRET", "CHAINLINK_BTC_FEED_ID"):
        monkeypatch.delenv(v, raising=False)
    # Unconfigured -> reports blocker, returns 0, never fakes OFFICIAL, no network.
    assert main(["backfill-official-chainlink", "--asset", "BTC", "--duration", "5m"]) == 0


def test_build_features_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # No recorded data -> returns 0 with a note, no network.
    assert main(["build-features", "--asset", "BTC", "--duration", "5m"]) == 0


def test_backfill_no_network_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # No recorded markets in a fresh data dir -> returns 0, no network used.
    rc = main(["backfill-settlements", "--asset", "BTC", "--duration", "5m", "--no-network"])
    assert rc == 0


def test_label_status_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    rc = main(["label-status"])
    assert rc == 0


def test_record_underlying_bad_source_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Unknown source -> no clients -> BLOCKER return 1, no network touched.
    rc = main(["record-underlying", "--sources", "bogus", "--seconds", "0"])
    assert rc == 1


def test_backfill_no_network_with_fixture_market(tmp_path, monkeypatch):
    # A completed window with no line/official data -> UNKNOWN row, no network.
    import json

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    market = {
        "slug": "btc-updown-5m-1000",
        "conditionId": "0xcond",
        "id": "1",
        "question": "Bitcoin Up or Down",
        "endDate": "2020-01-01T00:05:00Z",   # long past -> completed
        "eventStartTime": "2020-01-01T00:00:00Z",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["aaa","bbb"]',
        "description": "resolve Up if end >= start",
        "closed": False,
    }
    (raw / "polymarket_markets-20200101.jsonl").write_text(
        json.dumps({"stream": "polymarket_markets", "payload": market}) + "\n",
        encoding="utf-8",
    )
    rc = main(["backfill-settlements", "--asset", "BTC", "--duration", "5m", "--no-network"])
    assert rc == 0
    labels = list((tmp_path / "labels").glob("settlement_labels-*.jsonl"))
    assert labels, "a label row should be written even when UNKNOWN"
    row = json.loads(labels[0].read_text(encoding="utf-8").splitlines()[0])
    assert row["label_source_status"] == "UNKNOWN"
    assert row["reason_code"] in ("MISSING_LINE", "MISSING_SETTLEMENT_PRICE")
    assert row["label_yes_resolved"] is None
