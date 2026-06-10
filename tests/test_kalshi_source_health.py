"""Kalshi source-health reporting (offline)."""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi.source_health import assess_source_health


def test_sources_listed_with_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    cfg = load_config(mode="paper")
    h = assess_source_health(cfg)
    by_name = {s["source"]: s for s in h["sources"]}
    assert set(by_name) == {"kalshi", "coinbase", "binance", "deribit"}
    assert by_name["kalshi"]["required"] is True
    assert by_name["kalshi"]["implemented"] is True
    assert by_name["coinbase"]["required"] is False
    assert by_name["binance"]["used_in_kalshi_feature_builder"] is True
    # deribit disabled by default -> IMPLEMENTED (code exists) but disabled + optional.
    # No rows in this tmp dir, so status is the plain "disabled" (never "stubbed").
    de = by_name["deribit"]
    assert de["enabled"] is False and de["enabled_by_config"] is False
    assert de["implemented"] is True            # code exists regardless of enabled
    assert de["status"] == "disabled"
    assert de["required"] is False and de["optional"] is True
    assert de["selected_for_model_features"] is False
    assert de["disabled_by_config_but_rows_present"] is False
    # notifier reported separately, Noop by default, no secrets
    assert h["notifier"]["provider"] == "noop"


def test_freshness_from_recorded_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    norm = tmp_path / "normalized"
    norm.mkdir(parents=True)
    # a coinbase normalized row with a recent recv_ms + price
    from btc5m.timeutils import now_ms
    row = {"stream": "underlying_coinbase",
           "event": {"source": "coinbase", "recv_ms": now_ms(), "price": 72000.0}}
    # file name uses today's UTC date so _today_file finds it; _latest_file also.
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    (norm / f"underlying_coinbase-{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    h = assess_source_health(cfg)
    cb = next(s for s in h["sources"] if s["source"] == "coinbase")
    assert cb["latest_price"] == 72000.0
    assert cb["stale"] is False
    assert cb["rows_today_normalized"] == 1


def test_deribit_enabled_marks_implemented(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    cfg = load_config(mode="paper")
    h = assess_source_health(cfg)
    de = next(s for s in h["sources"] if s["source"] == "deribit")
    assert de["enabled"] is True and de["enabled_by_config"] is True
    assert de["implemented"] is True
    assert de["joined_into_feature_rows"] is True
    # enabled but no rows recorded yet in this tmp dir -> explicit, not contradictory.
    assert de["status"] == "enabled_no_rows_yet"
    assert de["missing_reason"] == "DERIBIT_ENABLED_NO_ROWS_YET"
