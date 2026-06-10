"""Trade-frequency analysis runtime: build a leakage-safe eval set, run the
frequency frontier / marginal-trade / time-to-close / within-window analyses, and
write reports under reports/frequency/. READ-ONLY: never trades, never promotes a
policy, never enables live. Diagnostic-safe when no tradable calibrated model exists.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from typing import Optional

from .fees import KalshiFeeModel
from .model_dataset import build_model_dataset
from .splits import split_indices
from .trade_frequency import (
    FrequencyConfig, build_scenario_grid, calibration_buckets, extract_candidates,
    marginal_trade_curve, simulate_frequency_policy, time_to_close_analysis,
    within_window_analysis,
)

NON_TRADABLE = "NON_TRADABLE_DIAGNOSTIC_ONLY"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _freq_dir(config):
    d = config.reports_path() / "frequency"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_eval_set(config, *, series: str = "KXBTC15M", source: str = "auto",
                   embargo: int = 1, diagnostic_only: bool = False) -> dict:
    """Held-out eval rows with leakage-safe probabilities + a diagnostic stamp.

    Probability source: a TRADABLE calibrated model if present, else a microstructure
    logistic fit on train / predicted on val (diagnostic). Falls back to all rows when
    there are too few windows for a split (still diagnostic)."""
    from .calibrate import Calibrator, latest_calibrator_path, load_calibrator
    from .executable_backtest import _attach, latest_model_artifact_path
    from .model_artifacts import is_tradable, load_artifact
    from .threshold_sweep import _probs_for

    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    blockers: list[str] = []
    if not rows:
        return {"rows": [], "prob_source": None, "diagnostic": True, "tradable": False,
                "gate_windows": gate_windows, "input_source": "model_dataset",
                "blockers": ["no model dataset rows yet (run the collector / build-model-dataset)"]}
    train_idx, val_idx = split_indices(rows, embargo_windows=embargo)
    if not val_idx or not train_idx:
        val_idx = list(range(len(rows)))
        train_idx = val_idx
        blockers.append("too few windows for a held-out split; using all rows (diagnostic).")

    mp = latest_model_artifact_path(config)
    model_tradable = False
    if mp:
        try:
            model_tradable = is_tradable(load_artifact(mp))
        except Exception:  # noqa: BLE001
            model_tradable = False
    chosen = ("model" if (mp and model_tradable) else "microstructure") if source in ("auto", None) else source
    cal_obj = None
    if chosen == "model":
        cpath = latest_calibrator_path(config)
        if cpath:
            try:
                cal_obj = Calibrator.from_dict(load_calibrator(cpath).get("calibrator", {}))
            except Exception:  # noqa: BLE001
                cal_obj = None
    probs, src = _probs_for(config, rows, train_idx, val_idx, source=chosen, calibrator=cal_obj)
    eval_rows = _attach(rows, val_idx, probs, calibrator=cal_obj)
    diagnostic = bool(diagnostic_only or not model_tradable or src != "model")
    return {"rows": eval_rows, "prob_source": src, "diagnostic": diagnostic,
            "tradable": (not diagnostic), "gate_windows": gate_windows,
            "input_source": "model_dataset_held_out_val", "blockers": blockers}


def _head(out: dict, kind: str) -> dict:
    out.setdefault("module", "trade_frequency")
    out.setdefault("status", "OK")
    out["analysis"] = kind
    out["diagnostic"] = out.get("diagnostic", True)
    out["tradable"] = out.get("tradable", False)
    out["promoted"] = False
    out["live_submission_allowed"] = False
    if out.get("diagnostic"):
        out["stamp"] = NON_TRADABLE
    return out


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_frequency_sweep(config, *, series="KXBTC15M", source="auto", diagnostic_only=False,
                        max_scenarios: Optional[int] = None, embargo=1) -> dict:
    cfg = FrequencyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    out = {"series": series, "input_source": ev["input_source"], "prob_source": ev["prob_source"],
           "diagnostic": ev["diagnostic"], "tradable": ev["tradable"],
           "gate_windows": ev["gate_windows"], "blockers": list(ev["blockers"])}
    if not ev["rows"]:
        out["status"] = "BLOCKED"
        return _head(out, "frequency_sweep")
    cands = extract_candidates(ev["rows"], fee_model)
    out["candidate_count"] = len(cands)
    out["distinct_windows"] = len({c["ticker"] for c in cands})
    grid = build_scenario_grid(cfg, max_scenarios=max_scenarios)
    results = [simulate_frequency_policy(cands, sc, fee_model) for sc in grid]
    out["scenarios_evaluated"] = len(results)
    out["scenarios"] = [r.__dict__ for r in results]
    out["reports"] = _write_sweep_reports(config, out, results)
    return _head(out, "frequency_sweep")


def run_marginal_trade_curve(config, *, series="KXBTC15M", source="auto", diagnostic_only=False, embargo=1) -> dict:
    cfg = FrequencyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    out = {"series": series, "prob_source": ev["prob_source"], "diagnostic": ev["diagnostic"],
           "tradable": ev["tradable"], "gate_windows": ev["gate_windows"], "blockers": list(ev["blockers"])}
    if not ev["rows"]:
        out["status"] = "BLOCKED"
        return _head(out, "marginal_trade_curve")
    cands = extract_candidates(ev["rows"], fee_model)
    curve = marginal_trade_curve(cands, fee_model, top_ns=tuple(cfg.report_top_n))
    out["candidate_count"] = len(cands)
    out["curve"] = {"peak_cumulative_net_pnl": curve.peak_cumulative_net_pnl,
                    "peak_at_rank": curve.peak_at_rank, "total_candidates": curve.total_candidates,
                    "distinct_windows": curve.distinct_windows,
                    "buckets": [b.__dict__ for b in curve.buckets], "warnings": curve.warnings}
    out["reports"] = _write_marginal_reports(config, out, curve)
    return _head(out, "marginal_trade_curve")


def run_time_to_close_analysis(config, *, series="KXBTC15M", source="auto", diagnostic_only=False, embargo=1) -> dict:
    fee_model = KalshiFeeModel.from_config(config)
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    out = {"series": series, "prob_source": ev["prob_source"], "diagnostic": ev["diagnostic"],
           "tradable": ev["tradable"], "gate_windows": ev["gate_windows"], "blockers": list(ev["blockers"])}
    if not ev["rows"]:
        out["status"] = "BLOCKED"
        return _head(out, "time_to_close")
    buckets = time_to_close_analysis(ev["rows"], fee_model)
    out["buckets"] = [b.__dict__ for b in buckets]
    out["reports"] = _write_ttc_reports(config, out, buckets)
    return _head(out, "time_to_close")


def run_within_window_frequency(config, *, series="KXBTC15M", source="auto", diagnostic_only=False, embargo=1) -> dict:
    fee_model = KalshiFeeModel.from_config(config)
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    out = {"series": series, "prob_source": ev["prob_source"], "diagnostic": ev["diagnostic"],
           "tradable": ev["tradable"], "gate_windows": ev["gate_windows"], "blockers": list(ev["blockers"])}
    if not ev["rows"]:
        out["status"] = "BLOCKED"
        return _head(out, "within_window")
    cands = extract_candidates(ev["rows"], fee_model)
    out.update(within_window_analysis(cands, fee_model))
    return _head(out, "within_window")


def run_frequency_report(config, *, series="KXBTC15M", source="auto", diagnostic_only=False,
                         max_scenarios: Optional[int] = None, embargo=1) -> dict:
    """Combined human-readable report (Part I) + staged conservative paper-policy
    suggestion (promoted=false; manual review required)."""
    cfg = FrequencyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    out = {"series": series, "input_source": ev["input_source"], "prob_source": ev["prob_source"],
           "diagnostic": ev["diagnostic"], "tradable": ev["tradable"],
           "gate_windows": ev["gate_windows"], "blockers": list(ev["blockers"])}
    if not ev["rows"]:
        out["status"] = "BLOCKED"
        out["reports"] = _write_report_md(config, out, None, None, None, None, None)
        return _head(out, "frequency_report")
    cands = extract_candidates(ev["rows"], fee_model)
    grid = build_scenario_grid(cfg, max_scenarios=max_scenarios)
    scenarios = [simulate_frequency_policy(cands, sc, fee_model) for sc in grid]
    curve = marginal_trade_curve(cands, fee_model, top_ns=tuple(cfg.report_top_n))
    ttc = time_to_close_analysis(ev["rows"], fee_model)
    ww = within_window_analysis(cands, fee_model)
    cal = calibration_buckets(cands, fee_model)
    out["candidate_count"] = len(cands)
    out["distinct_windows"] = len({c["ticker"] for c in cands})
    suggestion = _conservative_suggestion(out, curve, ww)
    out["recommended_paper_policy_suggestion"] = suggestion
    out["reports"] = _write_report_md(config, out, scenarios, curve, ttc, ww, cal)
    out["reports"].update(_write_suggestion(config, suggestion))
    return _head(out, "frequency_report")


# --------------------------------------------------------------------------- #
# Conservative suggestion (NOT promoted; manual review required)
# --------------------------------------------------------------------------- #
def _conservative_suggestion(out: dict, curve, ww: dict) -> dict:
    evidence = []
    if curve and curve.peak_at_rank and curve.total_candidates:
        evidence.append(f"marginal net P&L peaked at rank {curve.peak_at_rank}/{curve.total_candidates}")
    for w in (ww.get("warnings") or []):
        evidence.append(w["message"])
    return {
        # Deliberately conservative defaults — NOT optimized by maximizing P&L.
        "min_net_edge_cents": 5, "max_trades_per_window": 1, "cooldown_after_entry_seconds": 30,
        "min_seconds_to_close": 30, "max_book_age_ms": 1000, "min_depth": 1,
        "max_spread_cents": 5, "max_daily_trades": 10,
        "rationale": ("Trade selectively: one entry per window (same-window trades are correlated), "
                      "a high net-edge floor, a post-entry cooldown, and a daily cap. Frequency must be "
                      "earned by marginal net edge, not maximized."),
        "evidence_summary": evidence or ["diagnostic eval set; limited windows"],
        "diagnostic_only": bool(out.get("diagnostic", True)),
        "requires_manual_review": True, "promoted": False, "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _safety_lines() -> list:
    return ["", "## Safety",
            "- RESEARCH EVIDENCE ONLY: no orders, no PAPER_CANDIDATE, no live trading.",
            "- No policy is promoted; recommendations require manual review + paper validation.",
            "- Distinct windows matter more than raw trade count (one label per 15m window).",
            "- Score constantly; trade only when marginal net edge (after fees/executable prices) is positive."]


def _write_sweep_reports(config, out: dict, results) -> dict:
    d = _freq_dir(config)
    stamp = _ts()
    csv_path = d / f"kalshi_frequency_frontier_{stamp}.csv"
    cols = ["scenario", "trades", "distinct_windows", "distinct_days", "trades_per_window",
            "raw_trades_per_day", "distinct_windows_per_day", "fraction_same_window",
            "net_pnl", "hit_rate", "avg_net_edge_cents", "realized_pnl_per_contract", "max_drawdown"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in results:
            w.writerow([getattr(r, c) for c in cols])
    md_path = d / f"kalshi_frequency_frontier_{stamp}.md"
    traded = [r for r in results if r.trades > 0]
    top = sorted(traded, key=lambda r: (r.net_pnl or 0), reverse=True)[:8]
    lines = [f"# Kalshi trade-frequency frontier — {out['series']}", "",
             f"- prob_source: {out['prob_source']}  diagnostic/NON_TRADABLE: **{out['diagnostic']}**",
             f"- gate_windows: {out['gate_windows']}  candidates: {out.get('candidate_count')}  "
             f"distinct_windows: {out.get('distinct_windows')}",
             f"- scenarios evaluated: {len(results)} (bounded; not a full grid)", "",
             "## ⚠️ Do NOT pick a policy by max in-sample net P&L (overfits). Evidence only.",
             "", "| scenario | trades | windows | trades/win | net_pnl | hit | wf=na |",
             "|---|---|---|---|---|---|---|"]
    for r in top:
        lines.append(f"| {r.scenario} | {r.trades} | {r.distinct_windows} | "
                     f"{_f(r.trades_per_window)} | {_f(r.net_pnl)} | {_f(r.hit_rate)} |  |")
    lines += _safety_lines()
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"frontier_csv": str(csv_path), "frontier_md": str(md_path)}


def _write_marginal_reports(config, out: dict, curve) -> dict:
    d = _freq_dir(config)
    stamp = _ts()
    csv_path = d / f"kalshi_marginal_trade_curve_{stamp}.csv"
    cols = ["label", "trades", "distinct_windows", "trades_per_window", "fraction_same_window",
            "cumulative_net_pnl", "incremental_net_pnl", "avg_net_edge_cents",
            "realized_pnl_per_contract", "hit_rate", "max_drawdown"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for b in curve.buckets:
            w.writerow([getattr(b, c) for c in cols])
    return {"marginal_curve_csv": str(csv_path)}


def _write_ttc_reports(config, out: dict, buckets) -> dict:
    d = _freq_dir(config)
    stamp = _ts()
    csv_path = d / f"kalshi_time_to_close_frequency_{stamp}.csv"
    cols = ["bucket", "candidates", "executed", "distinct_windows", "net_pnl", "hit_rate",
            "mean_net_edge_cents", "avg_fee", "book_invalid_rate", "source_stale_rate"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for b in buckets:
            w.writerow([getattr(b, c) for c in cols])
    return {"time_to_close_csv": str(csv_path)}


def _write_report_md(config, out, scenarios, curve, ttc, ww, cal) -> dict:
    d = _freq_dir(config)
    stamp = _ts()
    md = d / f"kalshi_frequency_frontier_{stamp}.md"
    lines = [f"# Kalshi trade-frequency report — {out['series']}", "",
             "**Score constantly; trade selectively. Frequency is earned from marginal net edge, "
             "not guessed. Distinct windows matter more than raw trade count.**", "",
             "## 1. Data / gate status",
             f"- prob_source: {out.get('prob_source')}  diagnostic/NON_TRADABLE: **{out.get('diagnostic')}**",
             f"- gate_windows: {out.get('gate_windows')}  input: {out.get('input_source')}"]
    for b in (out.get("blockers") or []):
        lines.append(f"  - blocker: {b}")
    if out.get("status") == "BLOCKED":
        lines += ["", "## BLOCKED", "- no eval rows; nothing to analyze yet."] + _safety_lines()
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"frequency_report_md": str(md)}
    lines += ["", "## 2. Candidate / trade counts",
              f"- candidates: {out.get('candidate_count')}  distinct_windows: {out.get('distinct_windows')}"]
    if curve:
        lines += ["", "## 3-4. Marginal trade curve",
                  f"- cumulative net P&L peaks at rank {curve.peak_at_rank}/{curve.total_candidates} "
                  f"(peak {curve.peak_cumulative_net_pnl}).",
                  "| bucket | trades | windows | cum_net_pnl | incr | hit |",
                  "|---|---|---|---|---|---|"]
        for b in curve.buckets:
            lines.append(f"| {b.label} | {b.trades} | {b.distinct_windows} | "
                         f"{_f(b.cumulative_net_pnl)} | {_f(b.incremental_net_pnl)} | {_f(b.hit_rate)} |")
        for w in curve.warnings:
            lines.append(f"- ⚠️ {w}")
    if ttc:
        lines += ["", "## 5. Time-to-close", "| bucket | cand | exec | windows | net_pnl | hit |",
                  "|---|---|---|---|---|---|"]
        for b in ttc:
            lines.append(f"| {b.bucket} | {b.candidates} | {b.executed} | {b.distinct_windows} | "
                         f"{_f(b.net_pnl)} | {_f(b.hit_rate)} |")
    if ww:
        lines += ["", "## 6-7. Within-window concentration / overtrading",
                  f"- eligible candidates: {ww.get('eligible_candidates')}  distinct_windows: {ww.get('distinct_windows')}"]
        for name, p in (ww.get("policies") or {}).items():
            lines.append(f"  - {name}: trades={p['trades']} windows={p['distinct_windows']} "
                         f"net_pnl={_f(p['net_pnl'])} hit={_f(p['hit_rate'])}")
        for w in (ww.get("warnings") or []):
            lines.append(f"- ⚠️ [{w['code']}] {w['message']}")
    if cal:
        lines += ["", "## (G) Frequency vs calibration", "| prob | cand | mean_p | realized_yes | gap | net_pnl |",
                  "|---|---|---|---|---|---|"]
        for b in cal:
            lines.append(f"| {b['prob_bucket']} | {b['candidates']} | {b['mean_predicted_p']} | "
                         f"{b['realized_yes_rate']} | {b['calibration_gap']} | {_f(b['net_pnl'])} |")
    sug = out.get("recommended_paper_policy_suggestion")
    if sug:
        lines += ["", "## 8. Conservative recommended paper-policy settings (NOT promoted)",
                  f"- {json.dumps({k: sug[k] for k in ('min_net_edge_cents', 'max_trades_per_window', 'cooldown_after_entry_seconds', 'min_seconds_to_close', 'max_book_age_ms', 'min_depth', 'max_spread_cents', 'max_daily_trades')})}",
                  f"- rationale: {sug['rationale']}",
                  "", "## 9. Aggressive settings (EXPERIMENTAL — paper validation required, not promoted)",
                  "- e.g. min_net_edge_cents=2, max_trades_per_window=2, cooldown=5s — test in paper only.",
                  "", "## 10. Explicit statement",
                  "- No settings are promoted. No live trading enabled. Recommendations require paper validation."]
    lines += _safety_lines()
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"frequency_report_md": str(md)}


def _write_suggestion(config, suggestion: dict) -> dict:
    d = _freq_dir(config)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"KALSHI_PAPER_POLICY_SUGGESTION_{day}.json"
    path.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
    return {"paper_policy_suggestion_json": str(path)}


def _f(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "None"
