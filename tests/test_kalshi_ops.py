"""Unified ops/monitoring layer — read-only aggregators + CLI registry + safety.

All offline; hermetic via tmp DATA_DIR/REPORTS_DIR; no secrets; never touches
collectors; never submits orders.
"""

import json
from datetime import datetime, timezone

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config
from btc5m.venues.kalshi import ops

WIN = 15 * 60 * 1000


def _now_ms():
    from btc5m.timeutils import now_ms
    return now_ms()


def _day():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _write_norm(tmp_path, prefix, recv_ms, **extra):
    d = tmp_path / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    ev = {"recv_ms": recv_ms}
    ev.update(extra)
    (d / f"{prefix}-{_day()}.jsonl").write_text(
        json.dumps({"stream": prefix, "event": ev}) + "\n", encoding="utf-8")


def _write_features_labels(tmp_path, *, n_windows=3, with_orphan=True):
    feats = tmp_path / "features"; feats.mkdir(parents=True, exist_ok=True)
    labels = tmp_path / "labels"; labels.mkdir(parents=True, exist_ok=True)
    base = _now_ms() - 3 * 3_600_000
    fr, lr = [], []
    for w in range(n_windows):
        close = base + (w + 1) * WIN
        for i in range(4):
            fr.append({"market_ticker": f"KX-{w}", "has_orderbook": True, "has_underlying": True,
                       "has_start_reference": True, "book_ok": True, "seconds_to_close": 120,
                       "as_of_ms": close - 120_000, "close_ms": close, "feature_set_version": 2,
                       "yes_ask": 0.42, "no_ask": 0.60, "reference_start_price": 70000.0})
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL", "label_yes_resolved": w % 2})
    if with_orphan:
        lr.append({"market_ticker": "KX-ORPHAN", "label_source_status": "OFFICIAL", "label_yes_resolved": 1})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text("\n".join(json.dumps(r) for r in fr) + "\n", "utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text("\n".join(json.dumps(r) for r in lr) + "\n", "utf-8")


# --------------------------------------------------------------------------- #
# Collector status
# --------------------------------------------------------------------------- #
def test_collector_status_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    now = _now_ms()
    _write_norm(tmp_path, "kalshi_orderbook", now)
    _write_norm(tmp_path, "underlying_coinbase", now, price=70000.0)
    _write_norm(tmp_path, "underlying_binance_futures", now, best_bid=70000.0)
    s = ops.collector_status(load_config(mode="paper"))
    assert s["verdict"] == "ACTIVE" and s["kalshi_stale"] is False and s["underlying_ok"] is True


def test_collector_status_stalled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    old = _now_ms() - 600_000   # 10 min old
    _write_norm(tmp_path, "kalshi_orderbook", old)
    _write_norm(tmp_path, "underlying_coinbase", old, price=70000.0)
    s = ops.collector_status(load_config(mode="paper"))
    assert s["verdict"] in ("STALLED", "DEGRADED") and s["kalshi_stale"] is True


def test_collector_status_missing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = ops.collector_status(load_config(mode="paper"))   # no files -> no crash
    assert "verdict" in s and s["sources"]["kalshi"]["rows_today"] in (0, None)


# --------------------------------------------------------------------------- #
# Gate progress
# --------------------------------------------------------------------------- #
def test_gate_progress_excludes_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_features_labels(tmp_path, n_windows=3, with_orphan=True)
    g = ops.gate_progress(load_config(mode="paper"))
    assert g["gate_windows"] == 3 and g["orphan_labels_excluded"] == 1
    assert g["windows_remaining_backtest"] == 60 - 3
    assert g["bottleneck"] == "windows"


def test_gate_progress_zero_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    g = ops.gate_progress(load_config(mode="paper"))   # no data
    assert g["gate_windows"] == 0 and g["capture_rate_per_hour"] == 0.0
    assert g["eta_backtest_hours_actual"] is None


# --------------------------------------------------------------------------- #
# Model health / backtest summary
# --------------------------------------------------------------------------- #
def test_model_health_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    m = ops.model_health(load_config(mode="paper"))
    assert m["status"] == "MODEL_MISSING" and m["policy_can_emit_paper_candidate"] is False


def test_backtest_summary_missing_then_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert ops.backtest_summary(cfg)["status"] == "BACKTEST_MISSING"
    d = tmp_path / "reports" / "backtests"; d.mkdir(parents=True)
    (d / "kalshi_baseline_comparison_20260602_000000.json").write_text(json.dumps({
        "meta": {"series": "KXBTC15M", "gate_windows": 80, "gate_met": False, "diagnostic": True},
        "results": {"no_trade": {"net_pnl": 0}, "microstructure": {"total_simulated_trades": 5,
                    "net_pnl": -0.5, "hit_rate": 0.4}}}) + "\n", "utf-8")
    b = ops.backtest_summary(cfg)
    assert b["status"] == "OK" and b["diagnostic"] is True and b["usable_by_policy"] is False
    assert b["baselines"]["microstructure"]["trades"] == 5


# --------------------------------------------------------------------------- #
# Paper / lock summary
# --------------------------------------------------------------------------- #
def test_paper_summary_no_activity_then_aggregates(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    assert ops.paper_summary(cfg)["status"] == "NO_PAPER_ACTIVITY"
    paper = tmp_path / "paper"; paper.mkdir(parents=True)
    rows = [{"decision_state": "REJECTED", "fill_status": "not_traded", "reason_codes": ["INVALID_OR_INCOMPLETE_BOOK"]},
            {"decision_state": "MANUAL_REVIEW", "fill_status": "not_traded", "reason_codes": ["UNCALIBRATED_MODEL"]},
            {"decision_state": "SKIPPED", "fill_status": "not_traded", "reason_codes": ["MARKET_CLOSED"]},
            {"decision_state": "SKIPPED", "fill_status": "not_traded", "reason_codes": ["OUTSIDE_DECISION_WINDOW"]},
            {"decision_state": "WATCH", "fill_status": "not_traded", "reason_codes": []}]
    (paper / f"kalshi_paper_ledger-{_day()}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")
    p = ops.paper_summary(cfg)
    assert p["status"] == "OK" and p["decisions_by_state"]["REJECTED"] == 1
    assert p["decisions_by_state"]["MANUAL_REVIEW"] == 1 and p["open_paper_positions"] == 0
    # why-not-traded buckets (legacy INVALID_OR_INCOMPLETE_BOOK still maps to book)
    assert p["skipped_due_to_timing"] == 2
    assert p["rejected_due_to_book"] == 1
    assert p["rejected_due_to_model_uncalibrated"] == 1


def test_lock_summary_present_no_positions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = ops.lock_summary(load_config(mode="paper"))
    assert s["status"] == "OK" and s["open_positions"] == 0


# --------------------------------------------------------------------------- #
# Safety status
# --------------------------------------------------------------------------- #
def test_safety_status_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = ops.safety_status(load_config(mode="paper"))
    assert s["headline"] == "LIVE TRADING DISABLED" and s["live_submission_allowed"] is False
    assert s["live_adapter_refuses"] is True and not s["dangerous_warnings"]


def test_safety_status_dangerous_config_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("KILL_SWITCH_ENABLED", "false")
    s = ops.safety_status(load_config(mode="paper"))
    assert s["headline"].startswith("WARNING") and s["dangerous_warnings"]
    assert s["live_submission_allowed"] is False    # still impossible (no submit path)


# --------------------------------------------------------------------------- #
# Ops status / doctor / eod
# --------------------------------------------------------------------------- #
def test_ops_status_runs_missing_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_KEY_ID", "SECRET_VALUE")
    s = ops.ops_status(load_config(mode="paper"))
    assert s["safety"]["headline"] == "LIVE TRADING DISABLED"
    assert "SECRET_VALUE" not in json.dumps(s, default=str)   # no secrets in the snapshot


def test_doctor_summarizes_without_running_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    d = ops.doctor(load_config(mode="paper"), run_tests=False)
    assert d["overall"] in ("PASS", "WARN", "FAIL")
    names = {c["check"] for c in d["checks"]}
    assert "live_disabled" in names and "pytest" not in names   # tests not run by default


def test_eod_summary_report_and_noop_notification(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PUSHOVER_ENABLED", raising=False)
    r = ops.eod_summary(load_config(mode="paper"), send_notification=True)
    assert "BTC 15m EOD" in r["notification_line"] and r["safety_headline"] == "LIVE TRADING DISABLED"
    assert isinstance(r["notified"], bool)   # Noop fallback never breaks


# --------------------------------------------------------------------------- #
# CLI registry + safety
# --------------------------------------------------------------------------- #
def test_ops_commands_registered():
    for c in ("kalshi-ops-status", "kalshi-collector-status", "kalshi-gate-progress",
              "kalshi-model-health", "kalshi-backtest-summary", "kalshi-paper-summary",
              "kalshi-lock-summary", "kalshi-safety-status", "kalshi-doctor",
              "kalshi-eod-summary", "kalshi-notify-test"):
        assert c in _COMMANDS
    assert not any("arb" in name.lower() for name in _COMMANDS)


def test_ops_cli_runs_and_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    assert main(["kalshi-safety-status", "--series", "KXBTC15M"]) == 0
    assert main(["kalshi-gate-progress", "--series", "KXBTC15M"]) == 0
    assert main(["kalshi-eod-summary", "--series", "KXBTC15M", "--write-report"]) == 0
    assert main(["check-live-disabled"]) == 0
