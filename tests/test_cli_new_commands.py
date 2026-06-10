"""CLI checks for the shared (venue-agnostic) commands that remain after the
legacy Polymarket BTC 5m leg was removed."""

from btc5m.cli import _COMMANDS, main


def test_shared_commands_registered():
    for name in ("record-underlying", "record-deribit", "check-live-disabled",
                 "notify-test", "notification-health", "dependency-check",
                 "source-health", "status", "init"):
        assert name in _COMMANDS, name


def test_legacy_polymarket_commands_removed():
    for name in ("discover-markets", "debug-discovery", "inspect-market", "record",
                 "record-market", "collect-continuous", "backfill-settlements",
                 "backfill-official-chainlink", "build-features", "decide",
                 "data-readiness", "paper-backtest", "run-paper-pipeline",
                 "label-status", "paper", "eod"):
        assert name not in _COMMANDS, name


def test_record_underlying_bad_source_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    rc = main(["record-underlying", "--sources", "bogus", "--seconds", "0"])
    assert rc in (0, 1)  # must not raise
