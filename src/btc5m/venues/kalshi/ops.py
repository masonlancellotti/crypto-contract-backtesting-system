"""Unified, READ-ONLY operations/monitoring layer for the Kalshi pipeline.

Thin aggregators over the existing read-only building blocks (readiness, source
health, label audit, model/calibration/backtest validity, policy, lock, live
readiness, paper ledgers). Every function here is read-only: it never runs
collection, never submits/cancels orders, never prints secrets, and never weakens
a safety gate. Each returns a plain dict so it can be rendered as text / JSON /
markdown and written to ``reports/ops`` or ``reports/eod``.
"""

from __future__ import annotations

import importlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...timeutils import now_ms


# --------------------------------------------------------------------------- #
# Dependency check (optional ML/data deps; stdlib fallback always works)
# --------------------------------------------------------------------------- #
_OPTIONAL_DEPS = {
    "numpy": "fast numerics (training accel)",
    "pandas": "dataframes + parquet/dataset IO",
    "scikit-learn": "sklearn models + calibration (serious training path)",
    "scipy": "stats helpers (sklearn dependency)",
    "joblib": "model artifact (de)serialization for sklearn",
    "lightgbm": "LightGBM challenger model (optional)",
    "pyarrow": "parquet dataset output",
    "matplotlib": "calibration/reliability plots (optional)",
    "duckdb": "fast local querying of parquet/jsonl datasets",
    "websockets": "WebSocket streaming (low-latency)",
    "requests": "HTTP convenience (stdlib urllib used otherwise)",
    "cryptography": "Kalshi RSA-signed auth (live WS / private reads)",
    "yaml": "YAML config overlays (pyyaml)",
    "dotenv": "load .env (python-dotenv)",
}
_IMPORT_NAME = {"scikit-learn": "sklearn"}

# Commands that fall back to the pure-stdlib DIAGNOSTIC-ONLY path when the serious
# stack (numpy+pandas+scikit-learn) is missing.
_FALLBACK_COMMANDS = (
    "kalshi-train-baselines", "kalshi-train-model", "kalshi-calibrate-model",
    "kalshi-calibration-report", "kalshi-backtest-baselines", "kalshi-backtest-model",
)


def dependency_check(config=None) -> dict:
    """Report optional dependency availability + which features degrade. Never installs."""
    deps = {}
    for name, why in _OPTIONAL_DEPS.items():
        mod = _IMPORT_NAME.get(name, name)
        try:
            m = importlib.import_module(mod)
            deps[name] = {"installed": True, "version": getattr(m, "__version__", "?"), "purpose": why}
        except Exception:  # noqa: BLE001
            deps[name] = {"installed": False, "version": None, "purpose": why}

    def have(*names):
        return all(deps[n]["installed"] for n in names)

    serious_training_available = have("numpy", "pandas", "scikit-learn")
    features = {
        "numpy_accelerated_training": have("numpy"),
        "pandas_dataset_handling": have("pandas"),
        "sklearn_models": have("scikit-learn"),
        "sklearn_calibration": have("scikit-learn"),
        "parquet_dataset_output": have("pandas", "pyarrow"),
        "duckdb_querying": have("duckdb"),
        "lightgbm_challenger_model": have("lightgbm"),
        "calibration_plots": have("matplotlib"),
        "websocket_streaming": have("websockets"),
        "kalshi_rsa_signed_auth": have("cryptography"),
        "yaml_config_overlays": have("yaml"),
        "dotenv_loading": have("dotenv"),
    }
    missing_ml = [n for n in ("numpy", "pandas", "scikit-learn", "scipy", "joblib",
                              "pyarrow", "duckdb", "matplotlib", "lightgbm")
                  if not deps[n]["installed"]]
    # The pure-stdlib path is FORCED only when the serious stack is missing. With the
    # serious stack present, training uses sklearn and stdlib results are diagnostic.
    stdlib_fallback_active = not serious_training_available
    if serious_training_available:
        training_path = "sklearn (serious)"
    else:
        training_path = "pure_ml stdlib (DIAGNOSTIC-ONLY)"
    return {
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "dependencies": deps,
        "features": features,
        "serious_training_available": serious_training_available,
        "training_path": training_path,
        "stdlib_fallback_active": stdlib_fallback_active,
        "stdlib_fallback_note": ("pure-Python models (models/pure_ml.py) + JSONL/CSV dataset output "
                                 "are used ONLY when numpy/pandas/scikit-learn are absent; such results "
                                 "are stamped DIAGNOSTIC-ONLY and are never tradable"),
        "fallback_commands_when_missing": list(_FALLBACK_COMMANDS),
        "lightgbm_challenger": ("available" if deps["lightgbm"]["installed"]
                                else "UNAVAILABLE (optional challenger; install lightgbm to enable)"),
        "missing_ml_deps": missing_ml,
        "recommended_install": {
            "all": 'pip install -e ".[models,data,live,dev]"',
            "models": 'pip install -e ".[models]"   # numpy, pandas, scikit-learn, scipy, joblib, pyarrow, matplotlib, duckdb, lightgbm',
            "data": 'pip install -e ".[data]"     # websockets, requests, aiohttp, pyarrow, duckdb',
            "live": 'pip install -e ".[live]"     # cryptography, websockets, requests',
            "lightgbm": "pip install lightgbm",
            "parquet": "pip install pyarrow",
            "kalshi_auth": "pip install cryptography",
        },
        "warning": ("Serious ML stack present — training uses sklearn." if serious_training_available
                    else "SERIOUS TRAINING UNAVAILABLE: install numpy/pandas/scikit-learn (pip install -e \".[models]\"). "
                         "Stdlib fallback is DIAGNOSTIC-ONLY and never tradable. Missing optional deps never "
                         "break collection/readiness/safety."),
    }

_HOUR_MS = 3_600_000


# --------------------------------------------------------------------------- #
# Small file helpers
# --------------------------------------------------------------------------- #
def _latest_file(d: Path, pattern: str) -> Optional[Path]:
    if not d.exists():
        return None
    files = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _file_age_ms(path: Optional[Path]) -> Optional[int]:
    if not path or not path.exists():
        return None
    return int(now_ms() - path.stat().st_mtime * 1000)


def _iter_jsonl(path: Optional[Path]):
    if not path or not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return


def _count_lines(path: Optional[Path]) -> int:
    return sum(1 for _ in _iter_jsonl(path))


def _fmt_age(ms: Optional[int]) -> str:
    if ms is None:
        return "n/a"
    s = ms / 1000.0
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s/60:.0f}m"
    return f"{s/3600:.1f}h"


# --------------------------------------------------------------------------- #
# Collector status (freshness from files + source-health; never touches procs)
# --------------------------------------------------------------------------- #
def collector_status(config, *, stale_threshold_seconds: int = 120, record_history: bool = False) -> dict:
    from .source_health import assess_source_health
    sh = assess_source_health(config)
    by = {s["source"]: s for s in sh["sources"]}
    data = config.data_path()
    thr_ms = stale_threshold_seconds * 1000

    feats = _latest_file(data / "features", "kalshi_feature_rows*.jsonl")
    labels = _latest_file(data / "labels", "kalshi_settlement_labels-*.jsonl")
    feat_age = _file_age_ms(feats)
    label_age = _file_age_ms(labels)

    sources = {}
    for name in ("kalshi", "coinbase", "binance", "deribit"):
        s = by.get(name, {})
        sources[name] = {
            "enabled": s.get("enabled"), "rows_today": s.get("rows_today_normalized"),
            "age_ms": s.get("data_age_ms"), "age": _fmt_age(s.get("data_age_ms")),
            "stale": s.get("stale"),
            "latest_ts_ms": s.get("latest_normalized_ts_ms")}
    # Kalshi book + underlying drive "is the collector alive?"
    kalshi_stale = bool(by.get("kalshi", {}).get("stale"))
    underlying_ok = sh["underlying"]["underlying_ok"]
    feat_stale = bool(feat_age is not None and feat_age > max(thr_ms, 16 * 60_000))  # features batch ~ per cycle

    if kalshi_stale and not underlying_ok:
        verdict, rec = "STALLED", "collector may be stale — check the PowerShell collector window"
    elif kalshi_stale or not underlying_ok:
        verdict, rec = "DEGRADED", "one feed looks stale — check connectivity; restart at a natural 15m boundary if it persists"
    else:
        verdict, rec = "ACTIVE", "collector appears active"

    out = {
        "verdict": verdict, "recommendation": rec,
        "stale_threshold_seconds": stale_threshold_seconds,
        "sources": sources,
        "feature_file": (str(feats) if feats else None), "feature_age": _fmt_age(feat_age),
        "feature_age_ms": feat_age,
        "label_file": (str(labels) if labels else None), "label_age": _fmt_age(label_age),
        "underlying_ok": underlying_ok, "kalshi_stale": kalshi_stale,
        "assessed_at_ms": now_ms(),
    }
    # Optional history + capture-rate delta vs the previous snapshot.
    hist_path = data / "audit" / "kalshi_collector_status_history.jsonl"
    prev = None
    for row in _iter_jsonl(hist_path):
        prev = row
    try:
        gp = gate_progress(config)
        out["gate_windows"] = gp["gate_windows"]
        if prev is not None and prev.get("gate_windows") is not None:
            out["gate_windows_delta_since_last"] = gp["gate_windows"] - prev["gate_windows"]
    except Exception:  # noqa: BLE001
        out["gate_windows"] = None
    if record_history:
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        with hist_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts_ms": out["assessed_at_ms"], "verdict": verdict,
                                 "gate_windows": out.get("gate_windows"),
                                 "kalshi_stale": kalshi_stale, "underlying_ok": underlying_ok}) + "\n")
    return out


# --------------------------------------------------------------------------- #
# Gate progress (DISTINCT feature-backed official windows; orphans excluded)
# --------------------------------------------------------------------------- #
def gate_progress(config) -> dict:
    from .labels_audit import dedup_labels, load_label_rows
    from .readiness import (
        MIN_BACKTEST_WINDOWS, MIN_TRAIN_ROWS, MIN_TRAIN_WINDOWS, _event, _load_glob,
        feature_row_usable,
    )
    data = config.data_path()
    feats = [_event(r) for r in _load_glob(data / "features", "kalshi_feature_rows*.jsonl")]
    labels = dedup_labels(load_label_rows(config))
    official = {tk for tk, lr in labels.items()
                if lr.get("label_source_status") == "OFFICIAL" and lr.get("label_yes_resolved") is not None}

    feature_tickers, usable_tickers = set(), set()
    usable_rows = 0
    close_by_ticker: dict[str, int] = {}
    for r in feats:
        tk = r.get("market_ticker")
        if not tk:
            continue
        feature_tickers.add(tk)
        if feature_row_usable(r):
            usable_tickers.add(tk)
            if tk in official:
                usable_rows += 1
            cm = r.get("close_ms")
            if cm is not None:
                close_by_ticker[tk] = max(close_by_ticker.get(tk, 0), int(cm))

    gate_windows = len(official & usable_tickers)
    feature_backed = len(official & feature_tickers)
    orphans = len(official - feature_tickers)

    # Actual recent capture rate from gate-eligible windows' close times.
    now = now_ms()
    gate_tickers = official & usable_tickers
    def _recent(hrs):
        return sum(1 for tk in gate_tickers if (now - close_by_ticker.get(tk, 0)) <= hrs * _HOUR_MS
                   and close_by_ticker.get(tk, 0) > 0)
    c1, c3, c12 = _recent(1), _recent(3), _recent(12)
    rate_3h = (c3 / 3.0) if c3 else (c12 / 12.0 if c12 else 0.0)

    rem_backtest = max(0, MIN_BACKTEST_WINDOWS - gate_windows)
    rem_train = max(0, MIN_TRAIN_WINDOWS - gate_windows)
    eta_ideal_h = round(rem_backtest / 4.0, 1)   # ideal 4 windows/hour
    eta_actual_h = (round(rem_backtest / rate_3h, 1) if rate_3h > 0 else None)
    bottleneck = "windows" if gate_windows < MIN_TRAIN_WINDOWS else (
        "rows" if usable_rows < MIN_TRAIN_ROWS else "none")

    return {
        "gate_windows": gate_windows, "feature_backed_official_windows": feature_backed,
        "eligible_after_purge_embargo": gate_windows,  # 15m windows don't overlap
        "orphan_labels_excluded": orphans, "usable_rows": usable_rows,
        "backtest_gate_threshold": MIN_BACKTEST_WINDOWS, "train_gate_threshold": MIN_TRAIN_WINDOWS,
        "train_gate_min_rows": MIN_TRAIN_ROWS,
        "windows_remaining_backtest": rem_backtest, "windows_remaining_train": rem_train,
        "recent_windows_1h": c1, "recent_windows_3h": c3, "recent_windows_12h": c12,
        "capture_rate_per_hour": round(rate_3h, 2),
        "eta_backtest_hours_ideal_4ph": eta_ideal_h, "eta_backtest_hours_actual": eta_actual_h,
        "bottleneck": bottleneck,
        "backtest_allowed": gate_windows >= MIN_BACKTEST_WINDOWS,
        "train_allowed": gate_windows >= MIN_TRAIN_WINDOWS and usable_rows >= MIN_TRAIN_ROWS,
        "next_command": ("keep collecting (kalshi-collect-continuous); "
                         f"need {rem_backtest} more windows for backtest"
                         if rem_backtest else "backtest gate reached — run kalshi-backtest-baselines"),
    }


# --------------------------------------------------------------------------- #
# Model health
# --------------------------------------------------------------------------- #
def model_health(config) -> dict:
    from .policy_runtime import (
        _can_emit, assess_backtest_validity, assess_calibration_validity, assess_model_validity,
    )
    mv = assess_model_validity(config)
    cv = assess_calibration_validity(config)
    bv = assess_backtest_validity(config)
    d = config.data_path() / "models"
    artifacts = sorted([p.name for p in d.glob("kalshi_*.pkl")
                        if "calibrator" not in p.name]) if d.exists() else []
    calibrators = sorted([p.name for p in d.glob("kalshi_calibrator_*.pkl")]) if d.exists() else []
    can, blockers = _can_emit(mv, cv, bv, config.paper_policy)
    status = "MODEL_MISSING" if not mv.exists else (
        "NON_TRADABLE_DIAGNOSTIC_ONLY" if mv.diagnostic_only else "TRAINED")
    return {
        "status": status,
        "model_artifacts_found": len(artifacts), "latest_model": (artifacts[-1] if artifacts else None),
        "model_version": mv.version, "model_trained": mv.trained,
        "model_diagnostic_only": mv.diagnostic_only, "model_tradable_stamp": mv.tradable_stamp,
        "feature_schema_version": mv.feature_schema_version,
        "calibrators_found": len(calibrators), "calibration_exists": cv.exists,
        "calibration_valid": cv.valid, "calibration_diagnostic_only": cv.diagnostic_only,
        "backtest_exists": bv.exists, "backtest_valid": bv.valid, "backtest_windows": bv.windows,
        "policy_can_emit_paper_candidate": can,
        "blockers_to_paper_candidate": blockers,
        "next_steps": (["train + calibrate + backtest above gate (currently blocked)"] if blockers
                       else ["model approved-path clear; enable paper policy to emit candidates"]),
    }


# --------------------------------------------------------------------------- #
# Backtest summary
# --------------------------------------------------------------------------- #
def backtest_summary(config) -> dict:
    d = config.reports_path() / "backtests"
    comp = _latest_file(d, "kalshi_baseline_comparison_*.json")
    sweep = _latest_file(d, "kalshi_threshold_sweep_*.json")
    bt_md = _latest_file(d, "kalshi_executable_backtest_*.md")
    if not comp and not sweep and not bt_md:
        return {"status": "BACKTEST_MISSING",
                "next_command": "run kalshi-backtest-baselines --series KXBTC15M --diagnostic-only"}
    out = {"status": "OK", "baseline_comparison_file": (str(comp) if comp else None),
           "threshold_sweep_file": (str(sweep) if sweep else None),
           "executable_backtest_md": (str(bt_md) if bt_md else None)}
    if comp:
        try:
            j = json.loads(comp.read_text(encoding="utf-8"))
            meta = j.get("meta", {})
            out["diagnostic"] = meta.get("diagnostic")
            out["gate_met"] = meta.get("gate_met")
            out["gate_windows"] = meta.get("gate_windows")
            res = j.get("results", {})
            out["baselines"] = {
                name: {"trades": v.get("total_simulated_trades"), "net_pnl": v.get("net_pnl"),
                       "hit_rate": v.get("hit_rate")}
                for name, v in res.items() if isinstance(v, dict) and name != "no_trade"}
            out["usable_by_policy"] = bool(meta.get("gate_met") and not meta.get("diagnostic"))
        except Exception:  # noqa: BLE001
            out["parse_error"] = True
    if sweep:
        try:
            cfgs = json.loads(sweep.read_text(encoding="utf-8"))
            out["sweep_configs"] = len(cfgs)
            out["sweep_configs_with_trades"] = sum(1 for c in cfgs if (c.get("trades") or 0) > 0)
        except Exception:  # noqa: BLE001
            pass
    out["overfit_warning"] = "do not select a policy by max in-sample P&L; require paper validation"
    return out


# --------------------------------------------------------------------------- #
# Paper summary (collector ledger + policy ledger)
# --------------------------------------------------------------------------- #
def paper_summary(config, *, date: Optional[str] = None) -> dict:
    d = config.data_path() / "paper"
    day = date or datetime.now(timezone.utc).strftime("%Y%m%d")
    states = Counter()
    fills = Counter()
    pnl = 0.0
    pnl_by_side = Counter()
    reasons = Counter()
    n_rows = 0
    # Why-not-traded buckets (mutually exclusive, timing checked first).
    skipped_due_to_timing = 0
    rejected_due_to_book = 0
    rejected_due_to_model_uncalibrated = 0
    _timing_reasons = {"MARKET_NOT_OPEN", "MARKET_CLOSED", "OUTSIDE_DECISION_WINDOW", "WINDOW_CLOSED"}
    _book_reasons = {"EMPTY_OR_INCOMPLETE_BOOK", "INVALID_OR_INCOMPLETE_BOOK"}
    for stream in ("kalshi_paper_ledger", "kalshi_policy_paper_ledger"):
        path = d / f"{stream}-{day}.jsonl"
        for row in _iter_jsonl(path):
            n_rows += 1
            st = row.get("decision_state")
            if st:
                states[st] += 1
            fs = row.get("fill_status") or row.get("paper_fill_status")
            if fs:
                fills[fs] += 1
            p = row.get("paper_pnl") or row.get("paper_net_pnl")
            if isinstance(p, (int, float)):
                pnl += p
                if row.get("side") or row.get("selected_side"):
                    pnl_by_side[row.get("side") or row.get("selected_side")] += p
            for rc in (row.get("reason_codes") or []):
                reasons[rc] += 1
            # Categorize why this row did not trade (timing > book > model).
            _rcs = set(row.get("reason_codes") or [])
            if st == "SKIPPED" or (_rcs & _timing_reasons):
                skipped_due_to_timing += 1
            elif _rcs & _book_reasons:
                rejected_due_to_book += 1
            elif "UNCALIBRATED_MODEL" in _rcs:
                rejected_due_to_model_uncalibrated += 1
    # lock ledger
    lock_events = Counter()
    for row in _iter_jsonl(d / f"kalshi_lock_ledger-{day}.jsonl"):
        if row.get("event_type"):
            lock_events[row["event_type"]] += 1
    try:
        from .lock_runtime import load_open_paper_positions
        positions = load_open_paper_positions(config)
    except Exception:  # noqa: BLE001
        positions = []
    if n_rows == 0 and not positions:
        return {"status": "NO_PAPER_ACTIVITY", "date": day,
                "note": "no paper ledger rows yet (policy emits no candidates until a model is approved)"}
    return {
        "status": "OK", "date": day, "ledger_rows": n_rows,
        "decisions_by_state": dict(states), "fill_status_counts": dict(fills),
        "paper_pnl": round(pnl, 4), "pnl_by_side": {k: round(v, 4) for k, v in pnl_by_side.items()},
        "top_reason_codes": dict(reasons.most_common(6)),
        "skipped_due_to_timing": skipped_due_to_timing,
        "rejected_due_to_book": rejected_due_to_book,
        "rejected_due_to_model_uncalibrated": rejected_due_to_model_uncalibrated,
        "lock_events": dict(lock_events),
        "open_paper_positions": len(positions),
        "locked_pairs": sum(p.locked_pairs_quantity for p in positions),
        "naked_yes": sum(p.naked_yes_quantity for p in positions),
        "naked_no": sum(p.naked_no_quantity for p in positions),
    }


# --------------------------------------------------------------------------- #
# Lock summary
# --------------------------------------------------------------------------- #
def lock_summary(config) -> dict:
    try:
        from .lock_runtime import load_open_paper_positions
    except Exception:  # noqa: BLE001
        return {"status": "LOCK_MODULE_MISSING"}
    positions = load_open_paper_positions(config)
    d = config.data_path() / "paper"
    events = Counter()
    for p in (sorted(d.glob("kalshi_lock_ledger-*.jsonl")) if d.exists() else []):
        for row in _iter_jsonl(p):
            if row.get("event_type"):
                events[row["event_type"]] += 1
    return {
        "status": "OK", "open_positions": len(positions),
        "fully_locked": sum(1 for p in positions if p.naked_yes_quantity == 0 and p.naked_no_quantity == 0
                            and (p.yes_quantity > 0 or p.no_quantity > 0)),
        "naked_yes": sum(p.naked_yes_quantity for p in positions),
        "naked_no": sum(p.naked_no_quantity for p in positions),
        "lock_events": dict(events),
        "note": ("no open paper positions (lock module manages existing positions only)"
                 if not positions else "post-entry lock only; never a flat arb scanner"),
    }


# --------------------------------------------------------------------------- #
# Safety status
# --------------------------------------------------------------------------- #
def safety_status(config) -> dict:
    from ...execution.live_kalshi import LiveKalshiExecutionAdapter
    from .live_readiness import assess_live_readiness
    adapter = LiveKalshiExecutionAdapter(config)
    adapter_blockers = adapter.live_blockers()
    lr = assess_live_readiness(config)
    warnings = []
    if config.live_trading_enabled:
        warnings.append("LIVE_TRADING_ENABLED is true")
    if not config.kill_switch_enabled:
        warnings.append("KILL_SWITCH_ENABLED is false (kill switch OFF)")
    if getattr(config.live_readiness, "submit_enabled", False):
        warnings.append("KALSHI_LIVE_SUBMIT_ENABLED is true")
    if getattr(config.live_readiness, "allow_market_orders", False):
        warnings.append("KALSHI_ALLOW_MARKET_ORDERS is true")
    live_disabled = bool(adapter_blockers) and not warnings
    return {
        "headline": ("LIVE TRADING DISABLED" if live_disabled else "WARNING: DANGEROUS CONFIG"),
        "trading_mode": config.trading_mode,
        "live_trading_enabled": config.live_trading_enabled,
        "kill_switch_active": config.kill_switch_enabled,
        "require_manual_confirmation": config.require_manual_confirmation,
        "live_submit_enabled": getattr(config.live_readiness, "submit_enabled", False),
        "dry_run_only": getattr(config.live_readiness, "dry_run_only", True),
        "live_submission_allowed": False,
        "kalshi_auth_configured": config.kalshi.auth_configured,
        "live_adapter_refuses": bool(adapter_blockers),
        "adapter_blockers": adapter_blockers,
        "live_readiness_state": lr["state"],
        "risk_limits_set": config._risk_limits_set(),
        "dangerous_warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Unified ops status
# --------------------------------------------------------------------------- #
def ops_status(config, *, include_files=True, include_models=True, include_paper=True,
               include_live_readiness=True) -> dict:
    out = {
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "timezone": config.timezone,
        "trading_mode": config.trading_mode,
        "primary_venue": config.primary_venue,
        "polymarket_dormant": config.polymarket_dormant,
        "deribit_enabled": bool(getattr(config.deribit, "enabled", False)),
        "collector": collector_status(config),
        "gate": gate_progress(config),
        "safety": safety_status(config),
    }
    if include_models:
        out["model"] = model_health(config)
        out["backtest"] = backtest_summary(config)
    if include_paper:
        out["paper"] = paper_summary(config)
        out["lock"] = lock_summary(config)
    if include_live_readiness:
        lr = out["safety"]
        out["live_readiness_state"] = lr["live_readiness_state"]
    out["next_actions"] = _next_actions(out)
    return out


def _next_actions(snap: dict) -> list[str]:
    actions = []
    if snap["collector"]["verdict"] != "ACTIVE":
        actions.append("check the collector window — a feed looks stale")
    g = snap["gate"]
    if not g["backtest_allowed"]:
        actions.append(f"keep collecting: {g['windows_remaining_backtest']} more windows to the backtest gate")
    elif snap.get("model", {}).get("status") != "TRAINED":
        actions.append("train + calibrate + backtest a model (currently diagnostic/missing)")
    actions.append("safety: live disabled — keep it that way until evidence + a separate live-enable step")
    return actions[:3]


# --------------------------------------------------------------------------- #
# Doctor (fast pass/warn/fail)
# --------------------------------------------------------------------------- #
def doctor(config, *, run_tests: bool = False) -> dict:
    checks = []

    def chk(name, status, detail=""):
        checks.append({"check": name, "status": status, "detail": detail})

    chk("config_loaded", "PASS", f"mode={config.trading_mode} primary={config.primary_venue}")
    saf = safety_status(config)
    chk("live_disabled", "PASS" if saf["headline"] == "LIVE TRADING DISABLED" else "FAIL", saf["headline"])
    chk("kill_switch_active", "PASS" if config.kill_switch_enabled else "FAIL", "")
    data = config.data_path()
    for sub in ("raw", "normalized", "features", "labels"):
        chk(f"dir_{sub}", "PASS" if (data / sub).exists() else "WARN", str(data / sub))
    col = collector_status(config)
    chk("kalshi_fresh", "PASS" if not col["kalshi_stale"] else "WARN", col["sources"]["kalshi"]["age"])
    chk("underlying_fresh", "PASS" if col["underlying_ok"] else "WARN", "")
    chk("deribit_optional", "PASS",
        "enabled" if config.deribit.enabled else "disabled (optional)")
    try:
        from .labels_audit import audit_labels, load_feature_tickers, load_label_rows, load_usable_feature_tickers
        a = audit_labels(load_label_rows(config), load_feature_tickers(config), load_usable_feature_tickers(config))
        chk("label_audit", "PASS", f"gate_windows={a['gate_windows']} orphans_excluded={a['orphan_official_labels']}")
    except Exception as exc:  # noqa: BLE001
        chk("label_audit", "WARN", f"{type(exc).__name__}")
    g = gate_progress(config)
    chk("gate_progress", "PASS", f"{g['gate_windows']}/{g['backtest_gate_threshold']} backtest")
    mh = model_health(config)
    chk("model_health", "PASS" if mh["status"] == "TRAINED" else "WARN", mh["status"])
    chk("backtest_reports", "PASS" if backtest_summary(config)["status"] == "OK" else "WARN", "")
    chk("policy_can_emit", "WARN" if not mh["policy_can_emit_paper_candidate"] else "PASS",
        "PAPER_CANDIDATE blocked (expected until a model is approved)")
    chk("lock_module", "PASS", lock_summary(config)["status"])
    nt = config.notifications
    chk("notifications", "PASS", "pushover" if nt.pushover_configured else "noop (fallback)")
    if run_tests:
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(Path(__file__).resolve().parents[3]),
                               capture_output=True, text=True, timeout=300)
            chk("pytest", "PASS" if r.returncode == 0 else "FAIL", (r.stdout.strip().splitlines() or [""])[-1])
        except Exception as exc:  # noqa: BLE001
            chk("pytest", "WARN", f"could not run: {type(exc).__name__}")
    summary = Counter(c["status"] for c in checks)
    return {"checks": checks, "summary": dict(summary),
            "overall": ("FAIL" if summary.get("FAIL") else ("WARN" if summary.get("WARN") else "PASS"))}


# --------------------------------------------------------------------------- #
# EOD summary
# --------------------------------------------------------------------------- #
def eod_summary(config, *, date: Optional[str] = None, send_notification: bool = False) -> dict:
    g = gate_progress(config)
    col = collector_status(config)
    paper = paper_summary(config, date=date)
    saf = safety_status(config)
    mh = model_health(config)
    # short, safe notification line
    if paper.get("status") == "OK" and paper.get("ledger_rows"):
        fills = sum(v for k, v in paper.get("fill_status_counts", {}).items() if "fill" in k)
        msg = (f"BTC 15m EOD: {paper['ledger_rows']} signals | {fills} paper fills | "
               f"net ${paper['paper_pnl']:+.2f} paper | windows {g['gate_windows']}/{g['backtest_gate_threshold']} | "
               f"{'live disabled' if saf['headline']=='LIVE TRADING DISABLED' else 'CONFIG WARNING'}")
    else:
        msg = (f"BTC 15m EOD: windows {g['gate_windows']}/{g['backtest_gate_threshold']} backtest | "
               f"rows {g['usable_rows']} | paper 0 fills | "
               f"source {'ok' if col['underlying_ok'] and not col['kalshi_stale'] else 'check'} | "
               f"{'live disabled' if saf['headline']=='LIVE TRADING DISABLED' else 'CONFIG WARNING'}")
    notified = False
    if send_notification:
        try:
            from ...notifications import build_notifier
            notified = build_notifier(config).eod(msg)
        except Exception:  # noqa: BLE001
            notified = False
    return {"date": date or datetime.now(timezone.utc).strftime("%Y%m%d"),
            "notification_line": msg, "notified": notified,
            "gate": g, "collector": {"verdict": col["verdict"], "underlying_ok": col["underlying_ok"]},
            "paper": paper, "model_status": mh["status"], "safety_headline": saf["headline"],
            "next_actions": _next_actions(ops_status(config, include_models=True, include_paper=True))}


# --------------------------------------------------------------------------- #
# Report writing
# --------------------------------------------------------------------------- #
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def write_report(config, subdir: str, stem: str, data: dict, *, markdown: Optional[str] = None) -> dict:
    d = config.reports_path() / subdir
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    json_path = d / f"{stem}_{stamp}.json"
    json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    out = {"json": str(json_path)}
    if markdown is not None:
        md_path = d / f"{stem}_{stamp}.md"
        md_path.write_text(markdown, encoding="utf-8")
        out["markdown"] = str(md_path)
    return out
