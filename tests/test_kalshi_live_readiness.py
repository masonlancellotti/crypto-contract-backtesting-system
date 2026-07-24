"""Live-readiness scaffolding — config safety, credential preflight (no secrets),
readiness state machine, dry-run order payloads, live adapter hard refusal, paper/
live parity, audit logging, and proof that nothing can submit.

Live trading must remain impossible: live_submission_allowed is always False and no
order/cancel HTTP mutation can occur under default config.
"""

import json

from btc5m.cli import _COMMANDS, main
from btc5m.config import load_config
from btc5m.execution.live_kalshi import LiveKalshiExecutionAdapter
from btc5m.venues.kalshi.live_readiness import (
    NoConfirmationProvider, assess_live_readiness, credential_status,
    kalshi_private_read_preflight, write_audit_log,
)
from btc5m.venues.kalshi.lock_profit import LockOrderIntent
from btc5m.venues.kalshi.order_planner import build_dry_run_order_payload, payload_from_intent
from btc5m.venues.kalshi.policy import CandidateOrderIntent


# --------------------------------------------------------------------------- #
# Config defaults
# --------------------------------------------------------------------------- #
def test_live_safe_defaults(monkeypatch):
    for v in ("KALSHI_LIVE_READINESS_ENABLED", "KALSHI_LIVE_SUBMIT_ENABLED",
              "KALSHI_LIVE_DRY_RUN_ONLY", "LIVE_TRADING_ENABLED", "KILL_SWITCH_ENABLED",
              "KALSHI_ALLOW_MARKET_ORDERS"):
        monkeypatch.delenv(v, raising=False)
    cfg = load_config(mode="paper")
    lr = cfg.live_readiness
    assert lr.enabled is False and lr.submit_enabled is False and lr.dry_run_only is True
    assert lr.allow_market_orders is False and lr.allow_private_reads is False
    assert lr.live_submission_allowed is False
    assert cfg.live_trading_enabled is False and cfg.kill_switch_enabled is True
    assert cfg.require_manual_confirmation is True


def test_live_env_overrides(monkeypatch):
    monkeypatch.setenv("KALSHI_LIVE_READINESS_ENABLED", "true")
    monkeypatch.setenv("KALSHI_MAX_LIVE_ORDER_SIZE", "3")
    cfg = load_config(mode="paper")
    assert cfg.live_readiness.enabled is True and cfg.live_readiness.max_live_order_size == 3.0
    # enabling readiness must NOT enable submission
    assert cfg.live_readiness.live_submission_allowed is False


# --------------------------------------------------------------------------- #
# Credential preflight (no secret values)
# --------------------------------------------------------------------------- #
def test_credential_preflight_no_secret_values(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "SECRET_KEY_ID_VALUE")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/nonexistent/key.pem")
    cfg = load_config(mode="paper")
    cs = credential_status(cfg)
    assert cs["key_id_present"] is True and cs["private_key_path_present"] is True
    assert cs["private_key_file_exists"] is False  # path set but missing
    # the actual secret value must never appear anywhere in the status
    assert "SECRET_KEY_ID_VALUE" not in json.dumps(cs)
    # private reads disabled by default
    pr = kalshi_private_read_preflight(cfg, allow_private_read=True)
    assert pr["called_any_endpoint"] is False


# --------------------------------------------------------------------------- #
# Readiness state machine
# --------------------------------------------------------------------------- #
def test_readiness_default_blockers_and_no_submit(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for name in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_PRIVATE_KEY_PASSPHRASE"):
        monkeypatch.delenv(name, raising=False)
    r = assess_live_readiness(load_config(mode="paper", load_env=False))
    assert r["live_submission_allowed"] is False and r["dry_run_only"] is True
    codes = {b["code"] for b in r["blockers"]}
    for expected in ("LIVE_DISABLED", "KILL_SWITCH_ACTIVE", "MISSING_CREDENTIALS",
                     "MODEL_NOT_APPROVED", "CALIBRATOR_NOT_APPROVED", "BACKTEST_NOT_APPROVED",
                     "PAPER_EVIDENCE_MISSING", "RISK_BLOCKED", "MANUAL_CONFIRMATION_REQUIRED"):
        assert expected in codes
    assert r["state"] == "NOT_CONFIGURED"  # readiness scaffolding disabled by default


def test_readiness_enabled_headline_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_LIVE_READINESS_ENABLED", "true")
    r = assess_live_readiness(load_config(mode="paper"))
    assert r["state"] == "LIVE_DISABLED" and r["live_submission_allowed"] is False


def test_readiness_dry_run_ready_with_valid_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_LIVE_READINESS_ENABLED", "true")
    cfg = load_config(mode="paper")
    payload = build_dry_run_order_payload(config=cfg, ticker="KX-T", side="YES", quantity=1,
                                          limit_price=0.55, tif="fill_or_kill")
    r = assess_live_readiness(cfg, order_payload=payload)
    assert r["order_plan_status"] == "VALID"
    assert r["state"] == "DRY_RUN_READY"           # valid dry-run payload, but live still blocked
    assert r["live_submission_allowed"] is False


# --------------------------------------------------------------------------- #
# Dry-run order payload
# --------------------------------------------------------------------------- #
def test_dry_run_payload_valid_and_sanitized(monkeypatch):
    monkeypatch.setenv("KALSHI_KEY_ID", "SECRET_VALUE")
    cfg = load_config(mode="paper")
    p = build_dry_run_order_payload(config=cfg, ticker="KX-T", side="YES", quantity=1,
                                    limit_price=55, tif="fill_or_kill")   # price in cents
    assert p.valid is True and p.live_submission_allowed is False
    assert p.payload["yes_price"] == 55 and p.payload["type"] == "limit"
    assert p.payload["time_in_force"] == "fill_or_kill" and p.limit_price == 0.55
    assert "SECRET_VALUE" not in json.dumps(p.payload)   # no secrets in payload
    assert p.checksum and p.endpoint.endswith("/orders") and p.method == "POST"


def test_dry_run_payload_rejections():
    cfg = load_config(mode="paper")
    assert "MISSING_TICKER" in build_dry_run_order_payload(
        config=cfg, ticker=None, side="YES", quantity=1, limit_price=0.5, tif="fill_or_kill").blockers
    assert "INVALID_QUANTITY" in build_dry_run_order_payload(
        config=cfg, ticker="KX", side="YES", quantity=0, limit_price=0.5, tif="fill_or_kill").blockers
    assert "PRICE_OUT_OF_BOUNDS" in build_dry_run_order_payload(
        config=cfg, ticker="KX", side="YES", quantity=1, limit_price=1.5, tif="fill_or_kill",
        price_is_cents=False).blockers
    assert "MARKET_ORDER_NOT_ALLOWED" in build_dry_run_order_payload(
        config=cfg, ticker="KX", side="YES", quantity=1, limit_price=0.5, tif="market",
        order_type="market").blockers
    assert "TIF_REQUIRED_FOK_OR_IOC" in build_dry_run_order_payload(
        config=cfg, ticker="KX", side="YES", quantity=1, limit_price=0.5, tif="gtc").blockers


# --------------------------------------------------------------------------- #
# Live adapter hard refusal (no HTTP mutation)
# --------------------------------------------------------------------------- #
def test_live_adapter_submit_cancel_refuse_no_http(monkeypatch):
    import urllib.request
    called = {"n": 0}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    a = LiveKalshiExecutionAdapter(load_config(mode="paper"))
    s = a.submit()
    c = a.cancel()
    assert s["status"] == "rejected" and c["status"] == "rejected"
    assert s["live_submission_allowed"] is False and c["live_submission_allowed"] is False
    blockers = a.live_blockers()
    assert any("KILL_SWITCH" in b or "kill switch" in b for b in blockers)
    assert any("SUBMIT_ENABLED" in b for b in blockers)
    assert any("manual confirmation" in b for b in blockers)
    assert called["n"] == 0          # NO HTTP request issued at all


def test_no_confirmation_provider_never_confirms():
    from btc5m.venues.kalshi.live_readiness import ConfirmationRequired
    req = ConfirmationRequired(ticker="KX", side="YES", quantity=1, price=0.5,
                               expected_max_loss=0.5, model_version="m", reason_code="x",
                               timestamp_ms=0)
    assert NoConfirmationProvider().confirm(req) is False


# --------------------------------------------------------------------------- #
# Paper/live parity
# --------------------------------------------------------------------------- #
def test_parity_policy_and_lock_intents_convert():
    cfg = load_config(mode="paper")
    policy_intent = CandidateOrderIntent(
        ticker="KX-T", series="KXBTC15M", side="YES", action="buy", size=1, limit_price=0.42,
        time_in_force="fill_or_kill", post_only=False, max_acceptable_price=0.45,
        opposite_side_ask=0.60, expected_fee=0.02, expected_notional=0.42,
        market_close_ts_ms=1, as_of_ts_ms=0)
    lock_intent = LockOrderIntent(
        ticker="KX-T", side_to_buy="NO", quantity=1, limit_price=0.24, time_in_force="fill_or_kill",
        max_acceptable_price=0.28, expected_fee=0.02, expected_locked_profit=0.06)
    pp = payload_from_intent(policy_intent, cfg)
    lp = payload_from_intent(lock_intent, cfg)
    assert pp.valid and pp.side == "YES" and pp.payload["yes_price"] == 42
    assert lp.valid and lp.side == "NO" and lp.payload["no_price"] == 24
    assert pp.live_submission_allowed is False and lp.live_submission_allowed is False


def test_risk_status_included(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = assess_live_readiness(load_config(mode="paper"))
    assert "risk_status" in r and r["risk_status"]["approved"] is False
    assert any("kill switch" in s for s in r["risk_status"]["reasons"])


# --------------------------------------------------------------------------- #
# Audit logging (no secrets)
# --------------------------------------------------------------------------- #
def test_audit_log_written_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KALSHI_KEY_ID", "SECRET_VALUE")
    cfg = load_config(mode="paper")
    payload = build_dry_run_order_payload(config=cfg, ticker="KX-T", side="YES", quantity=1,
                                          limit_price=0.55, tif="fill_or_kill")
    r = assess_live_readiness(cfg, order_payload=payload)
    path = write_audit_log(cfg, r, ticker="KX-T", order_payload=payload)
    text = open(path, encoding="utf-8").read()
    assert "SECRET_VALUE" not in text                       # no secrets logged
    row = json.loads(text.splitlines()[0])
    assert row["dry_run"] is True and row["live_submission_allowed"] is False
    assert "LIVE_DISABLED" in row["blockers"] and row["order_payload_checksum"]


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_commands_registered_and_check_live_disabled():
    for c in ("kalshi-live-blockers", "kalshi-live-readiness", "kalshi-live-dry-run-order",
              "kalshi-private-read-preflight"):
        assert c in _COMMANDS
    assert not any("arb" in name.lower() for name in _COMMANDS)
    assert main(["check-live-disabled"]) == 0


def test_dry_run_order_cli_requires_ticker(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["kalshi-live-dry-run-order", "--series", "KXBTC15M"]) == 2   # usage error, no ticker
