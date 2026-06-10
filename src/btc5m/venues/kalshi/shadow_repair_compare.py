"""Staged SHADOW comparison of repaired probabilities (report-only; NEVER live/paper).

Scores the SAME active executable rows (live shadow loop) — or, offline, the rows of the
latest shadow ledger — with several probability sources and runs the SAME confidence-aware
edge policy on each, so we can see which (if any) would create positive FINAL edge WITHOUT
weakening any gate or removing the calibration buffer:

  current_promoted_isotonic   the deployed model + isotonic (what shadow uses today)
  identity_raw                the promoted model's RAW probability, no calibration
  platt                       a Platt/sigmoid calibrator fit on held-out CALIB windows
  market_implied              P(YES) from executable asks (DIAGNOSTIC benchmark)
  market_shrunk_a{α}          α·p_model + (1-α)·p_market for conservative α (near-market)

Each source's calibration buffer comes from THAT source's own reliability buckets, so a
better-calibrated source legitimately earns a smaller buffer — the buffer is never removed.

Safety: reads recorded data only; scores in memory; writes reports + a SHADOW ledger; never
records, never fills, never promotes, never changes the manifest/active artifacts, never
enables paper/live. ``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ...timeutils import now_ms
from .calibrate import Calibrator, build_calibrator_artifact, fit_calibrator, save_calibrator
from .edge_policy import EdgeInputs, evaluate_edge
from .executable_backtest import market_implied_probs
from .model_artifacts import DIAGNOSTIC_ONLY, STAGED_NON_PROMOTED, staged_models_dir, tradable_status_for
from .paper_runtime import _decision_eligibility, _prepare_runtime, _score, latest_feature_rows
from .probability_repair import (
    blend, market_implied_yes, snapshot_runtime_state, verify_runtime_unchanged,
    write_preservation_manifest,
)
from .splits import three_way_window_split
from .uncertainty import build_calibration_buckets

ALPHAS_DEFAULT = [0.0, 0.05, 0.1, 0.2]
STAGED_SHADOW_CANDIDATE = "STAGED_SHADOW_CANDIDATE"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _median(xs) -> Optional[float]:
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _f(x, nd=2) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _alpha_method(a: float) -> str:
    return f"market_shrunk_a{a}"


# --------------------------------------------------------------------------- #
# Build the per-method calibrators + reliability buckets (from PROMOTED-model raw)
# --------------------------------------------------------------------------- #
def prepare_methods(prep: dict, *, embargo_windows: int = 1, alphas=ALPHAS_DEFAULT,
                    shrink_base: str = "identity_raw") -> dict:
    """Fit Platt/identity on the PROMOTED model's raw probs (OOS) + build per-method buckets.

    Calibrators are fit on the promoted model's CALIB-window raw predictions so they are
    consistent with the live loop (which scores raw via the same promoted model). Buckets
    are over ALL labelled rows (the runtime's convention); the promoted-isotonic source
    reuses the runtime's own buckets for maximum fidelity.
    """
    rows = prep["dataset_rows"]
    labelled = [r for r in rows if r.get("label_yes_resolved") is not None
                and r.get("model_probability_yes") is not None]
    y_all = [int(r["label_yes_resolved"]) for r in labelled]
    raw_all = [r["model_probability_yes"] for r in labelled]
    promoted_all = [r.get("calibrated_probability_yes") for r in labelled]
    market_all = market_implied_probs(labelled, list(range(len(labelled))))

    sp = three_way_window_split(labelled, embargo_windows=embargo_windows)
    if sp["applied"]:
        raw_calib = [raw_all[i] for i in sp["calib_idx"]]
        y_calib = [y_all[i] for i in sp["calib_idx"]]
    else:
        raw_calib, y_calib = raw_all, y_all
    calibrators = {m: fit_calibrator(m, raw_calib, y_calib) for m in ("identity", "platt")}
    platt_all = calibrators["platt"].transform(raw_all)

    base_all = platt_all if shrink_base == "platt" else raw_all
    method_probs = {
        "current_promoted_isotonic": promoted_all,
        "identity_raw": raw_all,
        "platt": platt_all,
        "market_implied": market_all,
    }
    for a in alphas:
        method_probs[_alpha_method(a)] = [
            blend(b, m, a) if (b is not None and m is not None) else None
            for b, m in zip(base_all, market_all)]

    buckets: dict = {}
    for name, p in method_probs.items():
        pairs = [(yy, pp) for yy, pp in zip(y_all, p) if pp is not None]
        buckets[name] = (build_calibration_buckets([a for a, _ in pairs], [b for _, b in pairs])
                         if pairs else [])
    # promoted-isotonic uses the runtime's own all-rows buckets (what shadow really applies)
    if prep.get("buckets"):
        buckets["current_promoted_isotonic"] = prep["buckets"]

    return {
        "method_names": list(method_probs.keys()),
        "calibrators": {m: c.to_dict() for m, c in calibrators.items()},
        "buckets": buckets, "alphas": list(alphas), "shrink_base": shrink_base,
        "n_labelled": len(labelled), "gate_windows": prep.get("dataset_rows") and len(
            {r.get("ticker") for r in labelled}),
        "split": {k: sp.get(k) for k in ("n_windows", "train_windows", "calib_windows",
                                         "test_windows", "embargo_windows")},
        "_platt": calibrators["platt"],
    }


def _method_prob(name: str, *, raw_p, promoted_p, market, mctx) -> Optional[float]:
    if name == "current_promoted_isotonic":
        return promoted_p
    if name == "identity_raw":
        return raw_p
    if name == "platt":
        return mctx["_platt"].transform([raw_p])[0] if raw_p is not None else None
    if name == "market_implied":
        return market
    if name.startswith("market_shrunk_a"):
        if raw_p is None or market is None:
            return None
        a = float(name.split("market_shrunk_a")[1])
        base = (mctx["_platt"].transform([raw_p])[0] if mctx["shrink_base"] == "platt" else raw_p)
        return blend(base, market, a)
    return None


def _bucket_label(p: Optional[float]) -> str:
    if p is None:
        return "na"
    b = min(9, max(0, int(float(p) * 10)))
    return f"[{b/10:.1f},{(b+1)/10:.1f})"


# --------------------------------------------------------------------------- #
# Score ONE row under every method (the shared engine for live + replay)
# --------------------------------------------------------------------------- #
def score_row_all_methods(raw_p, promoted_p, ya, na, *, mctx, edge_cfg, fee_model,
                          book_age_ms=None, coinbase_stale=False, binance_stale=False) -> dict:
    market = market_implied_yes(ya, na)
    out: dict = {}
    for name in mctx["method_names"]:
        p = _method_prob(name, raw_p=raw_p, promoted_p=promoted_p, market=market, mctx=mctx)
        if p is None or ya is None or na is None:
            continue
        ens = {"model": p}
        if market is not None:
            ens["market_implied"] = market
        dec = evaluate_edge(EdgeInputs(
            p_yes_hat=p, yes_ask=ya, no_ask=na, book_age_ms=book_age_ms,
            coinbase_stale=bool(coinbase_stale), binance_stale=bool(binance_stale),
            calibration_buckets=mctx["buckets"].get(name, []), ensemble_probs=ens,
            model_calibrated=True, model_tradable=True, backtest_valid=True), edge_cfg, fee_model)
        out[name] = {
            "p": p, "market": market, "side": dec.side,
            "raw_edge_cents": dec.raw_edge_cents,
            "uncertainty_adjusted_edge_cents": dec.uncertainty_adjusted_edge_cents,
            "final_policy_edge_cents": dec.final_policy_edge_cents,
            "calib_buffer_cents": dec.calibration_uncertainty_buffer_cents,
            "state": dec.state, "bucket": _bucket_label(p),
            "market_disagreement_cents": ((p - market) * 100.0) if market is not None else None,
            "reason_codes": dec.reason_codes,
        }
    return out


class _Acc:
    """Per-method accumulator over the shadow run."""

    def __init__(self, min_raw_edge_cents: float):
        self.min_raw = min_raw_edge_cents
        self.m: dict = defaultdict(lambda: {
            "n": 0, "candidate_like": 0, "pass_final": 0, "raw": [], "unc": [], "final": [],
            "calib_buf": [], "disagree": [], "sides": Counter(), "buckets": Counter(),
            "reasons": Counter()})

    def add(self, recs: dict):
        for name, d in recs.items():
            g = self.m[name]
            g["n"] += 1
            if (d["raw_edge_cents"] or -9) >= self.min_raw - 1e-9:
                g["candidate_like"] += 1
            if d["state"] == "EDGE_OK":
                g["pass_final"] += 1
            g["raw"].append(d["raw_edge_cents"])
            g["unc"].append(d["uncertainty_adjusted_edge_cents"])
            g["final"].append(d["final_policy_edge_cents"])
            g["calib_buf"].append(d["calib_buffer_cents"])
            if d["market_disagreement_cents"] is not None:
                g["disagree"].append(abs(d["market_disagreement_cents"]))
            if d["side"]:
                g["sides"][d["side"]] += 1
            g["buckets"][d["bucket"]] += 1
            for rc in (d["reason_codes"] or []):
                g["reasons"][rc] += 1

    def summary(self) -> dict:
        out = {}
        for name, g in self.m.items():
            finals = [x for x in g["final"] if isinstance(x, (int, float))]
            out[name] = {
                "n_rows": g["n"], "candidate_like_rows": g["candidate_like"],
                "pass_final_edge": g["pass_final"],
                "median_raw_edge_cents": _median(g["raw"]),
                "median_uncertainty_adjusted_edge_cents": _median(g["unc"]),
                "median_final_edge_cents": _median(finals),
                "best_final_edge_cents": (max(finals) if finals else None),
                "median_calib_buffer_cents": _median(g["calib_buf"]),
                "mean_abs_market_disagreement_cents": (
                    sum(g["disagree"]) / len(g["disagree"]) if g["disagree"] else None),
                "side_distribution": dict(g["sides"]),
                "bucket_distribution": dict(g["buckets"].most_common()),
                "top_rejection_reasons": dict(g["reasons"].most_common(6)),
            }
        return out


# --------------------------------------------------------------------------- #
# Staged candidate artifacts (NEVER promoted; staged dir only)
# --------------------------------------------------------------------------- #
def stage_candidates(config, mctx: dict, *, series: str) -> list[dict]:
    """Save STAGED (non-promoted) candidate artifacts: identity, Platt, market-shrunk alphas."""
    staged: list[dict] = []
    sm = {k: mctx["split"].get(k) for k in ("train_windows", "calib_windows", "test_windows")}
    for method in ("identity", "platt"):
        art = build_calibrator_artifact(
            calibrator=Calibrator.from_dict(mctx["calibrators"][method]), method=method,
            model_name="microstructure_logistic", split_metadata=sm,
            metrics_before={}, metrics_after={}, tradable=False,
            gate_windows=mctx.get("gate_windows") or 0, is_staged=True,
            created_by_command="kalshi-shadow-compare-probability-repairs", series=series,
            notes=f"STAGED shadow candidate ({method}); NON-PROMOTED; report-only.")
        art["tradable_status"] = STAGED_NON_PROMOTED
        art["artifact_type"] = "shadow_candidate"
        paths = save_calibrator(config, art, stem=f"kalshi_shadow_candidate_{method}_{_ts()}", staged=True)
        staged.append({**paths, "method": method, "tradable_status": STAGED_NON_PROMOTED})
    d = staged_models_dir(config)
    for a in mctx["alphas"]:
        artifact = {
            "artifact_type": "shadow_candidate", "method": "market_shrink",
            "blender": {"formula": "alpha*p_model + (1-alpha)*p_market", "alpha": a,
                        "base": mctx["shrink_base"]},
            "alpha": a, "base": mctx["shrink_base"],
            "market_implied_source": "executable Kalshi YES/NO asks: ya/(ya+na)",
            "split_metadata": sm, "model_name": "microstructure_logistic", "series": series,
            "is_staged": True, "is_promoted": False, "promotion_required": True,
            "tradable_status": DIAGNOSTIC_ONLY, "tradable": False, "is_diagnostic": True,
            "live_approved": False, "calibration_status": "diagnostic",
            "created_by_command": "kalshi-shadow-compare-probability-repairs",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notes": f"STAGED shadow candidate market-shrink alpha={a}; DIAGNOSTIC_ONLY; never promoted.",
        }
        stem = f"kalshi_shadow_candidate_market_shrink_a{a}_{_ts()}"
        import pickle
        (d / f"{stem}.pkl").write_bytes(pickle.dumps(artifact))
        (d / f"{stem}.json").write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
        staged.append({"artifact_file": str(d / f"{stem}.pkl"), "summary_file": str(d / f"{stem}.json"),
                       "method": f"market_shrink_a{a}", "tradable_status": DIAGNOSTIC_ONLY,
                       "check": tradable_status_for(is_diagnostic=True, is_staged=True, is_promoted=False)})
    return staged


# --------------------------------------------------------------------------- #
# Live shadow loop (reuses paper_runtime row selection + promoted scoring)
# --------------------------------------------------------------------------- #
def _live_loop(config, prep, mctx, *, minutes, poll_interval, scan_lines, max_iterations,
               edge_cfg, fee_model, on_row=None,
               sleep: Callable[[float], None] = time.sleep,
               monotonic: Callable[[], float] = time.monotonic, now_fn=now_ms) -> dict:
    fcfg = config.freshness
    ftr_thr = int(max(int(fcfg.coinbase_decision_max_age_ms), int(float(poll_interval) * 1000 * 2)))
    md_secs = int(getattr(getattr(config, "low_latency", None), "market_duration_seconds", 900))
    pc_eff = prep["pc_eff"]
    model_art, cal_art = prep["model_art"], prep["cal_art"]
    acc = _Acc(edge_cfg.min_raw_edge_cents)
    seen: set = set()
    sel = {"rows_read": 0, "executable_rows": 0, "rejected_before_scoring": 0,
           "rejected_by_reason": Counter()}
    start = monotonic()
    end = start + max(0.0, float(minutes) * 60.0)
    it = 0
    while True:
        it += 1
        now = now_fn()
        eligible = []
        for r in latest_feature_rows(config, series=prep["base"]["series"], lines=scan_lines):
            key = (r.get("ticker"), r.get("as_of_ts_ms"))
            if key in seen:
                continue
            seen.add(key)
            sel["rows_read"] += 1
            ok, reasons, _flags = _decision_eligibility(
                r, pc=pc_eff, market_duration_seconds=md_secs, feature_row_max_age_ms=ftr_thr, now=now)
            if ok:
                sel["executable_rows"] += 1
                eligible.append(r)
            else:
                sel["rejected_before_scoring"] += 1
                for rc in reasons:
                    sel["rejected_by_reason"][rc] += 1
        if eligible:
            raw, promoted = _score(config, eligible, model_art, cal_art)
            for j, r in enumerate(eligible):
                recs = score_row_all_methods(
                    raw[j], promoted[j], r.get("yes_ask"), r.get("no_ask"), mctx=mctx,
                    edge_cfg=edge_cfg, fee_model=fee_model, book_age_ms=r.get("book_age_ms"),
                    coinbase_stale=r.get("coinbase_stale"), binance_stale=r.get("binance_stale"))
                acc.add(recs)
                if on_row:
                    on_row(r, recs)
        if max_iterations and it >= max_iterations:
            break
        if monotonic() >= end:
            break
        sleep(max(0.2, min(float(poll_interval), max(0.0, end - monotonic()))))
    return {"mode": "live", "iterations": it, "elapsed_s": round(monotonic() - start, 2),
            "rows_read": sel["rows_read"], "executable_rows": sel["executable_rows"],
            "rejected_before_scoring": sel["rejected_before_scoring"],
            "rejected_before_scoring_by_reason": dict(sel["rejected_by_reason"].most_common()),
            "accumulator": acc}


def _replay_loop(config, prep, mctx, *, ledger_path, edge_cfg, fee_model, on_row=None) -> dict:
    from .uncertainty_audit import latest_ledger, load_decisions
    lp = Path(ledger_path) if ledger_path else latest_ledger(config)
    if lp is None or not Path(lp).exists():
        return {"mode": "replay", "ledger": None, "accumulator": _Acc(edge_cfg.min_raw_edge_cents),
                "rows_read": 0, "executable_rows": 0}
    decs = load_decisions(lp)
    acc = _Acc(edge_cfg.min_raw_edge_cents)
    n = 0
    for d in decs:
        raw = d.get("model_probability_yes")
        promoted = d.get("calibrated_probability_yes")
        ya, na = d.get("executable_yes_price"), d.get("executable_no_price")
        if raw is None or ya is None or na is None:
            continue
        recs = score_row_all_methods(raw, promoted, ya, na, mctx=mctx, edge_cfg=edge_cfg,
                                     fee_model=fee_model, book_age_ms=d.get("book_age_ms"),
                                     coinbase_stale=d.get("coinbase_decision_stale"),
                                     binance_stale=d.get("binance_decision_stale"))
        acc.add(recs)
        n += 1
        if on_row:
            on_row(d, recs)
    return {"mode": "replay", "ledger": str(lp), "iterations": 1, "elapsed_s": 0.0,
            "rows_read": len(decs), "executable_rows": n,
            "rejected_before_scoring": len(decs) - n, "rejected_before_scoring_by_reason": {},
            "accumulator": acc}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _write_reports(config, *, series, mode, loop_meta, summary, mctx, staged, verdict) -> dict:
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_shadow_compare_probability_repairs_{stamp}.md"
    csvp = d / f"kalshi_shadow_compare_probability_repairs_{stamp}.csv"
    order = [m for m in ["current_promoted_isotonic", "identity_raw", "platt", "market_implied"]
             if m in summary] + sorted([m for m in summary if m.startswith("market_shrunk_a")])
    lines = [
        f"# Kalshi shadow comparison — repaired probabilities ({series})", "",
        "> STAGED / report-only. Same executable rows scored by every probability source through the "
        "SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). "
        "No promotion; no manifest change; live/paper disabled.", "",
        f"- mode: **{mode}**  rows_read: {loop_meta.get('rows_read')}  "
        f"executable_rows: {loop_meta.get('executable_rows')}  iterations: {loop_meta.get('iterations')}  "
        f"elapsed_s: {loop_meta.get('elapsed_s')}",
        f"- split(windows): {mctx['split']}  shrink_base: {mctx['shrink_base']}  alphas: {mctx['alphas']}",
        f"- rejected_before_scoring_by_reason: {loop_meta.get('rejected_before_scoring_by_reason')}",
        "", "| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | "
        "med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in order:
        s = summary[name]
        lines.append(
            f"| {name} | {s['n_rows']} | {s['candidate_like_rows']} | **{s['pass_final_edge']}** | "
            f"{_f(s['median_raw_edge_cents'])} | {_f(s['median_uncertainty_adjusted_edge_cents'])} | "
            f"{_f(s['median_final_edge_cents'])} | {_f(s['best_final_edge_cents'])} | "
            f"{_f(s['median_calib_buffer_cents'])} | {s['side_distribution']} | "
            f"{_f(s['mean_abs_market_disagreement_cents'])} |")
    lines += ["", "## Rejection reasons + bucket distribution (per source)"]
    for name in order:
        s = summary[name]
        lines.append(f"- **{name}**: reasons={s['top_rejection_reasons']}  buckets={s['bucket_distribution']}")
    lines += ["", "## Verdict",
              f"- any REPAIRED source creates positive FINAL edge (without removing protection): "
              f"**{verdict['any_repaired_pass']}**  (best repaired final = {_f(verdict['best_repaired_final_cents'])}c)",
              f"- promoted-isotonic reference passes {summary.get('current_promoted_isotonic',{}).get('pass_final_edge',0)} "
              "row(s) (not a repair).",
              f"- **recommendation: {verdict['recommendation']}**"]
    if verdict.get("staged_shadow_candidate"):
        lines.append(f"- STAGED_SHADOW_CANDIDATE: {verdict['staged_shadow_candidate']} "
                     "(marked STAGED only; NOT promoted; requires a separate review).")
    lines += ["", "## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)"]
    for a in staged:
        lines.append(f"- {a.get('method')}: {a.get('tradable_status')} -> "
                     f"{a.get('artifact_file') or a.get('calibrator_file')}")
    lines += ["", "## Safety",
              "- Shadow scoring only; no fills, no orders; per-source buffer never removed.",
              "- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.",
              "- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        import csv as _csv
        w = _csv.writer(fh)
        w.writerow(["source", "rows", "candidate_like", "pass_final", "median_raw_cents",
                    "median_unc_adj_cents", "median_final_cents", "best_final_cents",
                    "median_calib_buffer_cents", "mean_abs_market_disagreement_cents",
                    "side_distribution", "top_rejection_reasons"])
        for name in order:
            s = summary[name]
            w.writerow([name, s["n_rows"], s["candidate_like_rows"], s["pass_final_edge"],
                        s["median_raw_edge_cents"], s["median_uncertainty_adjusted_edge_cents"],
                        s["median_final_edge_cents"], s["best_final_edge_cents"],
                        s["median_calib_buffer_cents"], s["mean_abs_market_disagreement_cents"],
                        json.dumps(s["side_distribution"]), json.dumps(s["top_rejection_reasons"])])
    return {"report_md": str(md), "report_csv": str(csvp)}


def _verdict(summary: dict) -> dict:
    """A repaired source 'passes' only if it clears the final edge gate on >0 rows. The
    promoted-isotonic column is the unchanged REFERENCE, not a repair."""
    repaired = [n for n in summary if n != "current_promoted_isotonic"]
    passers = [n for n in repaired if summary[n]["pass_final_edge"] > 0]
    best = max((summary[n]["best_final_edge_cents"] for n in repaired
                if summary[n]["best_final_edge_cents"] is not None), default=None)
    any_pass = bool(passers)
    if any_pass:
        rec = (f"{passers} cleared the final edge gate on real shadow rows WITHOUT weakening it — "
               "mark STAGED_SHADOW_CANDIDATE and review (calibration + concentration) before any promotion. "
               "Do NOT promote here.")
    else:
        rec = ("NO repaired source clears the +final edge gate. Repair improves calibration but does not "
               "manufacture tradable edge — continue DATA COLLECTION and periodic RETRAINING/RECALIBRATION "
               "only; do not lower thresholds, do not remove buffers, do not promote.")
    return {"any_repaired_pass": any_pass, "best_repaired_final_cents": best,
            "staged_shadow_candidate": (passers or None), "recommendation": rec}


# --------------------------------------------------------------------------- #
# Top-level runner
# --------------------------------------------------------------------------- #
def run_shadow_compare(config, *, series: str = "KXBTC15M", minutes: float = 30.0,
                       poll_interval: float = 0.5, alphas=ALPHAS_DEFAULT,
                       shrink_base: str = "identity_raw", scan_lines: int = 4000,
                       max_iterations: Optional[int] = None, replay_ledger: Optional[str] = None,
                       stage: bool = True, embargo_windows: int = 1,
                       write_ledger: bool = True) -> dict:
    """Run the staged shadow comparison (live loop, or replay the latest ledger). Report-only."""
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    prep = _prepare_runtime(config, series=series, mode="shadow")
    base = {"series": series, "live_submission_allowed": False, "preservation_manifest": preservation}
    if prep.get("status") != "OK":
        return {**base, "status": prep.get("status", "RUNTIME_UNAVAILABLE"),
                "blockers": prep.get("base", {}).get("blockers", []),
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    mctx = prepare_methods(prep, embargo_windows=embargo_windows, alphas=alphas, shrink_base=shrink_base)
    edge_cfg, fee_model = prep["edge_cfg"], prep["fee_model"]

    # per-row shadow ledger (compact; nested per-method edges)
    ledger_rows: list[dict] = []

    def _on_row(r, recs):
        if write_ledger:
            ledger_rows.append({
                "ticker": r.get("ticker"), "as_of_ts_ms": r.get("as_of_ts_ms"),
                "seconds_to_close": r.get("seconds_to_close"),
                "yes_ask": r.get("executable_yes_price", r.get("yes_ask")),
                "no_ask": r.get("executable_no_price", r.get("no_ask")),
                "methods": {n: {"p": d["p"], "final_policy_edge_cents": d["final_policy_edge_cents"],
                                "state": d["state"], "side": d["side"]} for n, d in recs.items()},
                "live_submission_allowed": False})

    use_replay = bool(replay_ledger) or (minutes is not None and float(minutes) <= 0)
    if use_replay:
        loop = _replay_loop(config, prep, mctx, ledger_path=replay_ledger, edge_cfg=edge_cfg,
                            fee_model=fee_model, on_row=_on_row)
    else:
        loop = _live_loop(config, prep, mctx, minutes=float(minutes), poll_interval=float(poll_interval),
                          scan_lines=scan_lines, max_iterations=max_iterations, edge_cfg=edge_cfg,
                          fee_model=fee_model, on_row=_on_row)
        # Offline / no fresh active rows -> fall back to replaying the latest ledger so the
        # comparison is still meaningful (clearly labelled as replay).
        if loop["executable_rows"] == 0:
            loop = _replay_loop(config, prep, mctx, ledger_path=None, edge_cfg=edge_cfg,
                                fee_model=fee_model, on_row=_on_row)
            loop["fell_back_to_replay"] = True

    summary = loop["accumulator"].summary()
    verdict = _verdict(summary)
    staged = stage_candidates(config, mctx, series=series) if stage else []

    ledger_file = None
    if write_ledger and ledger_rows:
        ld = config.data_path() / "paper" / "experiments"
        ld.mkdir(parents=True, exist_ok=True)
        # NOTE: deliberately NOT "*_decisions.jsonl" so this never collides with the
        # edge-blocked-cohort ledgers that uncertainty_audit / candidate-repair pick as "latest".
        ledger_file = str(ld / f"shadow_compare_{_ts()}_methods.jsonl")
        with open(ledger_file, "w", encoding="utf-8") as fh:
            for row in ledger_rows:
                fh.write(json.dumps(row, default=str) + "\n")

    reports = _write_reports(config, series=series, mode=loop["mode"], loop_meta=loop,
                             summary=summary, mctx=mctx, staged=staged, verdict=verdict)
    verify = verify_runtime_unchanged(config, snap)
    return {**base, "status": "OK", "mode": loop["mode"],
            "fell_back_to_replay": loop.get("fell_back_to_replay", False),
            "rows_read": loop.get("rows_read"), "executable_rows": loop.get("executable_rows"),
            "rejected_before_scoring_by_reason": loop.get("rejected_before_scoring_by_reason"),
            "split": mctx["split"], "shrink_base": shrink_base, "alphas": list(alphas),
            "summary": summary, "verdict": verdict, "staged_candidates": staged,
            "ledger_file": ledger_file, "reports": reports,
            "runtime_unchanged": verify["unchanged"], "runtime_diff": verify}
