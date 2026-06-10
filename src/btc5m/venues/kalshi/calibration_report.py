"""Calibration metrics + report/calibrate runners (held-out, purged/embargoed).

Fits the model on TRAIN windows, a calibrator on CALIB windows, and reports
before/after calibration on TEST windows — three disjoint time-ordered window sets
(:func:`splits.three_way_window_split`). Pure-stdlib metrics: Brier, log loss, ECE,
reliability buckets, calibration slope/intercept. Real calibration is gated; below
the gate it runs only with ``diagnostic_only`` and any saved calibrator is stamped
NON_TRADABLE_DIAGNOSTIC_ONLY. Never trades; never emits PAPER_CANDIDATE.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from ...models import pure_ml
from .calibrate import (
    Calibrator, build_calibrator_artifact, fit_calibrator, save_calibrator,
)
from .feature_schema import MICROSTRUCTURE_FEATURES, MODEL_SCHEMA_VERSION
from .model_dataset import build_model_dataset
from .splits import three_way_window_split
from .train_baselines import fit_predict_logistic


def reliability_table(y: list[int], p: list[float], n_buckets: int = 10) -> list[dict]:
    return pure_ml.probability_buckets(y, p, n_buckets=n_buckets)


def expected_calibration_error(y: list[int], p: list[float], n_buckets: int = 10) -> float | None:
    if not y:
        return None
    n = len(y)
    return sum((b["count"] / n) * abs(b["mean_pred"] - b["mean_actual"])
               for b in reliability_table(y, p, n_buckets))


def calibration_slope_intercept(y: list[int], p: list[float]):
    """OLS of realized outcome on predicted prob (diagnostic). slope=1,int=0 ideal."""
    n = len(p)
    if n < 2:
        return None, None
    mx = sum(p) / n
    my = sum(y) / n
    sxx = sum((pi - mx) ** 2 for pi in p)
    if sxx == 0:
        return None, my
    sxy = sum((pi - mx) * (yi - my) for pi, yi in zip(p, y))
    slope = sxy / sxx
    return slope, my - slope * mx


def calibration_summary(y: list[int], p: list[float]) -> dict:
    slope, intercept = calibration_slope_intercept(y, p)
    return {
        "n": len(y),
        "base_rate": (sum(y) / len(y)) if y else None,
        "mean_pred": (sum(p) / len(p)) if p else None,
        "brier": pure_ml.brier(y, p),
        "log_loss": pure_ml.log_loss(y, p),
        "ece": expected_calibration_error(y, p),
        "calibration_slope": slope,
        "calibration_intercept": intercept,
        "reliability": reliability_table(y, p),
    }


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _fit_eval(config, *, series: str, method: str, embargo_windows: int) -> dict:
    """Build dataset, 3-way split, fit model+calibrator, eval before/after on TEST."""
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    sp = three_way_window_split(rows, embargo_windows=embargo_windows)
    res = {"series": series, "method": method, "gate_windows": gate_windows,
           "n_rows": len(rows), "split": {k: sp.get(k) for k in (
               "applied", "reason", "n_windows", "train_windows", "calib_windows",
               "test_windows", "embargo_windows")},
           "applied": sp["applied"]}
    if not sp["applied"]:
        res["reason"] = sp["reason"]
        return res

    feats = MICROSTRUCTURE_FEATURES
    p_calib, model_dict, imp_dict = fit_predict_logistic(rows, feats, sp["train_idx"], sp["calib_idx"])
    p_test, _, _ = fit_predict_logistic(rows, feats, sp["train_idx"], sp["test_idx"])
    y_calib = [int(rows[i]["label_yes_resolved"]) for i in sp["calib_idx"]]
    y_test = [int(rows[i]["label_yes_resolved"]) for i in sp["test_idx"]]

    calibrator = fit_calibrator(method, p_calib, y_calib)
    p_test_cal = calibrator.transform(p_test)

    res.update(
        before=calibration_summary(y_test, p_test),
        after=calibration_summary(y_test, p_test_cal),
        calibrator=calibrator.to_dict(),
        split_metadata={**{k: sp.get(k) for k in (
            "train_windows", "calib_windows", "test_windows", "embargo_windows")},
            "gate_windows": gate_windows},
    )
    return res


def run_calibration_report(config, *, series: str = "KXBTC15M", method: str = "isotonic",
                           embargo_windows: int = 1) -> dict:
    """Compute + write a before/after calibration report (no artifact saved)."""
    bt = config.backtest
    res = _fit_eval(config, series=series, method=method, embargo_windows=embargo_windows)
    res["gate_min_windows"] = bt.calibration_min_windows
    res["gate_met"] = res["gate_windows"] >= bt.calibration_min_windows
    res["diagnostic"] = not res["gate_met"]
    if res.get("applied"):
        paths = _write_calibration_report(config, res)
        res["reports"] = paths
    return res


def _overfit_warning(method: str, calib_windows, n_calib_rows: int) -> dict:
    """Flag calibration overfitting risk (esp. isotonic on few calibration windows)."""
    cw = calib_windows or 0
    risk = "low"
    msgs = []
    if method == "isotonic" and cw < 60:
        risk = "high"
        msgs.append(f"isotonic on only {cw} calibration windows overfits badly (prior runs did); "
                    "prefer platt/sigmoid or grow calibration windows >= 60.")
    elif cw < 30:
        risk = "high"
        msgs.append(f"only {cw} calibration windows — calibration is unstable; results are diagnostic.")
    elif cw < 80:
        risk = "medium"
        msgs.append(f"{cw} calibration windows is modest; treat calibration as provisional.")
    if n_calib_rows < 200:
        msgs.append(f"only {n_calib_rows} calibration rows.")
    return {"overfit_risk": risk, "messages": msgs}


def run_calibrate_model(config, *, series: str = "KXBTC15M", method: str = "isotonic",
                        diagnostic_only: bool = False, embargo_windows: int = 1,
                        staged: bool = True, created_by_command: str = "kalshi-calibrate-model") -> dict:
    """Fit + (gated) SAVE a calibrator artifact. Below gate requires --diagnostic-only.

    ``staged=True`` (default) writes the calibrator to ``data/models/staged/`` so the
    runtime cannot auto-select it; promotion is a SEPARATE explicit step.
    """
    bt = config.backtest
    res = _fit_eval(config, series=series, method=method, embargo_windows=embargo_windows)
    res["gate_min_windows"] = bt.calibration_min_windows
    gate_met = res["gate_windows"] >= bt.calibration_min_windows
    res["gate_met"] = gate_met

    if not res.get("applied"):
        res["refused"] = True
        res["blockers"] = [res.get("reason", "insufficient windows for a 3-way split")]
        return res
    if not gate_met and not (diagnostic_only or bt.allow_diagnostic):
        res["refused"] = True
        res["blockers"] = [f"calibration gate {res['gate_windows']}/{bt.calibration_min_windows} "
                           "not met; pass --diagnostic-only for a NON-TRADABLE calibrator."]
        return res

    calib_windows = res["split"].get("calib_windows")
    res["overfit"] = _overfit_warning(method, calib_windows, res["after"].get("n", 0))
    tradable = bool(gate_met and not diagnostic_only)
    artifact = build_calibrator_artifact(
        calibrator=Calibrator.from_dict(res["calibrator"]), method=method,
        model_name="microstructure_logistic", split_metadata=res["split_metadata"],
        metrics_before={k: res["before"][k] for k in ("brier", "log_loss", "ece")},
        metrics_after={k: res["after"][k] for k in ("brier", "log_loss", "ece")},
        tradable=tradable, gate_windows=res["gate_windows"], is_staged=staged,
        created_by_command=created_by_command, series=series,
        calibration_window_count=calib_windows, test_window_count=res["split"].get("test_windows"),
        notes=("diagnostic-only (below gate)" if not tradable else "calibrated (uncalibrated->calibrated)"))
    paths = save_calibrator(config, artifact, staged=staged)
    res["artifact"] = {**paths, "tradability": artifact["tradability"],
                       "tradable_status": artifact["tradable_status"],
                       "NON_TRADABLE_DIAGNOSTIC_ONLY": artifact["NON_TRADABLE_DIAGNOSTIC_ONLY"]}
    res["diagnostic"] = not tradable
    res["staged"] = bool(staged)
    res["reports"] = _write_calibration_report(config, res)
    return res


def _write_calibration_report(config, res: dict) -> dict:
    d = config.reports_path() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_calibration_report_{stamp}.md"
    csv_path = d / f"kalshi_reliability_table_{stamp}.csv"
    json_path = d / f"kalshi_reliability_table_{stamp}.json"
    before, after = res.get("before", {}), res.get("after", {})
    diagnostic = res.get("diagnostic", True)
    lines = [
        f"# Kalshi calibration report — {res['series']}", "",
        f"- method: {res['method']}",
        f"- tradable: **{not diagnostic and res.get('gate_met')}**  diagnostic_only: {diagnostic}",
        f"- model_schema_version: {MODEL_SCHEMA_VERSION}",
        f"- gate_windows: {res['gate_windows']} / calibration gate {res.get('gate_min_windows')}",
        f"- split: train={res['split'].get('train_windows')} calib={res['split'].get('calib_windows')} "
        f"test={res['split'].get('test_windows')} embargo={res['split'].get('embargo_windows')} "
        "(windows; purged/embargoed; held-out TEST)",
        "", "## Calibration metrics (TEST windows; diagnostic — not a profitability claim)",
        "| metric | before (raw) | after (calibrated) |",
        "|---|---|---|",
        f"| n | {before.get('n')} | {after.get('n')} |",
        f"| brier | {_f(before.get('brier'))} | {_f(after.get('brier'))} |",
        f"| log_loss | {_f(before.get('log_loss'))} | {_f(after.get('log_loss'))} |",
        f"| ECE | {_f(before.get('ece'))} | {_f(after.get('ece'))} |",
        f"| slope | {_f(before.get('calibration_slope'))} | {_f(after.get('calibration_slope'))} |",
        f"| intercept | {_f(before.get('calibration_intercept'))} | {_f(after.get('calibration_intercept'))} |",
        "", "## Reliability buckets (after calibration)",
        "| bucket | count | mean_pred | mean_actual |", "|---|---|---|---|",
    ]
    for b in after.get("reliability", []):
        lines.append(f"| {b['bucket']} | {b['count']} | {_f(b['mean_pred'])} | {_f(b['mean_actual'])} |")
    ov = res.get("overfit")
    if ov:
        lines += ["", f"## Overfitting risk: **{ov['overfit_risk']}**"]
        for msg in ov.get("messages", []) or ["- (no specific overfit flags)"]:
            lines.append(f"- {msg}")
    lines += ["", "## Safety",
              f"- artifact staging: staged={res.get('staged')} "
              f"({res.get('artifact', {}).get('tradable_status', 'n/a')}); not promoted; runtime cannot auto-load.",
              "- Calibration fit on HELD-OUT windows (purged/embargoed); not on model-fit rows.",
              "- Diagnostic-only calibrators are NON_TRADABLE; no PAPER_CANDIDATE; live disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump({"before": before.get("reliability", []), "after": after.get("reliability", [])},
                  fh, indent=2)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["phase", "bucket", "count", "mean_pred", "mean_actual"])
        for phase, tbl in (("before", before.get("reliability", [])),
                           ("after", after.get("reliability", []))):
            for b in tbl:
                w.writerow([phase, b["bucket"], b["count"], b["mean_pred"], b["mean_actual"]])
    return {"report_md": str(md), "reliability_csv": str(csv_path), "reliability_json": str(json_path)}


def _f(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "None"
