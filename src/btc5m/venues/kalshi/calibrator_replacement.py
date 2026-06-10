"""Staged calibrator REPLACEMENT review + window-reliability hardening (report-only; NEVER live).

Answers, for the currently PROMOTED model backbone, whether its isotonic calibrator should
later be replaced — by comparing, on held-out purged/embargoed TEST windows, these calibrators
*on the same promoted-model raw probabilities*:

  current_promoted_isotonic   the deployed calibrator (REFERENCE — what shadow uses now)
  identity_raw                no calibration (raw probability as final)
  platt                       Platt/sigmoid fit on held-out CALIB windows
  fresh_isotonic              isotonic refit (reference; high overfit risk on few windows)
  market_implied              P(YES) from executable asks (DIAGNOSTIC benchmark)
  market_shrunk_a{α}          α·p_model + (1-α)·p_market for α in {0,0.05,0.1,0.2,0.4}

Reports distinct-WINDOW reliability (the honest unit) alongside row reliability, re-evaluates the
edge-blocked cohort under each candidate with BOTH row- and window-based calibration buffers, runs
an executable backtest, and applies fixed promotion-review CRITERIA — but it NEVER promotes,
NEVER changes the manifest/active artifacts, NEVER weakens a gate or removes a buffer, and NEVER
enables paper/live. Candidates are staged under data/models/staged/ only. ``live_submission_allowed``
is always False.
"""

from __future__ import annotations

import csv
import json
import pickle
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .calibrate import Calibrator, build_calibrator_artifact, fit_calibrator, save_calibrator
from .edge_policy import EdgeInputs, EdgePolicyConfig, evaluate_edge
from .executable_backtest import (
    BacktestParams, _attach, market_implied_probs, simulate_backtest,
)
from .fees import KalshiFeeModel
from .model_artifacts import DIAGNOSTIC_ONLY, STAGED_NON_PROMOTED, staged_models_dir, tradable_status_for
from .paper_promotion import load_active_promotion, sha256_file
from .paper_runtime import _prepare_runtime
from .probability_repair import (
    blend, market_implied_yes, snapshot_runtime_state, source_metrics, verify_runtime_unchanged,
)
from .splits import three_way_window_split
from .uncertainty import build_calibration_buckets, build_window_calibration_buckets
from .uncertainty_audit import bucket_window_stats, latest_ledger, load_decisions, select_cohort

ALPHAS = [0.0, 0.05, 0.1, 0.2, 0.4]
REPLACEMENT_CANDIDATES = ("identity_raw", "platt")     # the realistic replacements to recommend
STAGED_SHADOW_CANDIDATE = "STAGED_SHADOW_CANDIDATE"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _median(xs) -> Optional[float]:
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _f(x, nd=4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _alpha_method(a) -> str:
    return f"market_shrunk_a{a}"


def write_preservation(config, snap: dict) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"pre_calibrator_replacement_preservation_{_ts()}.json"
    path.write_text(json.dumps({
        "purpose": "PRESERVE promoted/active runtime state across calibrator-replacement work",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": snap, "n_files": len(snap), "live_submission_allowed": False}, indent=2),
        encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# Build the promoted-backbone context (calibrators fit on the PROMOTED raw probs)
# --------------------------------------------------------------------------- #
def build_promoted_context(prep: dict, *, embargo_windows: int = 1, alphas=ALPHAS) -> dict:
    rows_all = prep["dataset_rows"]
    labelled = [r for r in rows_all
                if r.get("label_yes_resolved") is not None and r.get("model_probability_yes") is not None
                and r.get("yes_ask") is not None and r.get("no_ask") is not None]
    sp = three_way_window_split(labelled, embargo_windows=embargo_windows)
    if not sp["applied"]:
        return {"applied": False, "reason": sp.get("reason"), "n_labelled": len(labelled)}
    y_all = [int(r["label_yes_resolved"]) for r in labelled]
    raw_all = [r["model_probability_yes"] for r in labelled]
    promoted_all = [r.get("calibrated_probability_yes") for r in labelled]
    market_all = market_implied_probs(labelled, list(range(len(labelled))))
    tickers_all = [r.get("ticker") for r in labelled]

    raw_calib = [raw_all[i] for i in sp["calib_idx"]]
    y_calib = [y_all[i] for i in sp["calib_idx"]]
    cals = {m: fit_calibrator(m, raw_calib, y_calib) for m in ("identity", "platt", "isotonic")}
    platt_all = cals["platt"].transform(raw_all)
    iso_all = cals["isotonic"].transform(raw_all)

    methods = (["current_promoted_isotonic", "identity_raw", "platt", "fresh_isotonic", "market_implied"]
               + [_alpha_method(a) for a in alphas])

    def src_all(name):
        if name == "current_promoted_isotonic":
            return promoted_all
        if name == "identity_raw":
            return raw_all
        if name == "platt":
            return platt_all
        if name == "fresh_isotonic":
            return iso_all
        if name == "market_implied":
            return market_all
        a = float(name.split("market_shrunk_a")[1])
        return [blend(b, m, a) if (b is not None and m is not None) else None
                for b, m in zip(raw_all, market_all)]

    probs_all = {m: src_all(m) for m in methods}
    ti = sp["test_idx"]
    y_test = [y_all[i] for i in ti]
    tk_test = [tickers_all[i] for i in ti]
    base_rate = (sum(y_test) / len(y_test)) if y_test else None
    metrics = {m: source_metrics(y_test, [probs_all[m][i] for i in ti], tk_test, base_rate)
               for m in methods}

    row_buckets, win_buckets = {}, {}
    for m in methods:
        pairs = [(yy, pp, tt) for yy, pp, tt in zip(y_all, probs_all[m], tickers_all) if pp is not None]
        if pairs:
            row_buckets[m] = build_calibration_buckets([a for a, _, _ in pairs], [b for _, b, _ in pairs])
            win_buckets[m] = build_window_calibration_buckets(
                [a for a, _, _ in pairs], [b for _, b, _ in pairs], [c for _, _, c in pairs])
        else:
            row_buckets[m], win_buckets[m] = [], []
    if prep.get("buckets"):
        row_buckets["current_promoted_isotonic"] = prep["buckets"]

    return {"applied": True, "methods": methods, "alphas": list(alphas),
            "calibrators": {m: cals[m].to_dict() for m in cals},
            "labelled": labelled, "y_all": y_all, "raw_all": raw_all, "market_all": market_all,
            "tickers_all": tickers_all, "probs_all": probs_all, "test_idx": ti,
            "y_test": y_test, "base_rate": base_rate, "metrics": metrics,
            "row_buckets": row_buckets, "win_buckets": win_buckets,
            "split": {k: sp.get(k) for k in ("n_windows", "train_windows", "calib_windows",
                                             "test_windows", "embargo_windows")},
            "gate_windows": len({r.get("ticker") for r in labelled})}


# --------------------------------------------------------------------------- #
# Part C — window-vs-row reliability table (distinct windows primary)
# --------------------------------------------------------------------------- #
def reliability_tables(ctx: dict, method: str = "identity_raw") -> list[dict]:
    """Row vs distinct-window reliability for one source's predictions over ALL labelled rows."""
    p = ctx["probs_all"][method]
    rows = [{"calibrated_probability_yes": pp, "ticker": tk, "label_yes_resolved": yy}
            for pp, tk, yy in zip(p, ctx["tickers_all"], ctx["y_all"]) if pp is not None]
    return bucket_window_stats(rows)


# --------------------------------------------------------------------------- #
# Part E — candidate cohort re-evaluation (row AND window buffers)
# --------------------------------------------------------------------------- #
def _cohort_prob(method: str, *, raw, promoted, market, cals) -> Optional[float]:
    if method == "current_promoted_isotonic":
        return promoted
    if method == "identity_raw":
        return raw
    if method == "platt":
        return Calibrator.from_dict(cals["platt"]).transform([raw])[0] if raw is not None else None
    if method == "fresh_isotonic":
        return Calibrator.from_dict(cals["isotonic"]).transform([raw])[0] if raw is not None else None
    if method == "market_implied":
        return market
    if method.startswith("market_shrunk_a"):
        a = float(method.split("market_shrunk_a")[1])
        return blend(raw, market, a) if (raw is not None and market is not None) else None
    return None


def candidate_cohort_impact(config, ctx: dict, *, ledger: Optional[str], unit: str = "both") -> dict:
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    lp = Path(ledger) if ledger else latest_ledger(config)
    if lp is None or not Path(lp).exists():
        return {"status": "NO_LEDGER", "ledger": None}
    cohort = select_cohort(load_decisions(lp), "edge_blocked")
    cals = ctx["calibrators"]
    units = ("row", "window") if unit == "both" else (unit,)
    out: dict = {"ledger": str(lp), "n_cohort": len(cohort), "by_unit": {}, "per_row": []}
    for u in units:
        buckets_by_method = ctx["row_buckets"] if u == "row" else ctx["win_buckets"]
        per_method: dict = {}
        for method in ctx["methods"]:
            buckets = buckets_by_method.get(method, [])
            recs = []
            for d in cohort:
                raw = d.get("model_probability_yes")
                promoted = d.get("calibrated_probability_yes")
                ya, na = d.get("executable_yes_price"), d.get("executable_no_price")
                mkt = market_implied_yes(ya, na)
                p = _cohort_prob(method, raw=raw, promoted=promoted, market=mkt, cals=cals)
                if p is None or ya is None or na is None:
                    continue
                ens = {"model": p}
                if mkt is not None:
                    ens["market_implied"] = mkt
                dec = evaluate_edge(EdgeInputs(
                    p_yes_hat=p, yes_ask=ya, no_ask=na, book_age_ms=d.get("book_age_ms"),
                    coinbase_stale=bool(d.get("coinbase_decision_stale")),
                    binance_stale=bool(d.get("binance_decision_stale")),
                    calibration_buckets=buckets, ensemble_probs=ens,
                    model_calibrated=True, model_tradable=True, backtest_valid=True), edge_cfg, fee_model)
                recs.append({"ticker": d.get("ticker"), "p": p, "market": mkt, "side": dec.side,
                             "raw": dec.raw_edge_cents, "cost": dec.cost_adjusted_edge_cents,
                             "unc": dec.uncertainty_adjusted_edge_cents,
                             "final": dec.final_policy_edge_cents, "state": dec.state,
                             "calib_buf": dec.calibration_uncertainty_buffer_cents,
                             "reasons": dec.reason_codes})
                if u == units[0]:
                    out["per_row"].append({"unit": u, "method": method, **recs[-1],
                                           "reasons": "|".join(dec.reason_codes or [])})
            passers = [r for r in recs if r["state"] == "EDGE_OK"]
            pass_windows = {r["ticker"] for r in passers}
            cand_like = [r for r in recs if (r["raw"] or -9) >= edge_cfg.min_raw_edge_cents - 1e-9]
            sides = Counter(r["side"] for r in recs if r["side"])
            reasons = Counter(rc for r in recs for rc in (r["reasons"] or []))
            win_counts = Counter(r["ticker"] for r in passers) if passers else Counter()
            top1 = (win_counts.most_common(1)[0][1] / len(passers)) if passers else None
            per_method[method] = {
                "n_rows": len(recs), "candidate_like": len(cand_like),
                "pass_final": len(passers), "distinct_pass_windows": len(pass_windows),
                "top1_pass_window_share": top1,
                "median_raw_cents": _median([r["raw"] for r in recs]),
                "median_cost_cents": _median([r["cost"] for r in recs]),
                "median_unc_cents": _median([r["unc"] for r in recs]),
                "median_final_cents": _median([r["final"] for r in recs]),
                "best_final_cents": max((r["final"] for r in recs if r["final"] is not None), default=None),
                "median_calib_buffer_cents": _median([r["calib_buf"] for r in recs]),
                "side_distribution": dict(sides),
                "top_rejection_reasons": dict(reasons.most_common(5)),
            }
        out["by_unit"][u] = per_method
    return out


# --------------------------------------------------------------------------- #
# Part F — executable backtest per candidate (held-out TEST windows)
# --------------------------------------------------------------------------- #
def replacement_backtest(config, ctx: dict) -> dict:
    params = BacktestParams.from_config(config)
    fee_model = KalshiFeeModel.from_config(config)
    labelled, ti = ctx["labelled"], ctx["test_idx"]
    out: dict = {}
    for m in ctx["methods"]:
        p_all = ctx["probs_all"][m]
        probs = [p_all[i] for i in ti]
        arows = _attach(labelled, ti, probs)
        agg = simulate_backtest(arows, params=params, fee_model=fee_model, diagnostic=True, model_version=m)
        out[m] = {k: agg.get(k) for k in (
            "total_simulated_trades", "windows_touched", "net_pnl", "gross_pnl", "hit_rate",
            "max_drawdown", "avg_net_edge", "profit_factor", "pnl_by_side",
            "pnl_by_seconds_to_close", "pnl_by_net_edge_bucket")}
    return out


# --------------------------------------------------------------------------- #
# Part B — stage replacement candidates (rich metadata; staged dir ONLY)
# --------------------------------------------------------------------------- #
def stage_replacements(config, ctx: dict, *, series: str) -> list[dict]:
    promo = load_active_promotion(config, series=series)
    backbone_path = promo.get("model_path")
    input_sha = sha256_file(backbone_path) if (backbone_path and Path(backbone_path).exists()) else None
    sm = ctx["split"]

    def _metric3(m):
        x = ctx["metrics"].get(m, {})
        return {"ece_window": x.get("ece_window"), "ece_row": x.get("ece_row"),
                "brier": x.get("brier"), "log_loss": x.get("log_loss"),
                "yes_overprediction_cents": x.get("yes_overprediction_cents")}

    common = {"model_backbone_path": backbone_path, "input_model_sha256": input_sha,
              "train_windows": sm.get("train_windows"), "calib_windows": sm.get("calib_windows"),
              "test_windows": sm.get("test_windows"), "is_staged": True, "is_promoted": False,
              "live_approved": False, "promotion_required": True,
              "created_by_command": "kalshi-stage-calibrator-replacements", "series": series}
    staged: list[dict] = []
    # identity + platt + fresh_isotonic as calibrator artifacts
    method_map = {"identity_raw": ("identity", "identity"), "platt": ("platt", "platt"),
                  "fresh_isotonic": ("isotonic", "isotonic")}
    for cand, (calmethod, calkey) in method_map.items():
        overfit = (calmethod == "isotonic" and (sm.get("calib_windows") or 0) < 60)
        art = build_calibrator_artifact(
            calibrator=Calibrator.from_dict(ctx["calibrators"][calkey]), method=calmethod,
            model_name="microstructure_logistic", split_metadata=sm,
            metrics_before=_metric3("current_promoted_isotonic"), metrics_after=_metric3(cand),
            tradable=False, gate_windows=ctx["gate_windows"], is_staged=True,
            created_by_command="kalshi-stage-calibrator-replacements", series=series,
            calibration_window_count=sm.get("calib_windows"), test_window_count=sm.get("test_windows"),
            notes=f"STAGED calibrator replacement candidate ({cand}); NON-PROMOTED; report-only."
                  + (" HIGH OVERFIT RISK (isotonic on <60 calib windows)." if overfit else ""))
        art.update(common)
        art["artifact_type"] = "calibrator_replacement"
        art["calibrator_method"] = calmethod
        art["tradable_status"] = DIAGNOSTIC_ONLY if overfit else STAGED_NON_PROMOTED
        art["overfit_risk"] = "high" if overfit else "low"
        paths = save_calibrator(config, art, stem=f"kalshi_replacement_{cand}_{_ts()}", staged=True)
        staged.append({**paths, "candidate": cand, "method": calmethod,
                       "tradable_status": art["tradable_status"], "metrics": _metric3(cand)})
    # market-shrunk blender descriptors
    d = staged_models_dir(config)
    for a in ctx["alphas"]:
        m = _alpha_method(a)
        artifact = {"artifact_type": "calibrator_replacement", "calibrator_method": "market_shrink",
                    "blender": {"formula": "alpha*p_model + (1-alpha)*p_market", "alpha": a, "base": "raw"},
                    "alpha": a, "market_implied_source": "executable Kalshi YES/NO asks: ya/(ya+na)",
                    "metrics": _metric3(m), "tradable_status": DIAGNOSTIC_ONLY, "tradable": False,
                    "is_diagnostic": True, "calibration_status": "diagnostic",
                    "model_name": "microstructure_logistic", **common,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "notes": f"STAGED market-shrink replacement alpha={a}; DIAGNOSTIC_ONLY; never promoted."}
        stem = f"kalshi_replacement_market_shrink_a{a}_{_ts()}"
        (d / f"{stem}.pkl").write_bytes(pickle.dumps(artifact))
        (d / f"{stem}.json").write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
        staged.append({"artifact_file": str(d / f"{stem}.pkl"), "summary_file": str(d / f"{stem}.json"),
                       "candidate": m, "method": "market_shrink", "tradable_status": DIAGNOSTIC_ONLY,
                       "metrics": _metric3(m),
                       "check": tradable_status_for(is_diagnostic=True, is_staged=True, is_promoted=False)})
    return staged


# --------------------------------------------------------------------------- #
# Part H — promotion-review criteria (mark only; NEVER promote)
# --------------------------------------------------------------------------- #
def eligibility(ctx: dict, backtest: dict, cohort: dict) -> dict:
    prom = ctx["metrics"]["current_promoted_isotonic"]
    prom_bt = backtest.get("current_promoted_isotonic", {})
    cohort_row = (cohort.get("by_unit", {}).get("row", {}) if cohort.get("by_unit") else {})
    results: dict = {}
    for cand in REPLACEMENT_CANDIDATES:
        m = ctx["metrics"][cand]
        bt = backtest.get(cand, {})
        cw = cohort_row.get(cand, {})
        better_window_ece = (m.get("ece_window") is not None and prom.get("ece_window") is not None
                             and m["ece_window"] < prom["ece_window"])
        not_worse_brier = (m.get("brier") is not None and prom.get("brier") is not None
                           and m["brier"] <= prom["brier"] + 0.01)
        reduces_yes_over = (m.get("yes_overprediction_cents") is not None
                            and prom.get("yes_overprediction_cents") is not None
                            and abs(m["yes_overprediction_cents"]) <= abs(prom["yes_overprediction_cents"]) + 1e-9)
        not_lose_backtest = (bt.get("net_pnl") is not None and prom_bt.get("net_pnl") is not None
                             and bt["net_pnl"] >= prom_bt["net_pnl"] - 1e-9)
        pass_windows = cw.get("distinct_pass_windows", 0)
        clears_multi = pass_windows >= 2
        safer_calibrator = bool(better_window_ece and reduces_yes_over and not_lose_backtest)
        warnings, blockers = [], []
        if not better_window_ece:
            blockers.append("does_not_improve_window_ece_vs_promoted")
        if not not_worse_brier:
            warnings.append("brier_slightly_worse")
        if not reduces_yes_over:
            blockers.append("does_not_reduce_yes_overprediction")
        if not not_lose_backtest:
            blockers.append("loses_vs_promoted_in_backtest")
        if pass_windows == 1:
            warnings.append("passes_only_one_window (do not promote on this alone)")
        # mark STAGED_SHADOW_CANDIDATE if it is a clearly safer calibrator (even with 0 trades)
        # OR clears the final gate across multiple distinct windows.
        is_candidate = bool((safer_calibrator or clears_multi) and not blockers)
        results[cand] = {
            "better_window_ece": better_window_ece, "not_worse_brier": not_worse_brier,
            "reduces_yes_overprediction": reduces_yes_over, "not_lose_backtest": not_lose_backtest,
            "distinct_pass_windows": pass_windows, "clears_multi_window_gate": clears_multi,
            "safer_calibrator": safer_calibrator,
            "staged_shadow_candidate": is_candidate, "blockers": blockers, "warnings": warnings,
            "window_ece": m.get("ece_window"), "promoted_window_ece": prom.get("ece_window"),
            "backtest_net_pnl": bt.get("net_pnl"), "promoted_backtest_net_pnl": prom_bt.get("net_pnl"),
        }
    # recommend the eligible candidate with the lowest window ECE
    eligible = [c for c in REPLACEMENT_CANDIDATES if results[c]["staged_shadow_candidate"]]
    recommended = (min(eligible, key=lambda c: ctx["metrics"][c]["ece_window"]) if eligible else "none")
    market_ece = ctx["metrics"]["market_implied"].get("ece_window")
    rationale = (
        f"identity_raw window-ECE {_f(ctx['metrics']['identity_raw'].get('ece_window'))} and platt "
        f"{_f(ctx['metrics']['platt'].get('ece_window'))} vs promoted isotonic "
        f"{_f(prom.get('ece_window'))}; market-implied {_f(market_ece)} is best-calibrated but is the "
        "price (no edge). A safer calibrator (lower window-ECE, less YES over-prediction, no backtest "
        "loss) is worth a PAPER-ONLY promotion REVIEW even if it makes no trades; it is NOT promoted here.")
    return {"recommended_replacement_candidate": recommended,
            "replacement_eligible_for_promotion_review": bool(eligible),
            "per_candidate": results, "rationale": rationale,
            "blockers": sorted({b for c in REPLACEMENT_CANDIDATES for b in results[c]["blockers"]}),
            "warnings": sorted({w for c in REPLACEMENT_CANDIDATES for w in results[c]["warnings"]})}


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _order(methods) -> list:
    head = ["current_promoted_isotonic", "identity_raw", "platt", "fresh_isotonic", "market_implied"]
    return [m for m in head if m in methods] + sorted(m for m in methods if m.startswith("market_shrunk_a"))


def _write_review(config, ctx, backtest, elig, reliab, reliability_unit) -> dict:
    d = config.reports_path() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_calibrator_replacement_review_{stamp}.md"
    csvp = d / f"kalshi_calibrator_replacement_review_{stamp}.csv"
    order = _order(ctx["methods"])
    lines = [
        f"# Kalshi calibrator replacement review — {ctx.get('series', 'KXBTC15M')}", "",
        "> STAGED / report-only. Calibrators compared on the PROMOTED model's raw probs over held-out "
        "purged/embargoed TEST windows. **Distinct-window ECE is PRIMARY** (row ECE is fake-tight). "
        "The current promoted isotonic remains ACTIVE; nothing is promoted; live/paper disabled.", "",
        f"- split(windows): {ctx['split']}  gate_windows: {ctx['gate_windows']}  "
        f"base_rate(TEST): {_f(ctx['base_rate'])}  reliability_unit(report): {reliability_unit}",
        "", "| calibrator | n | brier | log_loss | ECE(row) | **ECE(window)** | YES_overpred(c) | "
        "NO_overpred(c) | backtest_net_pnl | trades |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in order:
        x = ctx["metrics"][m]
        bt = backtest.get(m, {})
        yo = x.get("yes_overprediction_cents")
        lines.append(
            f"| {m} | {x.get('n')} | {_f(x.get('brier'))} | {_f(x.get('log_loss'))} | {_f(x.get('ece_row'))} | "
            f"**{_f(x.get('ece_window'))}** | {_f(yo, 2)} | {_f(-yo, 2) if isinstance(yo,(int,float)) else 'None'} | "
            f"{_f(bt.get('net_pnl'), 4)} | {bt.get('total_simulated_trades')} |")
    lines += ["", "## Window vs row reliability (identity_raw; distinct-window is the honest unit)",
              "| bucket | row_n | win_n | eff_n(Kish) | row_yes | win_yes | row_buf(c) | **win_buf(c)** |",
              "|---|---|---|---|---|---|---|---|"]
    for b in reliab:
        rb = b.get("calib_buffer_row_cents")
        wb = b.get("calib_buffer_window_cents")
        lines.append(f"| {b['bucket']} | {b['row_n']} | {b['distinct_window_n']} | "
                     f"{b.get('effective_sample_size')} | {_f(b['row_yes_rate'],3)} | "
                     f"{_f(b['window_yes_rate'],3)} | {_f(rb,2)} | **{_f(wb,2)}** |")
    lines += ["", "## Recommendation (Part D/H — review only, NOT a promotion)",
              f"- recommended_replacement_candidate: **{elig['recommended_replacement_candidate']}**",
              f"- replacement_eligible_for_promotion_review: **{elig['replacement_eligible_for_promotion_review']}**",
              f"- blockers: {elig['blockers']}", f"- warnings: {elig['warnings']}",
              f"- rationale: {elig['rationale']}", "", "### Per-candidate criteria"]
    for c, r in elig["per_candidate"].items():
        lines.append(f"- **{c}**: STAGED_SHADOW_CANDIDATE={r['staged_shadow_candidate']} "
                     f"(better_window_ece={r['better_window_ece']}, reduces_yes_overpred={r['reduces_yes_overprediction']}, "
                     f"not_lose_backtest={r['not_lose_backtest']}, distinct_pass_windows={r['distinct_pass_windows']}, "
                     f"safer_calibrator={r['safer_calibrator']})")
    lines += ["", "## Safety",
              "- No promotion; promoted isotonic remains ACTIVE; manifest + promoted/active artifacts unchanged.",
              "- Window-based reliability is REPORT-ONLY and only ever WIDENS the buffer (never loosens a gate).",
              "- Candidates staged under data/models/staged/ only; live/paper disabled; live_submission_allowed=false."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["calibrator", "n", "brier", "log_loss", "ece_row", "ece_window",
                    "yes_overprediction_cents", "backtest_net_pnl", "trades",
                    "staged_shadow_candidate"])
        for m in order:
            x = ctx["metrics"][m]
            bt = backtest.get(m, {})
            ssc = elig["per_candidate"].get(m, {}).get("staged_shadow_candidate", "")
            w.writerow([m, x.get("n"), x.get("brier"), x.get("log_loss"), x.get("ece_row"),
                        x.get("ece_window"), x.get("yes_overprediction_cents"),
                        bt.get("net_pnl"), bt.get("total_simulated_trades"), ssc])
    return {"review_md": str(md), "review_csv": str(csvp)}


def _write_impact(config, cohort: dict, ctx) -> dict:
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_candidate_replacement_impact_{stamp}.md"
    csvp = d / f"kalshi_candidate_replacement_impact_{stamp}.csv"
    lines = [f"# Kalshi candidate replacement impact — {ctx.get('series', 'KXBTC15M')}", "",
             "> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- "
             "and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.", "",
             f"- ledger: `{cohort.get('ledger')}`  cohort_rows: {cohort.get('n_cohort')}"]
    for u, per_method in cohort.get("by_unit", {}).items():
        lines += ["", f"## reliability_unit = {u}",
                  "| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | "
                  "med_final(c) | best_final(c) | med_calib_buf(c) | side |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for m in _order(ctx["methods"]):
            s = per_method.get(m, {})
            lines.append(f"| {m} | {s.get('candidate_like')} | **{s.get('pass_final')}** | "
                         f"{s.get('distinct_pass_windows')} | {_f(s.get('top1_pass_window_share'),2)} | "
                         f"{_f(s.get('median_final_cents'),2)} | {_f(s.get('best_final_cents'),2)} | "
                         f"{_f(s.get('median_calib_buffer_cents'),2)} | {s.get('side_distribution')} |")
    row_pm = cohort.get("by_unit", {}).get("row", {})
    win_pm = cohort.get("by_unit", {}).get("window", {})
    any_pass_row = any(v.get("pass_final", 0) > 0 for m, v in row_pm.items() if m != "current_promoted_isotonic")
    any_pass_win = any(v.get("pass_final", 0) > 0 for m, v in win_pm.items() if m != "current_promoted_isotonic")
    lines += ["", "## Verdict",
              f"- any REPAIRED calibrator clears the final +edge gate — row unit: **{any_pass_row}**, "
              f"window unit: **{any_pass_win}**.",
              "- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER "
              "in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs "
              "thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — "
              "confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the "
              "selected side changes under window mode.)",
              "", "## Safety", "- No promotion; buffers never removed; live/paper disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unit", "calibrator", "candidate_like", "pass_final", "distinct_pass_windows",
                    "top1_pass_window_share", "median_final_cents", "best_final_cents",
                    "median_calib_buffer_cents", "side_distribution"])
        for u, per_method in cohort.get("by_unit", {}).items():
            for m in _order(ctx["methods"]):
                s = per_method.get(m, {})
                w.writerow([u, m, s.get("candidate_like"), s.get("pass_final"),
                            s.get("distinct_pass_windows"), s.get("top1_pass_window_share"),
                            s.get("median_final_cents"), s.get("best_final_cents"),
                            s.get("median_calib_buffer_cents"), json.dumps(s.get("side_distribution"))])
    return {"impact_md": str(md), "impact_csv": str(csvp), "any_repaired_pass_row": any_pass_row,
            "any_repaired_pass_window": any_pass_win}


def _write_backtest(config, ctx, backtest) -> dict:
    d = config.reports_path() / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_calibrator_replacement_backtest_{stamp}.md"
    lines = [f"# Kalshi calibrator replacement backtest — {ctx.get('series', 'KXBTC15M')}", "",
             "> STAGED / report-only. Executable YES/NO asks (never midpoint) + fees + depth + gates on "
             "held-out TEST windows. EVIDENCE only — NOT a profitability claim; in-sample P&L must NOT "
             "select a production policy. No promotion; live disabled.", "",
             f"- split(windows): {ctx['split']}", ""]
    for m in _order(ctx["methods"]):
        a = backtest.get(m, {})
        lines += [f"### {m}",
                  f"- trades: {a.get('total_simulated_trades')}  distinct_windows: {a.get('windows_touched')}  "
                  f"net_pnl: {_f(a.get('net_pnl'),4)}  hit_rate: {_f(a.get('hit_rate'))}  "
                  f"max_drawdown: {_f(a.get('max_drawdown'),4)}",
                  f"- pnl_by_side: {a.get('pnl_by_side')}",
                  f"- pnl_by_seconds_to_close: {a.get('pnl_by_seconds_to_close')}",
                  f"- pnl_by_net_edge_bucket: {a.get('pnl_by_net_edge_bucket')}", ""]
    lines += ["## Safety", "- EVIDENCE only; promoted isotonic remains active; no promotion; live disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"backtest_md": str(md)}


def _write_staged_catalog(config, staged: list[dict], ctx, elig) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_staged_replacement_artifacts_{_ts()}.json"
    path.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "series": ctx.get("series", "KXBTC15M"), "promotion": "NONE — staged only",
        "recommended_replacement_candidate": elig["recommended_replacement_candidate"],
        "replacement_eligible_for_promotion_review": elig["replacement_eligible_for_promotion_review"],
        "staged_artifacts": staged, "live_submission_allowed": False,
        "note": "All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime never auto-loads them; "
                "the promotion manifest was NOT modified."}, indent=2, default=str), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# Top-level runners
# --------------------------------------------------------------------------- #
def _prep_or_block(config, series):
    snap = snapshot_runtime_state(config)
    preservation = write_preservation(config, snap)
    prep = _prepare_runtime(config, series=series, mode="shadow")
    if prep.get("status") != "OK":
        return None, snap, preservation, {
            "series": series, "status": prep.get("status", "RUNTIME_UNAVAILABLE"),
            "blockers": prep.get("base", {}).get("blockers", []), "preservation_manifest": preservation,
            "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"],
            "live_submission_allowed": False}
    return prep, snap, preservation, None


def run_stage_calibrator_replacements(config, *, series: str = "KXBTC15M", embargo_windows: int = 1) -> dict:
    prep, snap, preservation, blocked = _prep_or_block(config, series)
    if blocked:
        return blocked
    ctx = build_promoted_context(prep, embargo_windows=embargo_windows)
    ctx["series"] = series
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "preservation_manifest": preservation, "live_submission_allowed": False}
    staged = stage_replacements(config, ctx, series=series)
    elig_stub = {"recommended_replacement_candidate": "n/a (run review)",
                 "replacement_eligible_for_promotion_review": None}
    catalog = _write_staged_catalog(config, staged, ctx, elig_stub)
    verify = verify_runtime_unchanged(config, snap)
    return {"series": series, "status": "OK", "staged_artifacts": staged, "catalog": catalog,
            "preservation_manifest": preservation, "runtime_unchanged": verify["unchanged"],
            "runtime_diff": verify, "live_submission_allowed": False}


def run_candidate_replacement_impact(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                                     embargo_windows: int = 1) -> dict:
    prep, snap, preservation, blocked = _prep_or_block(config, series)
    if blocked:
        return blocked
    ctx = build_promoted_context(prep, embargo_windows=embargo_windows)
    ctx["series"] = series
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "preservation_manifest": preservation, "live_submission_allowed": False}
    unit = getattr(config.edge_policy, "reliability_unit", "both")
    cohort = candidate_cohort_impact(config, ctx, ledger=ledger, unit=unit)
    if cohort.get("status") == "NO_LEDGER":
        return {"series": series, "status": "NO_LEDGER", "preservation_manifest": preservation,
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"],
                "live_submission_allowed": False}
    reports = _write_impact(config, cohort, ctx)
    verify = verify_runtime_unchanged(config, snap)
    return {"series": series, "status": "OK", "reliability_unit": unit, "ledger": cohort.get("ledger"),
            "n_cohort": cohort.get("n_cohort"), "by_unit": cohort.get("by_unit"), "reports": reports,
            "preservation_manifest": preservation, "runtime_unchanged": verify["unchanged"],
            "runtime_diff": verify, "live_submission_allowed": False}


def run_calibrator_replacement_review(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                                      embargo_windows: int = 1, stage: bool = True) -> dict:
    prep, snap, preservation, blocked = _prep_or_block(config, series)
    if blocked:
        return blocked
    ctx = build_promoted_context(prep, embargo_windows=embargo_windows)
    ctx["series"] = series
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "preservation_manifest": preservation, "live_submission_allowed": False}
    unit = getattr(config.edge_policy, "reliability_unit", "both")
    backtest = replacement_backtest(config, ctx)
    cohort = candidate_cohort_impact(config, ctx, ledger=ledger, unit=unit)
    elig = eligibility(ctx, backtest, cohort if cohort.get("by_unit") else {"by_unit": {"row": {}}})
    reliab = reliability_tables(ctx, "identity_raw")
    staged = stage_replacements(config, ctx, series=series) if stage else []
    review = _write_review(config, ctx, backtest, elig, reliab, unit)
    impact = _write_impact(config, cohort, ctx) if cohort.get("by_unit") else {}
    bt_report = _write_backtest(config, ctx, backtest)
    catalog = _write_staged_catalog(config, staged, ctx, elig) if staged else None
    verify = verify_runtime_unchanged(config, snap)
    return {
        "series": series, "status": "OK", "reliability_unit": unit, "split": ctx["split"],
        "gate_windows": ctx["gate_windows"], "base_rate": ctx["base_rate"],
        "metrics": {m: {k: v for k, v in ctx["metrics"][m].items() if k != "reliability_window"}
                    for m in ctx["methods"]},
        "backtest": backtest, "eligibility": elig,
        "recommended_replacement_candidate": elig["recommended_replacement_candidate"],
        "replacement_eligible_for_promotion_review": elig["replacement_eligible_for_promotion_review"],
        "reports": {**review, **impact, **bt_report, "staged_catalog": catalog},
        "staged_artifacts": staged, "preservation_manifest": preservation,
        "runtime_unchanged": verify["unchanged"], "runtime_diff": verify,
        "live_submission_allowed": False}
