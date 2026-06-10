"""Final integration / regression checks: dependency-check, CLI registry, and that
every important read-only command runs (no crash) on empty data, with safety intact.
"""

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config
from btc5m.venues.kalshi import ops

# Read-only / safe-on-empty commands that must run cleanly even with no data.
_SAFE_COMMANDS = [
    ["dependency-check"],
    ["status"],
    ["kalshi-data-readiness", "--series", "KXBTC15M"],
    ["kalshi-label-audit", "--series", "KXBTC15M"],
    ["kalshi-clean-orphan-labels", "--series", "KXBTC15M", "--dry-run"],
    ["source-health", "--series", "KXBTC15M"],
    ["kalshi-gate-progress", "--series", "KXBTC15M"],
    ["kalshi-collector-status", "--series", "KXBTC15M"],
    ["kalshi-train-dry-run", "--series", "KXBTC15M"],
    ["kalshi-split-report", "--series", "KXBTC15M"],
    ["kalshi-model-health", "--series", "KXBTC15M"],
    ["kalshi-backtest-summary", "--series", "KXBTC15M"],
    ["kalshi-policy-report", "--series", "KXBTC15M"],
    ["kalshi-paper-summary", "--series", "KXBTC15M"],
    ["kalshi-lock-dry-run", "--series", "KXBTC15M"],
    ["kalshi-lock-summary", "--series", "KXBTC15M"],
    ["kalshi-lock-sim", "--series", "KXBTC15M", "--limit", "5"],
    ["kalshi-safety-status", "--series", "KXBTC15M"],
    ["kalshi-live-blockers", "--series", "KXBTC15M"],
    ["kalshi-live-readiness", "--series", "KXBTC15M"],
    ["kalshi-ops-status", "--series", "KXBTC15M"],
    ["kalshi-doctor", "--series", "KXBTC15M"],
    ["kalshi-notify-test", "--series", "KXBTC15M"],
    ["check-live-disabled"],
]


def test_all_commands_have_callable_handlers():
    assert _COMMANDS and all(callable(v) for v in _COMMANDS.values())
    # the ops + integration commands from prompts 8/9 are wired
    for c in ("dependency-check", "kalshi-ops-status", "kalshi-doctor", "kalshi-safety-status"):
        assert c in _COMMANDS


def test_safe_commands_run_on_empty_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    failures = []
    for argv in _SAFE_COMMANDS:
        try:
            rc = main(argv)
            if rc != 0:
                failures.append((argv, f"rc={rc}"))
        except Exception as exc:  # noqa: BLE001
            failures.append((argv, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"commands failed on empty data: {failures}"


def test_dependency_check_structure(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    d = ops.dependency_check(load_config(mode="paper"))
    # stdlib fallback is active IFF the serious stack (numpy+pandas+sklearn) is missing.
    assert isinstance(d["serious_training_available"], bool)
    assert d["stdlib_fallback_active"] == (not d["serious_training_available"])
    assert "training_path" in d and "lightgbm_challenger" in d
    assert "numpy" in d["dependencies"] and "lightgbm" in d["dependencies"]
    assert set(d["features"]) >= {"parquet_dataset_output", "lightgbm_challenger_model", "sklearn_models"}
    # the recommended install + warning are present (text differs by availability)
    assert "models" in d["recommended_install"]
    assert isinstance(d["warning"], str) and d["warning"]


def test_dependency_check_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["dependency-check"]) == 0
    assert main(["dependency-check", "--json"]) == 0


def test_primary_dormant_optional_invariants(monkeypatch):
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    cfg = load_config(mode="paper")
    assert cfg.primary_venue == "kalshi"
    assert cfg.polymarket_dormant is True
    assert cfg.deribit.enabled is False        # optional native source, off by default
    # no flat-position arbitrage scanner exists anywhere in the CLI
    assert not any("arb" in name.lower() for name in _COMMANDS)


def test_safety_invariants_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    assert cfg.trading_mode == "paper" and cfg.live_trading_enabled is False
    assert cfg.kill_switch_enabled is True and cfg.require_manual_confirmation is True
    assert cfg.live_readiness.submit_enabled is False and cfg.live_readiness.dry_run_only is True
    assert cfg.live_readiness.allow_market_orders is False
    assert cfg.paper_policy.live_submission_allowed is False
    assert cfg.lock.live_submission_allowed is False
    s = ops.safety_status(cfg)
    assert s["headline"] == "LIVE TRADING DISABLED" and s["live_submission_allowed"] is False
    m = ops.model_health(cfg)   # empty -> no model -> cannot emit candidate
    assert m["policy_can_emit_paper_candidate"] is False
