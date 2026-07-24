"""Executable-backtest threshold sweep (RESEARCH ONLY; no policy auto-selection).

Computes held-out probabilities ONCE (leakage-safe: model fit on train, predicted on
val; calibrator optional), then re-runs the executable backtest across a grid of
gates (min net edge, max book/underlying age). Reports per-config economics + a
stability check across walk-forward folds. It deliberately does NOT pick a
production policy: maximizing in-sample P&L overfits — later paper validation is
required. No orders; diagnostic reports are NON_TRADABLE.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from .calibrate import Calibrator, latest_calibrator_path, load_calibrator
from .executable_backtest import (
    BacktestParams, _attach, latest_model_artifact_path, market_implied_probs,
    predict_from_artifact, simulate_backtest,
)
from .feature_schema import MICROSTRUCTURE_FEATURES, MODEL_SCHEMA_VERSION
from .fees import KalshiFeeModel
from .model_artifacts import load_artifact
from .model_dataset import build_model_dataset
from .splits import split_indices, walk_forward_indices

# Default sweep grid (the three primary executable gates).
GRID_MIN_NET_EDGE_CENTS = [1, 2, 3, 5, 7, 10]
GRID_MAX_BOOK_AGE_MS = [250, 500, 1000, 2000, 5000]
GRID_MAX_UNDERLYING_AGE_MS = [500, 1000, 2000, 5000]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _probs_for(config, rows, train_idx, eval_idx, *, source: str, calibrator):
    from .train_baselines import fit_predict_logistic
    if source == "model":
        mp = latest_model_artifact_path(config)
        if mp:
            return predict_from_artifact(load_artifact(mp), rows, eval_idx), mp
    if source == "market_implied":
        return market_implied_probs(rows, eval_idx), "market_implied"
    probs, _, _ = fit_predict_logistic(rows, MICROSTRUCTURE_FEATURES, train_idx, eval_idx)
    return probs, "microstructure"


def run_threshold_sweep(config, *, series: str = "KXBTC15M", model: str = "latest",
                        calibrator: str = "latest", diagnostic_only: bool = False,
                        embargo_windows: int = 1, source: str = "microstructure") -> dict:
    bt = config.backtest
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    gate_met = gate_windows >= bt.min_windows
    diagnostic = bool(diagnostic_only or bt.allow_diagnostic or not gate_met)
    report = {"series": series, "gate_windows": gate_windows, "gate_min_windows": bt.min_windows,
              "gate_met": gate_met, "diagnostic": diagnostic, "configs": [], "blockers": []}
    if not gate_met and not (diagnostic_only or bt.allow_diagnostic):
        report["refused"] = True
        report["blockers"].append(f"backtest gate {gate_windows}/{bt.min_windows} not met; "
                                  "pass --diagnostic-only for a NON-TRADABLE sweep.")
        return report

    train_idx, val_idx = split_indices(rows, embargo_windows=embargo_windows)
    if not val_idx or not train_idx:
        report["refused"] = True
        report["blockers"].append("not enough windows for a held-out train/val split.")
        return report

    cal_obj = None
    if calibrator not in ("none", "off", None):
        cpath = latest_calibrator_path(config) if calibrator in ("latest", "") else calibrator
        if cpath:
            try:
                cal_obj = Calibrator.from_dict(load_calibrator(cpath).get("calibrator", {}))
            except Exception:  # noqa: BLE001
                cal_obj = None

    fee_model = KalshiFeeModel.from_config(config)
    # Probabilities computed ONCE for the primary val split.
    probs, src = _probs_for(config, rows, train_idx, val_idx, source=source, calibrator=cal_obj)
    primary_rows = _attach(rows, val_idx, probs, calibrator=cal_obj)
    # Walk-forward fold rows (for stability) — probs fit per fold (leakage-safe).
    folds = []
    for (tr, vl) in walk_forward_indices(rows, n_splits=3, embargo_windows=embargo_windows):
        fp, _ = _probs_for(config, rows, tr, vl, source=source, calibrator=cal_obj)
        folds.append(_attach(rows, vl, fp, calibrator=cal_obj))
    report["prob_source"] = src

    for mne in GRID_MIN_NET_EDGE_CENTS:
        for mba in GRID_MAX_BOOK_AGE_MS:
            for mua in GRID_MAX_UNDERLYING_AGE_MS:
                params = BacktestParams.from_config(
                    config, min_net_edge_cents=mne, max_book_age_ms=mba, max_underlying_age_ms=mua)
                agg = simulate_backtest(primary_rows, params=params, fee_model=fee_model,
                                        diagnostic=diagnostic, model_version=src)
                fold_pnls = [simulate_backtest(fr, params=params, fee_model=fee_model,
                                               diagnostic=diagnostic)["net_pnl"] for fr in folds]
                n_tr = agg["total_simulated_trades"]
                cand = agg["total_candidate_rows"]
                report["configs"].append({
                    "min_net_edge_cents": mne, "max_book_age_ms": mba, "max_underlying_age_ms": mua,
                    "trades": n_tr, "windows_touched": agg["windows_touched"],
                    "net_pnl": agg["net_pnl"], "mean_pnl_per_trade": (agg["net_pnl"] / n_tr) if n_tr else None,
                    "max_drawdown": agg["max_drawdown"], "hit_rate": agg["hit_rate"],
                    "avg_net_edge": agg["avg_net_edge"],
                    "reject_rate": (1.0 - n_tr / cand) if cand else None,
                    "side_mix": {k: v["trades"] for k, v in agg["pnl_by_side"].items()},
                    "walk_forward_net_pnl": fold_pnls,
                    "walk_forward_pnl_spread": (max(fold_pnls) - min(fold_pnls)) if fold_pnls else None,
                })
    report["reports"] = _write_sweep(config, report)
    return report


def _write_sweep(config, report: dict) -> dict:
    d = config.reports_path() / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    csv_path = d / f"kalshi_threshold_sweep_{stamp}.csv"
    json_path = d / f"kalshi_threshold_sweep_{stamp}.json"
    md_path = d / f"kalshi_threshold_sweep_{stamp}.md"
    cols = ["min_net_edge_cents", "max_book_age_ms", "max_underlying_age_ms", "trades",
            "windows_touched", "net_pnl", "mean_pnl_per_trade", "max_drawdown", "hit_rate",
            "avg_net_edge", "reject_rate", "walk_forward_pnl_spread"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for c in report["configs"]:
            w.writerow([c.get(k) for k in cols])
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(report["configs"], fh, indent=2, default=str)
    # md: show a few configs but DO NOT recommend one
    traded = [c for c in report["configs"] if (c["trades"] or 0) > 0]
    by_pnl = sorted(traded, key=lambda c: (c["net_pnl"] or 0), reverse=True)[:5]
    lines = [f"# Kalshi threshold sweep ({report['series']})", "",
             f"- gate_windows: {report['gate_windows']} / {report['gate_min_windows']} (met={report['gate_met']})",
             f"- diagnostic / NON_TRADABLE: **{report['diagnostic']}**",
             f"- prob_source: {report.get('prob_source')}  model_schema_version: {MODEL_SCHEMA_VERSION}",
             f"- configs_evaluated: {len(report['configs'])}  configs_with_trades: {len(traded)}",
             "", "## ⚠️ Overfitting warning",
             "- These are IN-SAMPLE held-out metrics over limited windows. Do NOT choose a",
             "  production policy by maximizing net P&L here. Use walk-forward spread as a",
             "  stability check and require later paper validation. EVIDENCE only; no orders.",
             "", "## Highest-net-PnL configs (NOT a recommendation)",
             "| min_edge_c | max_book_ms | max_und_ms | trades | net_pnl | hit | wf_spread |",
             "|---|---|---|---|---|---|---|"]
    for c in by_pnl:
        lines.append(f"| {c['min_net_edge_cents']} | {c['max_book_age_ms']} | {c['max_underlying_age_ms']} "
                     f"| {c['trades']} | {c['net_pnl']} | {_f(c['hit_rate'])} | {_f(c['walk_forward_pnl_spread'])} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sweep_csv": str(csv_path), "sweep_json": str(json_path), "sweep_md": str(md_path)}


def _f(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "None"
