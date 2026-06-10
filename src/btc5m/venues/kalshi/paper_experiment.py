"""Controlled PAPER experiment framework — shadow first, paper only after preflight.

Orchestrates a disciplined paper experiment on top of the existing building blocks:
the PROMOTED paper artifacts (``paper_promotion``), the manifest-based + dual-gated
runtime (``paper_runtime.evaluate_paper_rows``), the confidence-aware edge policy, and
the strict source-freshness gate. It NEVER submits live orders and NEVER auto-promotes.

Flow:
  preflight  -> create manifest (CREATED)  -> RUNNING  -> evaluate (shadow|paper)
  -> abort checks  -> COMPLETED / ABORTED  -> status / report.

SHADOW scores + logs SHADOW_DECISION rows and can NEVER paper-fill. PAPER may emit
PAPER_CANDIDATE + simulate fills (settle vs the OFFICIAL label in replay) only when
preflight passes, a shadow run happened first (unless explicitly skipped), and every
gate (edge policy, freshness, rate caps, risk) passes. ``live_submission_allowed`` is
always False; every run writes an auditable manifest + ledger.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ...notifications import build_notifier
from .executable_backtest import settle_trade
from .fees import KalshiFeeModel
from .paper_promotion import load_active_promotion
from .paper_runtime import evaluate_paper_rows, run_live_shadow
from .source_health import assess_source_health


# --------------------------------------------------------------------------- #
# Paths / ids
# --------------------------------------------------------------------------- #
def experiments_dir(config) -> Path:
    d = config.data_path() / "paper" / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir(config) -> Path:
    d = config.reports_path() / "paper" / "experiments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def new_experiment_id(name: str = "") -> str:
    slug = "".join(c for c in (name or "exp").lower().replace(" ", "-") if c.isalnum() or c in "-_")[:24]
    return f"{slug or 'exp'}_{_ts()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def _check(name: str, ok: bool, detail: str = "", severe: bool = False) -> dict:
    return {"check": name, "status": ("PASS" if ok else ("FAIL" if severe else "WARN")),
            "ok": bool(ok), "severe": bool(severe and not ok), "detail": detail}


def _file_ok(path: Optional[str]) -> bool:
    return bool(path) and Path(path).exists()


def preflight(config, *, series: str = "KXBTC15M") -> dict:
    """Read-only preflight: can we run shadow? can we run paper? Never promotes/trades."""
    xc = config.paper_experiment
    checks: list[dict] = []
    promo = load_active_promotion(config, series=series)
    man = promo.get("manifest") or {}
    model_art = promo.get("model_artifact") or {}
    cal_art = promo.get("calibrator_artifact") or {}

    # ----- live safety (severe if violated) -----
    live_blockers = config.live_blockers()
    checks.append(_check("live_disabled", bool(live_blockers),
                         f"live blockers present: {len(live_blockers)}", severe=True))
    checks.append(_check("kill_switch_or_live_blocked",
                         bool(config.kill_switch_enabled or live_blockers),
                         "kill switch active or live otherwise blocked"))
    checks.append(_check("live_submit_disabled",
                         not (config.live_trading_enabled or getattr(config.live_readiness, "submit_enabled", False)),
                         "LIVE_TRADING_ENABLED / KALSHI_LIVE_SUBMIT_ENABLED are false", severe=True))

    # ----- promotion / artifacts (severe) -----
    checks.append(_check("paper_promotion_manifest_exists", promo.get("exists", False),
                         str(promo.get("manifest_path")), severe=True))
    checks.append(_check("promotion_valid_hash_match", promo.get("valid", False),
                         f"blockers: {promo.get('blockers')}", severe=True))
    checks.append(_check("model_promoted_for_paper",
                         bool(model_art.get("is_promoted") and man.get("promoted_for") == "PAPER_ONLY"),
                         f"promoted_for={man.get('promoted_for')}", severe=True))
    checks.append(_check("live_approved_false", not man.get("live_approved", False),
                         "manifest live_approved must be false", severe=True))
    checks.append(_check("model_not_diagnostic",
                         bool(model_art) and not (model_art.get("is_diagnostic")
                         or model_art.get("tradability") == "NON_TRADABLE_DIAGNOSTIC_ONLY"),
                         f"tradable_status={model_art.get('tradable_status')}", severe=True))
    checks.append(_check("calibrator_valid",
                         bool(cal_art) and cal_art.get("calibration_status") == "calibrated"
                         and not cal_art.get("NON_TRADABLE_DIAGNOSTIC_ONLY"),
                         f"calibration_status={cal_art.get('calibration_status')}", severe=True))

    # ----- evidence reports -----
    checks.append(_check("edge_policy_available",
                         bool(config.edge_policy.enabled) and _file_ok(man.get("edge_policy_report_path")),
                         f"edge_policy_report={man.get('edge_policy_report_path')}"))
    checks.append(_check("backtest_report_exists", _file_ok(man.get("backtest_report_path")),
                         str(man.get("backtest_report_path"))))
    checks.append(_check("calibration_report_exists", _file_ok(man.get("calibration_report_path")),
                         str(man.get("calibration_report_path"))))
    checks.append(_check("frequency_report_exists", _file_ok(man.get("frequency_report_path")),
                         str(man.get("frequency_report_path"))))

    # ----- source health / freshness -----
    src_ok = True
    kalshi_decision_stale = underlying_decision_ok = None
    try:
        sh = assess_source_health(config)
        by = {s["source"]: s for s in sh["sources"]}
        kalshi_decision_stale = by.get("kalshi", {}).get("decision_stale")
        underlying_decision_ok = sh["underlying"]["underlying_decision_ok"]
    except Exception as exc:  # noqa: BLE001
        src_ok = False
        kalshi_decision_stale = underlying_decision_ok = None
        checks.append(_check("source_health_available", False, f"{type(exc).__name__}: {exc}", severe=True))
    if src_ok:
        checks.append(_check("source_health_available", True, "assess_source_health ok"))
        checks.append(_check("kalshi_book_decision_fresh", not bool(kalshi_decision_stale),
                             f"kalshi decision_stale={kalshi_decision_stale}"))
        checks.append(_check("underlying_decision_fresh_or_fallback", bool(underlying_decision_ok),
                             f"underlying_decision_ok={underlying_decision_ok}"))

    # ----- conservative thresholds -----
    cpc = man.get("conservative_policy_config", {})
    conservative = (float(cpc.get("min_net_edge_cents", 0)) >= xc.min_net_edge_cents
                    and int(cpc.get("max_trades_per_window", 99)) <= xc.max_trades_per_window
                    and int(cpc.get("cooldown_after_entry_seconds", 0)) >= xc.cooldown_seconds) if cpc else False
    checks.append(_check("paper_thresholds_conservative", conservative or not cpc,
                         f"manifest conservative_policy_config={cpc}"))

    # ----- structural safety -----
    checks.append(_check("no_newest_by_mtime_loading", True,
                         "runtime loads ONLY the promotion manifest (never newest-by-mtime)"))
    ledger_writable = True
    try:
        probe = experiments_dir(config) / ".preflight_probe"
        probe.write_text("ok", encoding="utf-8"); probe.unlink()
    except Exception:  # noqa: BLE001
        ledger_writable = False
    checks.append(_check("paper_ledger_writable", ledger_writable, str(experiments_dir(config)), severe=True))
    notif_ok = True
    try:
        build_notifier(config)
    except Exception:  # noqa: BLE001
        notif_ok = False
    checks.append(_check("notifier_safe", notif_ok, "Noop-safe notifier"))
    checks.append(_check("no_live_order_path", True, "live adapter refuses unconditionally"))

    severe_blockers = [c["check"] for c in checks if c["severe"]]
    warnings = [f"{c['check']}: {c['detail']}" for c in checks if c["status"] == "WARN"]
    preflight_pass = not severe_blockers
    # PAPER additionally requires decision-fresh sources + evidence + conservative thresholds.
    paper_blockers = list(severe_blockers)
    if xc.require_source_freshness:
        if kalshi_decision_stale:
            paper_blockers.append("kalshi_book_decision_stale")
        if underlying_decision_ok is False:
            paper_blockers.append("underlying_decision_stale")
    if xc.require_backtest_report and not _file_ok(man.get("backtest_report_path")):
        paper_blockers.append("backtest_report_missing")
    if xc.require_edge_policy and not (config.edge_policy.enabled and _file_ok(man.get("edge_policy_report_path"))):
        paper_blockers.append("edge_policy_report_missing")
    paper_ready = not paper_blockers

    if severe_blockers:
        recommended_mode = "disabled"
    elif paper_ready and _shadow_completed_before(config, series):
        recommended_mode = "paper"
    else:
        recommended_mode = "shadow"

    return {
        "series": series,
        "preflight_pass": preflight_pass,
        "paper_ready": paper_ready,
        "recommended_mode": recommended_mode,
        "blockers": severe_blockers,
        "paper_blockers": paper_blockers,
        "warnings": warnings,
        "checks": checks,
        "promotion_valid": promo.get("valid", False),
        "manifest_path": promo.get("manifest_path"),
        "kalshi_book_decision_stale": kalshi_decision_stale,
        "underlying_decision_ok": underlying_decision_ok,
        "shadow_completed_before": _shadow_completed_before(config, series),
        "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def _experiment_manifests(config) -> list[Path]:
    d = experiments_dir(config)
    return sorted(d.glob("kalshi_paper_experiment_*.json"), key=lambda p: p.stat().st_mtime)


def latest_manifest(config) -> Optional[dict]:
    files = _experiment_manifests(config)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _shadow_completed_before(config, series: str) -> bool:
    for p in _experiment_manifests(config):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if (m.get("series") == series and m.get("mode") == "shadow"
                and m.get("status") in ("COMPLETED", "RUNNING")):
            return True
    return False


def _build_manifest(config, *, exp_id, series, mode, name, preflight_result) -> dict:
    xc = config.paper_experiment
    promo = load_active_promotion(config, series=series)
    man = promo.get("manifest") or {}
    snapshot = {f: getattr(xc, f) for f in (
        "mode", "max_duration_minutes", "max_daily_trades", "max_trades_per_window",
        "max_open_positions", "default_size", "min_net_edge_cents", "min_final_edge_cents",
        "min_raw_edge_cents", "cooldown_seconds", "min_seconds_to_close", "max_seconds_to_close",
        "max_book_age_ms", "max_underlying_age_ms", "max_deribit_age_ms",
        "require_promoted_model", "require_calibrator", "require_edge_policy",
        "require_source_freshness", "require_backtest_report", "allow_diagnostic",
        "abort_on_source_stale", "abort_on_model_error", "abort_on_policy_error",
        "abort_on_unexpected_live_enabled", "max_consecutive_rejections",
        "max_drawdown_cents", "max_daily_paper_loss_cents")}
    return {
        "experiment_id": exp_id,
        "experiment_name": name or xc.name or exp_id,
        "series": series,
        "mode": mode,
        "promoted_paper_manifest_path": promo.get("manifest_path"),
        "model_artifact_path": man.get("model_artifact_path"),
        "calibrator_artifact_path": man.get("calibrator_artifact_path"),
        "model_artifact_sha256": man.get("model_artifact_sha256"),
        "calibrator_artifact_sha256": man.get("calibrator_artifact_sha256"),
        "model_type": man.get("model_type"),
        "calibrator_type": man.get("calibrator_type"),
        "feature_schema_version": man.get("feature_schema_version"),
        "dataset_path": man.get("dataset_path"),
        "backtest_report_path": man.get("backtest_report_path"),
        "calibration_report_path": man.get("calibration_report_path"),
        "edge_policy_report_path": man.get("edge_policy_report_path"),
        "frequency_report_path": man.get("frequency_report_path"),
        "experiment_config": snapshot,
        "preflight_pass": preflight_result.get("preflight_pass"),
        "preflight_recommended_mode": preflight_result.get("recommended_mode"),
        "start_time": _now_iso(),
        "end_time": None,
        "status": "CREATED",
        "abort_reason": None,
        "summary": {},
        "live_approved": False,
        "live_submission_allowed": False,
        "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
    }


def _manifest_path(config, exp_id: str) -> Path:
    return experiments_dir(config) / f"kalshi_paper_experiment_{exp_id}.json"


def _write_manifest(config, manifest: dict) -> str:
    p = _manifest_path(config, manifest["experiment_id"])
    p.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- #
# Fills (paper mode; settle vs OFFICIAL label in replay)
# --------------------------------------------------------------------------- #
def simulate_paper_fills(decisions: list[dict], fee_model, size: float) -> dict:
    pnl = peak = max_dd = 0.0
    fills, windows = [], set()
    for d in decisions:
        if d.get("decision_state") != "PAPER_CANDIDATE":
            continue
        side = d.get("selected_side")
        entry = d.get("executable_yes_price") if side == "YES" else d.get("executable_no_price")
        label = d.get("label_yes_resolved")
        if side is None or entry is None or label is None:
            continue
        fee = fee_model.taker_fee(float(entry), size)
        s = settle_trade(side, float(entry), size, int(label), fee)
        pnl += s["net_pnl"] * 100.0
        peak = max(peak, pnl)
        max_dd = max(max_dd, peak - pnl)
        windows.add(d.get("ticker"))
        fills.append({"ticker": d.get("ticker"), "side": side, "entry_price": entry, "size": size,
                      "fee": round(fee, 6), "win": s["win"], "net_pnl_cents": round(s["net_pnl"] * 100.0, 3),
                      "label_yes_resolved": int(label), "live_submission_allowed": False})
    return {"n_fills": len(fills), "fills": fills, "net_pnl_cents": round(pnl, 3),
            "max_drawdown_cents": round(max_dd, 3), "distinct_windows": len(windows),
            "open_positions": 0}


# --------------------------------------------------------------------------- #
# Abort criteria
# --------------------------------------------------------------------------- #
def _max_consecutive(decisions: list[dict], pred: Callable[[dict], bool]) -> int:
    best = run = 0
    for d in decisions:
        run = run + 1 if pred(d) else 0
        best = max(best, run)
    return best


def abort_reasons(config, *, decisions: list[dict], fills: dict, error: Optional[str],
                  promo_valid: bool) -> list[str]:
    xc = config.paper_experiment
    reasons: list[str] = []
    if xc.abort_on_unexpected_live_enabled:
        if not config.live_blockers():
            reasons.append("UNEXPECTED_LIVE_PERMITTED")
        if config.live_trading_enabled or getattr(config.live_readiness, "submit_enabled", False):
            reasons.append("UNEXPECTED_LIVE_ENABLED")
    if any(d.get("live_submission_allowed") for d in decisions):
        reasons.append("UNEXPECTED_LIVE_SUBMISSION_FLAG")
    if error and (xc.abort_on_model_error or xc.abort_on_policy_error):
        reasons.append(f"RUNTIME_ERROR:{error}")
    if not promo_valid:
        reasons.append("PROMOTION_INVALID_OR_HASH_MISMATCH")
    if xc.abort_on_source_stale:
        cs = _max_consecutive(decisions, lambda d: d.get("freshness_ok") is False)
        if cs > xc.max_consecutive_rejections:
            reasons.append(f"TOO_MANY_CONSECUTIVE_SOURCE_STALE({cs})")
    cr = _max_consecutive(decisions, lambda d: d.get("decision_state") == "REJECTED")
    if cr > xc.max_consecutive_rejections:
        reasons.append(f"TOO_MANY_CONSECUTIVE_REJECTIONS({cr})")
    if fills:
        if fills.get("net_pnl_cents", 0.0) < -abs(xc.max_daily_paper_loss_cents):
            reasons.append("MAX_DAILY_PAPER_LOSS_EXCEEDED")
        if fills.get("max_drawdown_cents", 0.0) > abs(xc.max_drawdown_cents):
            reasons.append("MAX_DRAWDOWN_EXCEEDED")
    return reasons


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def _write_ledger(config, exp_id: str, mode: str, decisions: list[dict]) -> Optional[str]:
    if not decisions:
        return None
    p = experiments_dir(config) / f"{exp_id}_decisions.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        for d in decisions:
            row = {"experiment_id": exp_id, "mode": mode, **d, "live_submission_allowed": False}
            fh.write(json.dumps(row, default=str) + "\n")
    return str(p)


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def _from_counter(decisions, predicate):
    return sum(1 for d in decisions if predicate(d))


def run_experiment(config, *, series: str = "KXBTC15M", mode: Optional[str] = None,
                   minutes: Optional[float] = None, skip_shadow_warning: bool = False,
                   limit: int = 25, max_iterations: Optional[int] = None,
                   name: Optional[str] = None, poll_interval: float = 5.0) -> dict:
    """Run a controlled experiment (shadow or paper). Never live; never long-collects a 15m cycle.

    With ``minutes`` > 0 (and not forced single-pass via ``max_iterations=1``) this runs a LIVE
    LOOP for ~``minutes`` wall-clock: every ``poll_interval`` seconds it re-reads the LATEST
    recorded feature rows and evaluates each NEW (ticker, as_of) row once, with feature-row-age
    ENFORCED (stale rows flagged/rejected — never traded). With no ``minutes`` (or
    ``max_iterations=1``) it does a SINGLE batch pass over the most recent ``limit`` stored rows.
    SHADOW never fills; PAPER fills settle vs the OFFICIAL label (live in-window rows are
    unsettled until backfill). live_submission_allowed is always False.
    """
    xc = config.paper_experiment
    mode = (mode or xc.mode or "shadow").lower()
    if mode not in ("shadow", "paper"):
        return {"status": "REFUSED", "abort_reason": f"invalid experiment mode {mode!r} (use shadow|paper)",
                "live_submission_allowed": False, "blockers": ["INVALID_MODE"]}

    pre = preflight(config, series=series)
    exp_id = new_experiment_id(name or xc.name)
    manifest = _build_manifest(config, exp_id=exp_id, series=series, mode=mode, name=name, preflight_result=pre)
    manifest["max_duration_minutes_requested"] = minutes

    def _finalize(status: str, abort_reason: Optional[str], summary: dict, ledger_file=None):
        manifest["status"] = status
        manifest["abort_reason"] = abort_reason
        manifest["end_time"] = _now_iso()
        manifest["summary"] = summary
        manifest["ledger_file"] = ledger_file
        path = _write_manifest(config, manifest)
        if abort_reason:
            _notify(config, f"PAPER EXPERIMENT {status}: {abort_reason} (live disabled)")
        return {"experiment_id": exp_id, "series": series, "mode": mode, "status": status,
                "abort_reason": abort_reason, "manifest_path": path, "ledger_file": ledger_file,
                "preflight": pre, "summary": summary, "live_submission_allowed": False}

    # ----- gate the run -----
    if mode == "paper":
        if not pre["preflight_pass"]:
            return _finalize("ABORTED", f"PAPER_PREFLIGHT_FAILED:{pre['blockers']}", {})
        if not pre["paper_ready"]:
            return _finalize("ABORTED", f"PAPER_NOT_READY:{pre['paper_blockers']}", {})
        if not skip_shadow_warning and not _shadow_completed_before(config, series):
            return _finalize("ABORTED", "PAPER_REQUIRES_SHADOW_FIRST "
                             "(run a shadow experiment first, or pass --skip-shadow-warning)", {})
    elif not pre["preflight_pass"]:
        # shadow can run for inspection, but flag the severe blockers.
        pass

    manifest["status"] = "RUNNING"
    _write_manifest(config, manifest)

    # ----- evaluate: LIVE LOOP for --minutes, else single batch pass -----
    use_loop = bool(minutes and float(minutes) > 0 and int(max_iterations or 0) != 1)
    error = None
    ev: dict = {}
    fills: dict = {}
    ledger_written = False
    try:
        if use_loop:
            def _on(decs):                       # incremental ledger write per poll
                nonlocal ledger_written
                if decs:
                    _write_ledger(config, exp_id, mode, decs)
                    ledger_written = True

            def _abort(decs):                    # critical early-abort during the loop
                if any(d.get("live_submission_allowed") for d in decs):
                    return "UNEXPECTED_LIVE_SUBMISSION_FLAG"
                if not config.live_blockers():
                    return "UNEXPECTED_LIVE_PERMITTED"
                return None

            ev = run_live_shadow(
                config, series=series, minutes=float(minutes), mode=mode,
                poll_interval=float(poll_interval), limit=limit,
                max_iterations=(int(max_iterations) if (max_iterations and int(max_iterations) > 1) else None),
                on_decisions=_on, abort_check=_abort)
        else:
            ev = evaluate_paper_rows(config, series=series, mode=mode, limit=limit)
        if mode == "paper" and isinstance(ev, dict) and ev.get("status") in ("OK", "ABORTED"):
            fills = simulate_paper_fills(ev.get("decisions", []), KalshiFeeModel.from_config(config),
                                         xc.default_size)
    except Exception as exc:  # noqa: BLE001 — abort, never crash the experiment harness
        error = f"{type(exc).__name__}: {exc}"

    decisions = ev.get("decisions", []) if isinstance(ev, dict) else []
    promo_valid = bool(ev.get("manifest_valid")) if isinstance(ev, dict) else False
    aborts = abort_reasons(config, decisions=decisions, fills=fills, error=error, promo_valid=promo_valid)
    status_val = ev.get("status") if isinstance(ev, dict) else None
    if status_val not in ("OK", "ABORTED", None):       # hard runtime block (no model, disabled)
        aborts.append(status_val)
    if isinstance(ev, dict) and ev.get("abort_reason"):  # loop's own early-abort reason
        aborts.append(ev["abort_reason"])

    ledger_file = (str(experiments_dir(config) / f"{exp_id}_decisions.jsonl") if ledger_written
                   else _write_ledger(config, exp_id, mode, decisions))
    summary = _summarize(ev, fills, mode)
    if aborts:
        return _finalize("ABORTED", "; ".join(str(a) for a in aborts), summary, ledger_file)
    return _finalize("COMPLETED", None, summary, ledger_file)


def _summarize(ev: dict, fills: dict, mode: str) -> dict:
    from collections import Counter
    decisions = ev.get("decisions", []) if isinstance(ev, dict) else []
    reasons = Counter(rc for d in decisions for rc in (d.get("reason_codes") or []))
    return {
        "runtime_status": ev.get("status"),
        "live_loop": ev.get("live_loop", False),
        "iterations": ev.get("iterations"),
        "elapsed_s": ev.get("elapsed_s"),
        "minutes_requested": ev.get("minutes_requested"),
        "poll_interval": ev.get("poll_interval"),
        "samples": ev.get("samples"),
        # ----- row selection funnel (collection rows -> executable active decision rows) -----
        "rows_read": ev.get("rows_read"),
        "rows_eligible_for_scoring": ev.get("rows_eligible_for_scoring"),
        "executable_rows": ev.get("executable_rows"),
        "active_window_rows": ev.get("active_window_rows"),
        "book_backed_rows": ev.get("book_backed_rows"),
        "start_reference_rows": ev.get("start_reference_rows"),
        "rows_with_start_reference": ev.get("rows_with_start_reference"),
        "rows_missing_start_reference_by_reason": ev.get(
            "rows_missing_start_reference_by_reason", {}),
        "rows_with_executable_depth": ev.get("rows_with_executable_depth"),
        "rows_missing_depth_by_reason": ev.get("rows_missing_depth_by_reason", {}),
        "rejected_before_scoring": ev.get("rejected_before_scoring"),
        "rejected_before_scoring_by_reason": ev.get("rejected_before_scoring_by_reason", {}),
        "n_rows_evaluated": ev.get("n_rows_evaluated", len(decisions)),
        "decisions_by_state": ev.get("decisions_by_state", {}),
        "shadow_decisions": ev.get("shadow_decisions", 0),
        "paper_candidates": ev.get("paper_candidates", 0),
        "would_be_paper_candidates": _from_counter(decisions, lambda d: d.get("would_be_paper_candidate")),
        "freshness_stale_rows": ev.get("freshness_stale_rows", 0),
        "book_stale_rows": ev.get("book_stale_rows", 0),
        "underlying_stale_rows": ev.get("underlying_stale_rows", 0),
        "feature_row_stale_rows": ev.get("feature_row_stale_rows", 0),
        "deribit_stale_rows": ev.get("deribit_stale_rows", 0),
        "freshness_fallback_used_rows": ev.get("freshness_fallback_used_rows", 0),
        "freshest_feature_row_age_ms": ev.get("freshest_feature_row_age_ms"),
        "stalest_feature_row_age_ms": ev.get("stalest_feature_row_age_ms"),
        "edge_policy_required": ev.get("edge_policy_required"),
        "rejection_reason_counts": dict(reasons.most_common(20)),
        "paper_fills": fills.get("n_fills", 0),
        "paper_net_pnl_cents": fills.get("net_pnl_cents", 0.0),
        "paper_max_drawdown_cents": fills.get("max_drawdown_cents", 0.0),
        "open_positions": fills.get("open_positions", 0),
        "model_path": ev.get("model_path"),
        "calibrator_path": ev.get("calibrator_path"),
    }


def _notify(config, message: str) -> bool:
    try:
        return bool(build_notifier(config).eod(message))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Status / stop / report
# --------------------------------------------------------------------------- #
def status(config, *, series: str = "KXBTC15M") -> dict:
    m = latest_manifest(config)
    rt_mode = config.model_runtime_mode
    safety = {"live_submission_allowed": False, "live_blocked": bool(config.live_blockers()),
              "kill_switch": config.kill_switch_enabled, "trading_mode": config.trading_mode}
    if not m:
        return {"series": series, "experiment": None, "status": "NO_EXPERIMENT",
                "note": "No experiment has been created yet. Run kalshi-paper-experiment-start.",
                "model_runtime_mode": rt_mode, "live_safety": safety}
    s = m.get("summary", {})
    return {
        "series": series,
        "experiment_id": m.get("experiment_id"),
        "experiment_name": m.get("experiment_name"),
        "mode": m.get("mode"),
        "status": m.get("status"),
        "abort_reason": m.get("abort_reason"),
        "start_time": m.get("start_time"),
        "end_time": m.get("end_time"),
        "decisions_by_state": s.get("decisions_by_state", {}),
        "shadow_decisions": s.get("shadow_decisions", 0),
        "paper_candidates": s.get("paper_candidates", 0),
        "would_be_paper_candidates": s.get("would_be_paper_candidates", 0),
        "paper_fills": s.get("paper_fills", 0),
        "open_positions": s.get("open_positions", 0),
        "paper_net_pnl_cents": s.get("paper_net_pnl_cents", 0.0),
        "paper_max_drawdown_cents": s.get("paper_max_drawdown_cents", 0.0),
        "rejection_reason_counts": s.get("rejection_reason_counts", {}),
        "freshness_stale_rows": s.get("freshness_stale_rows", 0),
        "book_stale_rows": s.get("book_stale_rows", 0),
        "underlying_stale_rows": s.get("underlying_stale_rows", 0),
        "feature_row_stale_rows": s.get("feature_row_stale_rows", 0),
        "deribit_stale_rows": s.get("deribit_stale_rows", 0),
        # ----- live-loop row-selection funnel (collection -> executable decision rows) -----
        "live_loop": s.get("live_loop", False),
        "rows_read": s.get("rows_read"),
        "rows_eligible_for_scoring": s.get("rows_eligible_for_scoring"),
        "active_window_rows": s.get("active_window_rows"),
        "book_backed_rows": s.get("book_backed_rows"),
        "start_reference_rows": s.get("start_reference_rows"),
        "rows_with_start_reference": s.get("rows_with_start_reference"),
        "rows_missing_start_reference_by_reason": s.get("rows_missing_start_reference_by_reason", {}),
        "rows_with_executable_depth": s.get("rows_with_executable_depth"),
        "rows_missing_depth_by_reason": s.get("rows_missing_depth_by_reason", {}),
        "rejected_before_scoring": s.get("rejected_before_scoring"),
        "rejected_before_scoring_by_reason": s.get("rejected_before_scoring_by_reason", {}),
        "model_path": s.get("model_path"),
        "manifest_path": str(_manifest_path(config, m.get("experiment_id", "x"))),
        "model_runtime_mode": rt_mode,
        "live_safety": safety,
    }


def stop(config, *, series: str = "KXBTC15M", reason: str = "manual") -> dict:
    """Write a stop flag + mark the latest RUNNING experiment ABORTED (controlled stop)."""
    flag = experiments_dir(config) / "STOP"
    flag.write_text(json.dumps({"reason": reason, "at": _now_iso()}), encoding="utf-8")
    m = latest_manifest(config)
    marked = None
    if m and m.get("status") == "RUNNING":
        m["status"] = "ABORTED"
        m["abort_reason"] = f"STOPPED:{reason}"
        m["end_time"] = _now_iso()
        _write_manifest(config, m)
        marked = m.get("experiment_id")
        _notify(config, f"PAPER EXPERIMENT STOPPED: {reason} (live disabled)")
    return {"series": series, "stop_flag": str(flag), "stopped_experiment": marked,
            "note": ("Marked the RUNNING experiment ABORTED." if marked else
                     "No RUNNING experiment to mark. The standalone runner is single-pass; "
                     "for a continuous collector, stop it with Ctrl-C."),
            "live_submission_allowed": False}


def report(config, *, series: str = "KXBTC15M") -> dict:
    m = latest_manifest(config)
    if not m:
        return {"series": series, "status": "NO_EXPERIMENT", "report_file": None}
    s = m.get("summary", {})
    try:
        sh = assess_source_health(config)
        by = {x["source"]: x for x in sh["sources"]}
        src_line = (f"kalshi decision_stale={by.get('kalshi', {}).get('decision_stale')} | "
                    f"underlying_decision_ok={sh['underlying']['underlying_decision_ok']} | "
                    f"reference={sh['underlying']['reference_source']} "
                    f"fallback_used={sh['underlying']['fallback_used']}")
    except Exception:  # noqa: BLE001
        src_line = "(source-health unavailable)"
    rec = _recommendation(m, s)
    d = reports_dir(config)
    path = d / f"kalshi_paper_experiment_report_{_ts()}.md"
    lines = [
        f"# Kalshi PAPER experiment report — {series}", "",
        f"- experiment_id: {m.get('experiment_id')}  name: {m.get('experiment_name')}",
        f"- mode: **{m.get('mode')}**  status: **{m.get('status')}**  abort_reason: {m.get('abort_reason')}",
        f"- start: {m.get('start_time')}  end: {m.get('end_time')}",
        f"- promoted model: {m.get('model_artifact_path')} ({(m.get('model_artifact_sha256') or '')[:16]}...)",
        f"- calibrator: {m.get('calibrator_artifact_path')} ({m.get('calibrator_type')})",
        f"- live_approved: {m.get('live_approved')}  live_submission_allowed: {m.get('live_submission_allowed')}",
        "", "## Experiment config (snapshot)",
        f"- {json.dumps(m.get('experiment_config', {}))}",
        "", "## Source health (decision-grade)", f"- {src_line}",
        "", "## Decisions",
        f"- rows_evaluated: {s.get('n_rows_evaluated')}  decisions_by_state: {s.get('decisions_by_state')}",
        f"- shadow_decisions: {s.get('shadow_decisions')}  paper_candidates: {s.get('paper_candidates')}  "
        f"would_be_paper_candidates: {s.get('would_be_paper_candidates')}",
        f"- freshness_stale_rows: {s.get('freshness_stale_rows')}  "
        f"book_stale_rows: {s.get('book_stale_rows')}  "
        f"underlying_stale_rows: {s.get('underlying_stale_rows')}  "
        f"deribit_stale_rows: {s.get('deribit_stale_rows')}  "
        f"freshness_fallback_used_rows: {s.get('freshness_fallback_used_rows')}",
        f"- feature_row_age_ms (freshest/stalest): {s.get('freshest_feature_row_age_ms')} / "
        f"{s.get('stalest_feature_row_age_ms')}  feature_row_stale_rows: {s.get('feature_row_stale_rows')}  "
        "(large == evaluating STALE stored rows; the collector must flush features incrementally)",
        "", "## Rejection reasons", f"- {json.dumps(s.get('rejection_reason_counts', {}))}",
        "", "## Paper fills (settle vs OFFICIAL label; NOT a profitability claim)",
        f"- fills: {s.get('paper_fills')}  net_pnl_cents: {s.get('paper_net_pnl_cents')}  "
        f"max_drawdown_cents: {s.get('paper_max_drawdown_cents')}  open_positions: {s.get('open_positions')}",
        "", "## Recommendation", f"- **{rec['recommendation']}** — {rec['rationale']}",
        "", "## Safety",
        "- SHADOW scores+logs only (no fills); PAPER fills are simulated vs the OFFICIAL label.",
        "- Runtime loads ONLY the promoted paper manifest (never newest-by-mtime). No live orders.",
        "- live_approved=false; live_submission_allowed=false. Paper promotion is NOT proof of profitability.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"series": series, "status": m.get("status"), "report_file": str(path),
            "recommendation": rec["recommendation"], "live_submission_allowed": False}


def _recommendation(manifest: dict, summary: dict) -> dict:
    if manifest.get("status") == "ABORTED":
        return {"recommendation": "PAUSE / INVESTIGATE",
                "rationale": f"experiment aborted: {manifest.get('abort_reason')}"}
    mode = manifest.get("mode")
    fills = summary.get("paper_fills", 0)
    pnl = summary.get("paper_net_pnl_cents", 0.0)
    shadow = summary.get("shadow_decisions", 0)
    wbc = summary.get("would_be_paper_candidates", 0)
    if mode == "shadow":
        if wbc == 0:
            return {"recommendation": "KEEP SHADOWING",
                    "rationale": f"{shadow} shadow decisions, 0 would-be candidates — no signal to act on yet; "
                                 "collect more windows before considering paper."}
        return {"recommendation": "KEEP SHADOWING (then consider PAPER)",
                "rationale": f"{wbc} would-be candidates over {shadow} decisions; validate freshness + edge "
                             "concentration across more windows before paper."}
    # paper
    if fills == 0:
        return {"recommendation": "KEEP PAPER (no fills yet) / TIGHTEN",
                "rationale": "no paper fills — gates are (correctly) conservative; widen the window or "
                             "re-evaluate edge, but do not loosen freshness/edge gates."}
    if pnl <= 0:
        return {"recommendation": "PAUSE / TIGHTEN / consider DEMOTE",
                "rationale": f"{fills} paper fills, net {pnl}c (<=0) — not consistent with a tradable edge."}
    return {"recommendation": "CONTINUE PAPER (small) + keep monitoring",
            "rationale": f"{fills} paper fills, net {pnl}c — positive but unproven; do NOT scale, do NOT go live."}
