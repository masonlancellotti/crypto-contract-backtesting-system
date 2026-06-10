"""Probability repair + market-shrinkage modeling (STAGED / report-only; NEVER live).

Tests whether we can HONESTLY reduce the edge policy's calibration-uncertainty buffer
by improving the probability estimate — not by removing the buffer. It compares, on
held-out TEST windows (purged/embargoed, distinct-window), these probability sources:

  raw_model                  fresh microstructure logistic, no calibration
  identity                   raw probability used as the final probability
  current_promoted_calibrator  the deployed model+isotonic, scored on TEST (REFERENCE
                               ONLY — the promoted model may have trained on some TEST
                               windows, so its TEST metrics are optimistic; never used
                               for selection)
  staged_platt               sigmoid/Platt calibrator fit on held-out CALIB windows
  staged_isotonic            isotonic calibrator (flagged high overfit risk)
  market_implied             P(YES) implied by executable YES/NO asks (DIAGNOSTIC
                               benchmark, never an automatic trading signal)
  market_shrunk              alpha*p_model + (1-alpha)*p_market over an alpha grid,
                               alpha chosen ONLY by out-of-sample calibration

Safety: every output is STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY. It never modifies the
promotion manifest, the promoted artifacts, the active runtime selection, or any gate,
and never enables paper/live. ``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import csv
import json
import pickle
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...models import pure_ml
from .calibrate import Calibrator, build_calibrator_artifact, fit_calibrator, save_calibrator
from .calibration_report import calibration_summary
from .edge_policy import EdgeInputs, EdgePolicyConfig, evaluate_edge
from .executable_backtest import (
    BacktestParams, _attach, market_implied_probs, predict_from_artifact, simulate_backtest,
)
from .feature_schema import MICROSTRUCTURE_FEATURES, feature_vector
from .fees import KalshiFeeModel
from .model_artifacts import (
    DIAGNOSTIC_ONLY, STAGED_NON_PROMOTED, staged_models_dir, tradable_status_for,
)
from .model_dataset import build_model_dataset
from .paper_promotion import load_active_promotion, manifest_path, sha256_file
from .splits import three_way_window_split, walk_forward_indices
from .train_baselines import fit_predict_logistic
from .uncertainty import build_calibration_buckets
from .uncertainty_audit import (
    bucket_window_stats, latest_ledger, load_decisions, select_cohort,
)

ALPHA_GRID = [round(0.1 * i, 1) for i in range(11)]   # 0.0 .. 1.0
SHRINK_BASES = ("raw", "platt", "isotonic")
CALIB_METHODS = ("identity", "platt", "isotonic")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def market_implied_yes(ya, na) -> Optional[float]:
    """P(YES) implied by executable asks; None when no YES ask."""
    if ya is None:
        return None
    if na is not None and (ya + na) > 0:
        return max(0.0, min(1.0, ya / (ya + na)))
    return max(0.0, min(1.0, ya))


def blend(p_model: float, p_market: float, alpha: float) -> float:
    """market-shrunk probability: alpha*model + (1-alpha)*market, clamped to [0,1]."""
    return max(0.0, min(1.0, alpha * p_model + (1.0 - alpha) * p_market))


def _median(xs) -> Optional[float]:
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _f(x, nd=4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _predict_idx(rows, feats, model_dict, imp_dict, idx) -> list:
    """Predict pure-Python logistic probs for rows[idx] from a fitted model/imputer dict."""
    if not idx or not model_dict:
        return []
    model = pure_ml.LogisticRegression.from_dict(model_dict)
    imp = pure_ml.StandardImputer()
    imp.means = list(imp_dict.get("means", []))
    imp.stds = list(imp_dict.get("stds", []))
    imp.n_features = imp_dict.get("n_features", len(imp.means))
    X = [feature_vector(rows[i], feats) for i in idx]
    return model.predict_proba(imp.transform(X))


# --------------------------------------------------------------------------- #
# Part A — preserve promoted runtime state (hash + verify; never modify)
# --------------------------------------------------------------------------- #
def snapshot_runtime_state(config) -> dict:
    """Hash the promotion manifest, promoted artifacts, and legacy active pointers."""
    snap: dict = {}
    mp = manifest_path(config)
    if mp.exists():
        snap[str(mp)] = sha256_file(mp)
    pdir = config.data_path() / "models" / "paper_promoted"
    if pdir.exists():
        for p in sorted(pdir.glob("*.pkl")):
            snap[str(p)] = sha256_file(p)
    mdir = config.data_path() / "models"
    if mdir.exists():
        for p in sorted(mdir.glob("*.pkl")):       # non-recursive legacy active pointers
            snap[str(p)] = sha256_file(p)
    return snap


def write_preservation_manifest(config, snapshot: dict) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_runtime_preservation_{_ts()}.json"
    path.write_text(json.dumps({
        "purpose": "PRESERVE promoted/active runtime state across probability-repair work",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": snapshot, "n_files": len(snapshot),
        "live_submission_allowed": False}, indent=2), encoding="utf-8")
    return str(path)


def verify_runtime_unchanged(config, snapshot: dict) -> dict:
    """Re-hash and compare to a prior snapshot. Returns unchanged + any diffs."""
    now = snapshot_runtime_state(config)
    changed = [p for p in snapshot if now.get(p) != snapshot[p]]
    removed = [p for p in snapshot if p not in now]
    added = [p for p in now if p not in snapshot]
    return {"unchanged": not (changed or removed or added),
            "changed": changed, "removed": removed, "added": added}


# --------------------------------------------------------------------------- #
# Part B/C — build the repair context (one purged window split, all sources)
# --------------------------------------------------------------------------- #
def build_repair_context(config, *, series: str = "KXBTC15M", embargo_windows: int = 1) -> dict:
    """Build the held-out TEST probabilities for every source on ONE purged window split.

    raw/identity/platt/isotonic share a fresh microstructure-logistic backbone (fit on
    TRAIN, calibrators fit on CALIB); market-implied + market-shrunk use executable asks;
    the promoted pipeline is scored on TEST as a REFERENCE column only.
    """
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    sp = three_way_window_split(rows, embargo_windows=embargo_windows)
    ctx = {"series": series, "applied": sp["applied"], "reason": sp.get("reason"),
           "gate_windows": gate_windows, "n_rows": len(rows),
           "split": {k: sp.get(k) for k in ("n_windows", "train_windows", "calib_windows",
                                            "test_windows", "embargo_windows")}}
    if not sp["applied"]:
        return ctx

    feats = MICROSTRUCTURE_FEATURES
    p_calib, mdict, idict = fit_predict_logistic(rows, feats, sp["train_idx"], sp["calib_idx"])
    y_calib = [int(rows[i]["label_yes_resolved"]) for i in sp["calib_idx"]]

    # keep only TEST rows with executable asks (needed for market-implied / shrink)
    test_idx = [i for i in sp["test_idx"]
                if rows[i].get("yes_ask") is not None and rows[i].get("no_ask") is not None]
    y_test = [int(rows[i]["label_yes_resolved"]) for i in test_idx]
    tickers = [rows[i].get("ticker") for i in test_idx]
    base_rate = (sum(y_test) / len(y_test)) if y_test else None

    p_raw = _predict_idx(rows, feats, mdict, idict, test_idx)
    cal = {m: fit_calibrator(m, p_calib, y_calib) for m in CALIB_METHODS}
    p_platt = cal["platt"].transform(p_raw)
    p_iso = cal["isotonic"].transform(p_raw)
    p_market = [market_implied_yes(rows[i].get("yes_ask"), rows[i].get("no_ask")) for i in test_idx]

    # promoted pipeline (REFERENCE ONLY — may be in-sample on some TEST windows)
    promo = load_active_promotion(config, series=series)
    p_promoted = None
    if promo.get("valid"):
        try:
            praw_prom = predict_from_artifact(promo["model_artifact"], rows, test_idx)
            cobj = Calibrator.from_dict((promo.get("calibrator_artifact") or {}).get("calibrator", {}))
            p_promoted = cobj.transform(praw_prom)
        except Exception:  # noqa: BLE001
            p_promoted = None

    ctx.update({
        "feats": feats, "rows": rows, "sp": sp, "test_idx": test_idx,
        "y_test": y_test, "tickers": tickers, "base_rate": base_rate,
        "model_dict": mdict, "imputer_dict": idict, "calibrators": {m: cal[m].to_dict() for m in cal},
        "p_calib": p_calib, "y_calib": y_calib,
        "sources": {
            "raw_model": p_raw, "identity": list(p_raw), "staged_platt": p_platt,
            "staged_isotonic": p_iso, "market_implied": p_market,
            **({"current_promoted_calibrator": p_promoted} if p_promoted is not None else {}),
        },
        "promoted_valid": bool(promo.get("valid")),
    })
    return ctx


# --------------------------------------------------------------------------- #
# Part D — per-source calibration metrics (distinct-window primary)
# --------------------------------------------------------------------------- #
def source_metrics(y: list, p: list, tickers: list, base_rate: Optional[float]) -> dict:
    """Brier/log-loss/ECE (row) + distinct-window ECE + signed YES over-prediction."""
    pairs = [(yi, pi, tk) for yi, pi, tk in zip(y, p, tickers) if pi is not None]
    if not pairs:
        return {"n": 0}
    yy = [a for a, _, _ in pairs]
    pp = [b for _, b, _ in pairs]
    tt = [c for _, _, c in pairs]
    cs = calibration_summary(yy, pp)
    rel = bucket_window_stats([{"calibrated_probability_yes": b, "ticker": c, "label_yes_resolved": a}
                               for a, b, c in pairs])
    tot_w = sum(r["distinct_window_n"] for r in rel) or 1
    wece = sum((r["distinct_window_n"] / tot_w) * abs((r["mean_pred_window"] or 0.0) - (r["window_yes_rate"] or 0.0))
               for r in rel)
    # signed YES over-prediction = mean predicted - realized base rate (window-weighted realized)
    overpred_row = (cs["mean_pred"] - cs["base_rate"]) if (cs["mean_pred"] is not None) else None
    return {
        "n": cs["n"], "mean_pred": cs["mean_pred"], "base_rate": cs["base_rate"],
        "brier": cs["brier"], "log_loss": cs["log_loss"],
        "ece_row": cs["ece"], "ece_window": wece,
        "slope": cs["calibration_slope"], "intercept": cs["calibration_intercept"],
        "yes_overprediction_cents": (overpred_row * 100.0) if overpred_row is not None else None,
        "reliability_window": rel,
    }


def compare_sources(ctx: dict) -> dict:
    """Calibration metrics for every probability source on the held-out TEST windows."""
    y, tk, br = ctx["y_test"], ctx["tickers"], ctx["base_rate"]
    out: dict = {}
    for name, p in ctx["sources"].items():
        out[name] = source_metrics(y, p, tk, br)
    return out


# --------------------------------------------------------------------------- #
# Part G — market-shrink alpha sweep (alpha chosen by OOS calibration, not P&L)
# --------------------------------------------------------------------------- #
def market_shrink_sweep(ctx: dict) -> dict:
    """Sweep alpha for each base; select alpha ONLY by out-of-sample calibration."""
    y, tk, br = ctx["y_test"], ctx["tickers"], ctx["base_rate"]
    market = ctx["sources"]["market_implied"]
    base_probs = {"raw": ctx["sources"]["raw_model"], "platt": ctx["sources"]["staged_platt"],
                  "isotonic": ctx["sources"]["staged_isotonic"]}
    market_m = source_metrics(y, market, tk, br)
    grid: dict = {}
    best: dict = {}
    for base_name, bp in base_probs.items():
        rows_alpha = []
        for a in ALPHA_GRID:
            p = [blend(m_i, k_i, a) if (m_i is not None and k_i is not None) else None
                 for m_i, k_i in zip(bp, market)]
            m = source_metrics(y, p, tk, br)
            rows_alpha.append({"alpha": a, "brier": m["brier"], "log_loss": m["log_loss"],
                               "ece_row": m["ece_row"], "ece_window": m["ece_window"],
                               "yes_overprediction_cents": m["yes_overprediction_cents"]})
        # selection: minimum out-of-sample window ECE (tie-break Brier), among alphas not
        # worse than the market baseline on ECE.
        cand = [r for r in rows_alpha if r["ece_window"] is not None]
        by_ece = min(cand, key=lambda r: (r["ece_window"], r["brier"] if r["brier"] is not None else 9))
        by_brier = min(cand, key=lambda r: (r["brier"] if r["brier"] is not None else 9, r["ece_window"]))
        grid[base_name] = rows_alpha
        best[base_name] = {"best_alpha_by_ece": by_ece["alpha"], "best_alpha_by_brier": by_brier["alpha"],
                           "best_ece_window": by_ece["ece_window"], "best_brier": by_brier["brier"]}
    # conservative recommendation: the base+alpha with the lowest window ECE that also
    # beats (<=) the market baseline's window ECE; else recommend pure-market (alpha 0).
    mkt_ece = market_m["ece_window"]
    flat = [(b, r) for b, rs in grid.items() for r in rs if r["ece_window"] is not None]
    beats_market = [(b, r) for b, r in flat if mkt_ece is None or r["ece_window"] <= mkt_ece + 1e-9]
    if beats_market:
        rec_base, rec_row = min(beats_market, key=lambda br: (br[1]["ece_window"], br[1]["brier"] or 9))
        rec = {"recommended_base": rec_base, "recommended_alpha": rec_row["alpha"],
               "recommended_ece_window": rec_row["ece_window"],
               "beats_market_baseline": True}
    else:
        rec = {"recommended_base": "market_implied", "recommended_alpha": 0.0,
               "recommended_ece_window": mkt_ece, "beats_market_baseline": False,
               "note": "no model/blend beat the market-implied baseline on held-out window ECE."}
    return {"grid": grid, "best_per_base": best, "market_baseline": {
        "ece_window": market_m["ece_window"], "brier": market_m["brier"],
        "log_loss": market_m["log_loss"]}, "recommendation": rec}


def _apply_stability(sweep: dict, stability: dict) -> None:
    """Fold walk-forward stability into the recommendation: pick the MORE conservative
    (lower / more market-weighted) alpha when the main split and folds disagree."""
    rec = sweep["recommendation"]
    main_alpha = rec.get("recommended_alpha")
    wf = [a for a in (stability.get("alpha_values") or []) if isinstance(a, (int, float))]
    wf_med = _median(wf)
    cons = min(main_alpha, wf_med) if (wf_med is not None and main_alpha is not None) else main_alpha
    rec["conservative_alpha"] = cons
    rec["walk_forward_median_alpha"] = wf_med
    if wf_med is not None and main_alpha is not None and abs(main_alpha - wf_med) > 0.2:
        rec["conservative_note"] = (f"main-split alpha={main_alpha} but walk-forward median alpha={wf_med}: the "
                                    "model's marginal value over market is within noise — shrink HEAVILY toward "
                                    "market (use the lower alpha).")
    else:
        rec["conservative_note"] = "alpha consistent across splits; still provisional — shadow-test before promotion."


def alpha_stability(config, *, series: str, embargo_windows: int = 1, n_splits: int = 3) -> dict:
    """Is the best alpha stable across walk-forward folds? (raw->market shrink, OOS ECE)."""
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    feats = MICROSTRUCTURE_FEATURES
    folds = walk_forward_indices(rows, n_splits=n_splits, embargo_windows=embargo_windows)
    per_fold = []
    for k, (tr, vl) in enumerate(folds, 1):
        vl = [i for i in vl if rows[i].get("yes_ask") is not None and rows[i].get("no_ask") is not None]
        if not tr or not vl:
            continue
        p_raw, mdict, idict = fit_predict_logistic(rows, feats, tr, vl)
        y = [int(rows[i]["label_yes_resolved"]) for i in vl]
        tk = [rows[i].get("ticker") for i in vl]
        mkt = [market_implied_yes(rows[i].get("yes_ask"), rows[i].get("no_ask")) for i in vl]
        br = sum(y) / len(y)
        best_a, best_e = None, None
        for a in ALPHA_GRID:
            p = [blend(m_i, k_i, a) for m_i, k_i in zip(p_raw, mkt)]
            e = source_metrics(y, p, tk, br)["ece_window"]
            if e is not None and (best_e is None or e < best_e):
                best_e, best_a = e, a
        per_fold.append({"fold": k, "val_windows": len({rows[i].get("ticker") for i in vl}),
                         "best_alpha": best_a, "best_ece_window": best_e})
    alphas = [f["best_alpha"] for f in per_fold if f["best_alpha"] is not None]
    return {"folds": per_fold, "alpha_values": alphas,
            "alpha_min": (min(alphas) if alphas else None), "alpha_max": (max(alphas) if alphas else None),
            "stable": bool(alphas and (max(alphas) - min(alphas) <= 0.3))}


# --------------------------------------------------------------------------- #
# Part E — candidate-cohort repair audit (re-run the edge policy per source)
# --------------------------------------------------------------------------- #
def _repaired_prob(method: str, *, raw, promoted, market, calibrators, alpha, base) -> Optional[float]:
    if method in ("raw_model", "identity"):
        return raw
    if method == "current_promoted_calibrator":
        return promoted
    if method == "staged_platt":
        return Calibrator.from_dict(calibrators["platt"]).transform([raw])[0] if raw is not None else None
    if method == "staged_isotonic":
        return Calibrator.from_dict(calibrators["isotonic"]).transform([raw])[0] if raw is not None else None
    if method == "market_implied":
        return market
    if method == "market_shrunk":
        if raw is None or market is None:
            return None
        if base == "platt":
            bp = Calibrator.from_dict(calibrators["platt"]).transform([raw])[0]
        elif base == "isotonic":
            bp = Calibrator.from_dict(calibrators["isotonic"]).transform([raw])[0]
        else:
            bp = raw
        return blend(bp, market, alpha)
    return None


def candidate_repair_audit(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                           embargo_windows: int = 1) -> dict:
    """Re-evaluate the latest edge-blocked cohort under each repaired probability source.

    For each source the calibration buffer comes from THAT source's OWN held-out TEST
    reliability buckets — so a better-calibrated source legitimately earns a smaller
    buffer (we never just delete the buffer). Reports whether any source yields positive
    UNCERTAINTY-ADJUSTED edge and whether it does so via genuinely lower bias.
    """
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    lpath = Path(ledger) if ledger else latest_ledger(config)
    if lpath is None or not Path(lpath).exists():
        return {"series": series, "status": "NO_LEDGER", "live_submission_allowed": False,
                "note": "no shadow/paper ledger found"}
    cohort = select_cohort(load_decisions(lpath), "edge_blocked")
    ctx = build_repair_context(config, series=series, embargo_windows=embargo_windows)
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "live_submission_allowed": False}

    sweep = market_shrink_sweep(ctx)
    rec_base = sweep["recommendation"]["recommended_base"]
    rec_alpha = sweep["recommendation"]["recommended_alpha"]
    shrink_base = rec_base if rec_base in ("raw", "platt", "isotonic") else "raw"

    # per-source held-out reliability buckets (for the edge policy's calibration buffer)
    y_test, tickers = ctx["y_test"], ctx["tickers"]
    src_test = dict(ctx["sources"])
    src_test["market_shrunk"] = [blend(
        (ctx["sources"]["staged_platt"][j] if shrink_base == "platt"
         else ctx["sources"]["staged_isotonic"][j] if shrink_base == "isotonic"
         else ctx["sources"]["raw_model"][j]), m, rec_alpha) if m is not None else None
        for j, m in enumerate(ctx["sources"]["market_implied"])]
    buckets_by_method = {}
    for name, p in src_test.items():
        pairs = [(int(yi), pi) for yi, pi in zip(y_test, p) if pi is not None]
        if pairs:
            buckets_by_method[name] = build_calibration_buckets([a for a, _ in pairs], [b for _, b in pairs])
        else:
            buckets_by_method[name] = []

    methods = ["raw_model", "identity", "staged_platt", "staged_isotonic", "market_implied", "market_shrunk"]
    if "current_promoted_calibrator" in ctx["sources"]:
        methods.insert(0, "current_promoted_calibrator")
    calibrators = ctx["calibrators"]

    per_method: dict = {}
    per_row_records: list[dict] = []
    for method in methods:
        buckets = buckets_by_method.get(method, [])
        recs = []
        for d in cohort:
            raw = d.get("model_probability_yes")
            promoted = d.get("calibrated_probability_yes")
            ya, na = d.get("executable_yes_price"), d.get("executable_no_price")
            mkt = market_implied_yes(ya, na)
            p = _repaired_prob(method, raw=raw, promoted=promoted, market=mkt,
                               calibrators=calibrators, alpha=rec_alpha, base=shrink_base)
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
            bucket_real = None
            for b in buckets:
                if b.lo <= p < b.hi or (p >= b.hi and b.hi >= 1.0):
                    bucket_real = b.mean_actual
                    break
            reduces_over = None
            if bucket_real is not None and promoted is not None:
                reduces_over = abs(p - bucket_real) < abs(promoted - bucket_real)
            rec = {"method": method, "ticker": d.get("ticker"), "as_of_ts_ms": d.get("as_of_ts_ms"),
                   "repaired_p": p, "promoted_p": promoted, "market_p": mkt, "side": dec.side,
                   "raw_edge_cents": dec.raw_edge_cents, "cost_adjusted_edge_cents": dec.cost_adjusted_edge_cents,
                   "uncertainty_adjusted_edge_cents": dec.uncertainty_adjusted_edge_cents,
                   "final_policy_edge_cents": dec.final_policy_edge_cents, "state": dec.state,
                   "calib_buffer_cents": dec.calibration_uncertainty_buffer_cents,
                   "model_unc_buffer_cents": dec.model_uncertainty_buffer_cents,
                   "bucket_realized": bucket_real, "reduces_yes_overprediction": reduces_over}
            recs.append(rec)
            per_row_records.append(rec)
        n = len(recs)
        per_method[method] = {
            "n_rows": n,
            "n_pos_raw_edge": sum(1 for r in recs if (r["raw_edge_cents"] or -9) > 0),
            "n_pos_cost_adjusted": sum(1 for r in recs if (r["cost_adjusted_edge_cents"] or -9) > 0),
            "n_pos_uncertainty_adjusted": sum(1 for r in recs if (r["uncertainty_adjusted_edge_cents"] or -9) > 0),
            "n_pass_final_edge": sum(1 for r in recs if r["state"] == "EDGE_OK"),
            "median_raw_edge_cents": _median([r["raw_edge_cents"] for r in recs]),
            "median_final_edge_cents": _median([r["final_policy_edge_cents"] for r in recs]),
            "best_final_edge_cents": max((r["final_policy_edge_cents"] for r in recs
                                          if r["final_policy_edge_cents"] is not None), default=None),
            "median_calib_buffer_cents": _median([r["calib_buffer_cents"] for r in recs]),
            "n_market_beats_model": sum(1 for r in recs if r["market_p"] is not None
                                        and r["bucket_realized"] is not None
                                        and abs(r["market_p"] - r["bucket_realized"])
                                        < abs((r["promoted_p"] or 9) - r["bucket_realized"])),
            "n_reduces_yes_overprediction": sum(1 for r in recs if r["reduces_yes_overprediction"]),
        }
    return {"series": series, "status": "OK", "ledger": str(lpath), "n_cohort": len(cohort),
            "shrink_base": shrink_base, "shrink_alpha": rec_alpha, "split": ctx["split"],
            "per_method": per_method, "per_row_records": per_row_records,
            "recommendation": sweep["recommendation"], "live_submission_allowed": False}


# --------------------------------------------------------------------------- #
# Part F — executable backtest comparison (held-out TEST windows)
# --------------------------------------------------------------------------- #
def repair_backtest(config, ctx: dict, *, shrink_base: str, shrink_alpha: float) -> dict:
    """Executable backtest (asks/fees/depth/gates) for each repaired probability source."""
    rows, test_idx = ctx["rows"], ctx["test_idx"]
    params = BacktestParams.from_config(config)
    fee_model = KalshiFeeModel.from_config(config)
    market = ctx["sources"]["market_implied"]
    base_p = (ctx["sources"]["staged_platt"] if shrink_base == "platt"
              else ctx["sources"]["staged_isotonic"] if shrink_base == "isotonic"
              else ctx["sources"]["raw_model"])
    method_probs = {
        "raw_model": ctx["sources"]["raw_model"], "staged_platt": ctx["sources"]["staged_platt"],
        "staged_isotonic": ctx["sources"]["staged_isotonic"], "market_implied": market,
        "market_shrunk": [blend(b, m, shrink_alpha) if m is not None else None
                          for b, m in zip(base_p, market)],
    }
    if "current_promoted_calibrator" in ctx["sources"]:
        method_probs["current_promoted_calibrator"] = ctx["sources"]["current_promoted_calibrator"]
    out: dict = {}
    for name, probs in method_probs.items():
        arows = _attach(rows, test_idx, [p if p is not None else None for p in probs])
        agg = simulate_backtest(arows, params=params, fee_model=fee_model, diagnostic=True,
                                model_version=name)
        out[name] = {k: agg.get(k) for k in (
            "total_simulated_trades", "windows_touched", "net_pnl", "gross_pnl", "hit_rate",
            "max_drawdown", "avg_net_edge", "profit_factor", "pnl_by_side")}
    return out


# --------------------------------------------------------------------------- #
# Part H — staged artifacts (NEVER promoted; staged dir only)
# --------------------------------------------------------------------------- #
def stage_platt_calibrator(config, ctx: dict, *, series: str) -> Optional[dict]:
    """Save a STAGED Platt calibrator fit on the held-out CALIB windows (non-promoted)."""
    if not ctx.get("applied"):
        return None
    metrics_before = {k: source_metrics(ctx["y_test"], ctx["sources"]["raw_model"], ctx["tickers"],
                                        ctx["base_rate"]).get(k) for k in ("brier", "log_loss")}
    metrics_before["ece"] = source_metrics(ctx["y_test"], ctx["sources"]["raw_model"], ctx["tickers"],
                                            ctx["base_rate"]).get("ece_row")
    m_after = source_metrics(ctx["y_test"], ctx["sources"]["staged_platt"], ctx["tickers"], ctx["base_rate"])
    art = build_calibrator_artifact(
        calibrator=Calibrator.from_dict(ctx["calibrators"]["platt"]), method="platt",
        model_name="microstructure_logistic",
        split_metadata={k: ctx["split"].get(k) for k in ("train_windows", "calib_windows", "test_windows")},
        metrics_before=metrics_before,
        metrics_after={"brier": m_after["brier"], "log_loss": m_after["log_loss"], "ece": m_after["ece_row"]},
        tradable=False, gate_windows=ctx["gate_windows"], is_staged=True,
        created_by_command="kalshi-probability-repair", series=series,
        calibration_window_count=ctx["split"].get("calib_windows"),
        test_window_count=ctx["split"].get("test_windows"),
        notes="STAGED probability-repair candidate (Platt). NON-PROMOTED; report-only.")
    art["tradable_status"] = STAGED_NON_PROMOTED
    art["artifact_type"] = "probability_repair"
    paths = save_calibrator(config, art, stem=f"kalshi_repair_platt_{_ts()}", staged=True)
    return {**paths, "method": "platt", "tradable_status": STAGED_NON_PROMOTED}


def stage_market_shrink_blender(config, ctx: dict, sweep: dict, *, series: str) -> Optional[dict]:
    """Save a STAGED market-shrink blender descriptor (DIAGNOSTIC_ONLY; non-promoted)."""
    rec = sweep["recommendation"]
    promo = load_active_promotion(config, series=series)
    artifact = {
        "artifact_type": "probability_repair",
        "method": "market_shrink",
        "blender": {"formula": "alpha*p_model + (1-alpha)*p_market",
                    "alpha": rec.get("recommended_alpha"), "base": rec.get("recommended_base")},
        "alpha": rec.get("recommended_alpha"),
        "base": rec.get("recommended_base"),
        "input_model_path": promo.get("model_path"),
        "input_calibrator_path": promo.get("calibrator_path"),
        "staged_calibrators": ctx.get("calibrators"),
        "market_implied_source": "executable Kalshi YES/NO asks: ya/(ya+na)",
        "split_metadata": {k: ctx["split"].get(k) for k in (
            "train_windows", "calib_windows", "test_windows", "embargo_windows")},
        "metrics": {"recommended_ece_window": rec.get("recommended_ece_window"),
                    "market_baseline": sweep.get("market_baseline"),
                    "beats_market_baseline": rec.get("beats_market_baseline")},
        "is_staged": True, "is_promoted": False, "promotion_required": True,
        "tradable_status": DIAGNOSTIC_ONLY,
        "tradable": False, "is_diagnostic": True, "live_approved": False,
        "calibration_status": "diagnostic",
        "model_name": "microstructure_logistic",
        "series": series, "created_by_command": "kalshi-probability-repair",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": "STAGED market-shrink blender; DIAGNOSTIC_ONLY; NEVER promoted; runtime never loads it.",
    }
    d = staged_models_dir(config)
    stem = f"kalshi_repair_market_shrink_{_ts()}"
    pkl = d / f"{stem}.pkl"
    with pkl.open("wb") as fh:
        pickle.dump(artifact, fh)
    js = d / f"{stem}.json"
    summary = {k: v for k, v in artifact.items() if k != "staged_calibrators"}
    js.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return {"artifact_file": str(pkl), "summary_file": str(js), "method": "market_shrink",
            "tradable_status": DIAGNOSTIC_ONLY,
            "tradable_status_for_check": tradable_status_for(is_diagnostic=True, is_staged=True, is_promoted=False)}


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _write_compare_reports(config, ctx: dict, metrics: dict) -> dict:
    d = config.reports_path() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_calibration_compare_{stamp}.md"
    csvp = d / f"kalshi_calibration_compare_{stamp}.csv"
    order = ["raw_model", "identity", "staged_platt", "staged_isotonic", "market_implied",
             "current_promoted_calibrator"]
    order = [m for m in order if m in metrics]
    lines = [
        f"# Kalshi calibration comparison — {ctx['series']}", "",
        "> STAGED / report-only. Held-out TEST windows (purged/embargoed). Distinct-window ECE is the "
        "PRIMARY diagnostic (row ECE is less independent). `current_promoted_calibrator` is REFERENCE ONLY "
        "(may be in-sample on some TEST windows). No promotion; live disabled.", "",
        f"- split (windows): {ctx['split']}  gate_windows: {ctx['gate_windows']}  base_rate(TEST): {_f(ctx['base_rate'])}",
        "", "| source | n | brier | log_loss | ECE(row) | **ECE(window)** | slope | YES_overpred(c) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in order:
        m = metrics[name]
        lines.append(f"| {name} | {m.get('n')} | {_f(m.get('brier'))} | {_f(m.get('log_loss'))} | "
                     f"{_f(m.get('ece_row'))} | **{_f(m.get('ece_window'))}** | {_f(m.get('slope'))} | "
                     f"{_f(m.get('yes_overprediction_cents'),2)} |")
    # which is best?
    cmp = {n: metrics[n].get("ece_window") for n in order if metrics[n].get("ece_window") is not None
           and n != "current_promoted_calibrator"}
    best = min(cmp, key=cmp.get) if cmp else None
    iso = metrics.get("staged_isotonic", {}).get("ece_window")
    platt = metrics.get("staged_platt", {}).get("ece_window")
    ident = metrics.get("identity", {}).get("ece_window")
    mkt = metrics.get("market_implied", {}).get("ece_window")
    lines += ["", "## Findings (held-out window ECE; lower = better)",
              f"- best source: **{best}**",
              f"- Platt vs isotonic: platt={_f(platt)} isotonic={_f(iso)} -> "
              f"**{'Platt better' if (platt is not None and iso is not None and platt < iso) else 'isotonic not beaten by Platt' if (platt is not None and iso is not None) else 'n/a'}**",
              f"- identity(raw) vs isotonic: identity={_f(ident)} isotonic={_f(iso)} -> "
              f"**{'identity better' if (ident is not None and iso is not None and ident < iso) else 'isotonic better' if (ident is not None and iso is not None) else 'n/a'}**",
              f"- market-implied vs model: market={_f(mkt)} best_model={_f(cmp.get(best)) if best else 'n/a'} -> "
              f"**{'market better' if (mkt is not None and best and mkt < cmp.get(best)) else 'model better-or-equal'}**",
              "", "## Safety",
              "- STAGED/report-only; no artifact promoted; no manifest changed; live disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "n", "brier", "log_loss", "ece_row", "ece_window", "slope",
                    "intercept", "mean_pred", "base_rate", "yes_overprediction_cents"])
        for name in order:
            m = metrics[name]
            w.writerow([name, m.get("n"), m.get("brier"), m.get("log_loss"), m.get("ece_row"),
                        m.get("ece_window"), m.get("slope"), m.get("intercept"), m.get("mean_pred"),
                        m.get("base_rate"), m.get("yes_overprediction_cents")])
    return {"compare_md": str(md), "compare_csv": str(csvp), "best_source": best}


def _write_shrink_reports(config, ctx: dict, sweep: dict, stability: dict) -> dict:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_market_shrink_sweep_{stamp}.md"
    csvp = d / f"kalshi_market_shrink_sweep_{stamp}.csv"
    rec = sweep["recommendation"]
    lines = [
        f"# Kalshi market-shrink alpha sweep — {ctx['series']}", "",
        "> STAGED / report-only. `p = alpha*p_model + (1-alpha)*p_market`. alpha selected ONLY by "
        "out-of-sample window ECE (never in-sample P&L). No promotion; live disabled.", "",
        f"- split (windows): {ctx['split']}  base_rate(TEST): {_f(ctx['base_rate'])}",
        f"- market-implied baseline: ECE(window)={_f(sweep['market_baseline']['ece_window'])} "
        f"brier={_f(sweep['market_baseline']['brier'])}",
        f"- **recommended: base={rec['recommended_base']} alpha={rec['recommended_alpha']} "
        f"(ECE_window={_f(rec.get('recommended_ece_window'))}, beats_market={rec.get('beats_market_baseline')})**",
        f"- alpha stability across folds: stable={stability.get('stable')} "
        f"alphas={stability.get('alpha_values')} (min={stability.get('alpha_min')} max={stability.get('alpha_max')})",
        f"- **conservative alpha (stability-aware): {rec.get('conservative_alpha')}** — "
        f"{rec.get('conservative_note', '')}",
        "", "## alpha sweep by base (ECE window; lower=better). alpha=0 is pure market, alpha=1 is pure model.",
    ]
    for base_name, rows_alpha in sweep["grid"].items():
        lines += [f"", f"### base = {base_name}",
                  "| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |",
                  "|---|---|---|---|---|---|"]
        for r in rows_alpha:
            lines.append(f"| {r['alpha']} | {_f(r['brier'])} | {_f(r['log_loss'])} | {_f(r['ece_row'])} | "
                         f"{_f(r['ece_window'])} | {_f(r['yes_overprediction_cents'],2)} |")
    lines += ["", "## Safety", "- STAGED/report-only; alpha not promoted; no manifest changed; live disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["base", "alpha", "brier", "log_loss", "ece_row", "ece_window", "yes_overprediction_cents"])
        for base_name, rows_alpha in sweep["grid"].items():
            for r in rows_alpha:
                w.writerow([base_name, r["alpha"], r["brier"], r["log_loss"], r["ece_row"],
                            r["ece_window"], r["yes_overprediction_cents"]])
    return {"shrink_md": str(md), "shrink_csv": str(csvp)}


def _write_candidate_reports(config, res: dict) -> dict:
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_candidate_repair_audit_{stamp}.md"
    csvp = d / f"kalshi_candidate_repair_audit_{stamp}.csv"
    pm = res["per_method"]
    order = [m for m in ("current_promoted_calibrator", "raw_model", "identity", "staged_platt",
                         "staged_isotonic", "market_implied", "market_shrunk") if m in pm]
    lines = [
        f"# Kalshi candidate-cohort repair audit — {res['series']}", "",
        "> STAGED / report-only. Re-runs the SAME edge policy on the edge-blocked cohort under each "
        "repaired probability. The calibration buffer for each source uses that source's OWN held-out "
        "TEST reliability — a better-calibrated source earns a smaller buffer; the buffer is NEVER removed. "
        "No promotion; live disabled.", "",
        f"- ledger: `{res['ledger']}`  cohort_rows: {res['n_cohort']}",
        f"- market-shrink applied: base={res['shrink_base']} alpha={res['shrink_alpha']}",
        "", "| source | n | +raw | +cost_adj | **+unc_adj** | pass_final | med_final(c) | best_final(c) | "
        "med_calib_buf(c) | reduces_YES_overpred |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in order:
        m = pm[name]
        lines.append(f"| {name} | {m['n_rows']} | {m['n_pos_raw_edge']} | {m['n_pos_cost_adjusted']} | "
                     f"**{m['n_pos_uncertainty_adjusted']}** | {m['n_pass_final_edge']} | "
                     f"{_f(m['median_final_edge_cents'],2)} | {_f(m['best_final_edge_cents'],2)} | "
                     f"{_f(m['median_calib_buffer_cents'],2)} | {m['n_reduces_yes_overprediction']} |")
    any_pass = any(pm[n]["n_pass_final_edge"] > 0 for n in order)
    any_unc = any(pm[n]["n_pos_uncertainty_adjusted"] > 0 for n in order)
    # REPAIRED-only verdict excludes the unchanged promoted REFERENCE column (not a repair).
    repaired = [n for n in order if n != "current_promoted_calibrator"]
    any_repaired_pass = any(pm[n]["n_pass_final_edge"] > 0 for n in repaired)
    any_repaired_unc = any(pm[n]["n_pos_uncertainty_adjusted"] > 0 for n in repaired)
    best_repaired_final = max((pm[n]["best_final_edge_cents"] for n in repaired
                               if pm[n]["best_final_edge_cents"] is not None), default=None)
    lines += ["", "## Verdict",
              f"- any REPAIRED source passes the FULL edge policy on the cohort: **{any_repaired_pass}**  "
              f"(best repaired final edge = {_f(best_repaired_final,2)}c)",
              f"- any REPAIRED source yields positive UNCERTAINTY-ADJUSTED edge: **{any_repaired_unc}**",
              f"- (reference: the unchanged promoted calibrator passes {pm.get('current_promoted_calibrator',{}).get('n_pass_final_edge',0)} "
              "row(s) — NOT a repair; shown for context only.)",
              "- Honest reading: a better-calibrated source legitimately SHRINKS the buffer (lower bias) and "
              "reduces YES over-prediction, but that is only worth shadow testing if it ALSO clears the final "
              "profit gate with positive uncertainty-adjusted edge — NOT merely break-even, and NOT by removing "
              "the buffer.",
              "", "## Safety", "- STAGED/report-only; cohort re-evaluation only; no promotion; live disabled."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        cols = ["method", "ticker", "as_of_ts_ms", "repaired_p", "promoted_p", "market_p", "side",
                "raw_edge_cents", "cost_adjusted_edge_cents", "uncertainty_adjusted_edge_cents",
                "final_policy_edge_cents", "state", "calib_buffer_cents", "model_unc_buffer_cents",
                "bucket_realized", "reduces_yes_overprediction"]
        w.writerow(cols)
        for r in res["per_row_records"]:
            w.writerow([r.get(c) for c in cols])
    return {"candidate_md": str(md), "candidate_csv": str(csvp),
            "any_pass": any_pass, "any_positive_uncertainty_adjusted": any_unc,
            "any_repaired_pass": any_repaired_pass,
            "any_repaired_positive_uncertainty_adjusted": any_repaired_unc,
            "best_repaired_final_cents": best_repaired_final}


# --------------------------------------------------------------------------- #
# Top-level runners (CLI entry points)
# --------------------------------------------------------------------------- #
def run_calibration_compare(config, *, series: str = "KXBTC15M", staged: bool = True,
                            embargo_windows: int = 1) -> dict:
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    ctx = build_repair_context(config, series=series, embargo_windows=embargo_windows)
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "live_submission_allowed": False}
    metrics = compare_sources(ctx)
    reports = _write_compare_reports(config, ctx, metrics)
    verify = verify_runtime_unchanged(config, snap)
    return {"series": series, "status": "OK", "split": ctx["split"], "gate_windows": ctx["gate_windows"],
            "metrics": {k: {kk: vv for kk, vv in v.items() if kk != "reliability_window"}
                        for k, v in metrics.items()},
            "reports": reports, "preservation_manifest": preservation,
            "runtime_unchanged": verify["unchanged"], "runtime_diff": verify,
            "live_submission_allowed": False}


def run_market_shrink_sweep(config, *, series: str = "KXBTC15M", staged: bool = True,
                            embargo_windows: int = 1, save_artifact: bool = True) -> dict:
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    ctx = build_repair_context(config, series=series, embargo_windows=embargo_windows)
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "live_submission_allowed": False}
    sweep = market_shrink_sweep(ctx)
    stability = alpha_stability(config, series=series, embargo_windows=embargo_windows)
    _apply_stability(sweep, stability)
    reports = _write_shrink_reports(config, ctx, sweep, stability)
    staged_artifact = stage_market_shrink_blender(config, ctx, sweep, series=series) if save_artifact else None
    verify = verify_runtime_unchanged(config, snap)
    return {"series": series, "status": "OK", "split": ctx["split"],
            "recommendation": sweep["recommendation"], "best_per_base": sweep["best_per_base"],
            "market_baseline": sweep["market_baseline"], "alpha_stability": stability,
            "reports": reports, "staged_artifact": staged_artifact,
            "preservation_manifest": preservation, "runtime_unchanged": verify["unchanged"],
            "runtime_diff": verify, "live_submission_allowed": False}


def run_candidate_repair_audit(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                               embargo_windows: int = 1) -> dict:
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    res = candidate_repair_audit(config, series=series, ledger=ledger, embargo_windows=embargo_windows)
    if res.get("status") != "OK":
        res["preservation_manifest"] = preservation
        res["runtime_unchanged"] = verify_runtime_unchanged(config, snap)["unchanged"]
        return res
    reports = _write_candidate_reports(config, res)
    verify = verify_runtime_unchanged(config, snap)
    res_out = {k: v for k, v in res.items() if k != "per_row_records"}
    res_out.update(reports=reports, preservation_manifest=preservation,
                   runtime_unchanged=verify["unchanged"], runtime_diff=verify)
    return res_out


def run_probability_repair(config, *, series: str = "KXBTC15M", staged: bool = True,
                           embargo_windows: int = 1, ledger: Optional[str] = None) -> dict:
    """Umbrella: calibration compare + market-shrink sweep + cohort repair + backtest + staged artifacts.

    Everything is STAGED/report-only. Snapshots and re-verifies the promoted/active runtime
    state; aborts the summary with a loud flag if anything changed (it never should)."""
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    ctx = build_repair_context(config, series=series, embargo_windows=embargo_windows)
    if not ctx.get("applied"):
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": ctx.get("reason"),
                "preservation_manifest": preservation, "live_submission_allowed": False}

    metrics = compare_sources(ctx)
    compare_reports = _write_compare_reports(config, ctx, metrics)
    sweep = market_shrink_sweep(ctx)
    stability = alpha_stability(config, series=series, embargo_windows=embargo_windows)
    _apply_stability(sweep, stability)
    shrink_reports = _write_shrink_reports(config, ctx, sweep, stability)
    rec = sweep["recommendation"]
    shrink_base = rec["recommended_base"] if rec["recommended_base"] in SHRINK_BASES else "raw"
    backtest = repair_backtest(config, ctx, shrink_base=shrink_base, shrink_alpha=rec["recommended_alpha"])
    cohort = candidate_repair_audit(config, series=series, ledger=ledger, embargo_windows=embargo_windows)
    cohort_reports = _write_candidate_reports(config, cohort) if cohort.get("status") == "OK" else {}

    staged_platt = stage_platt_calibrator(config, ctx, series=series) if staged else None
    staged_blender = stage_market_shrink_blender(config, ctx, sweep, series=series) if staged else None

    # main combined report under reports/models/
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    main_md = d / f"kalshi_probability_repair_{_ts()}.md"
    bt_lines = [f"  - {n}: trades={a['total_simulated_trades']} windows={a['windows_touched']} "
                f"net_pnl={_f(a['net_pnl'],4)} hit_rate={_f(a['hit_rate'])} dd={_f(a['max_drawdown'],4)}"
                for n, a in backtest.items()]
    verify = verify_runtime_unchanged(config, snap)
    cohort_pm = cohort.get("per_method", {}) if cohort.get("status") == "OK" else {}
    any_repaired_pass = cohort_reports.get("any_repaired_pass")
    best_repaired = cohort_reports.get("best_repaired_final_cents")
    promoted_ref_pass = cohort_pm.get("current_promoted_calibrator", {}).get("n_pass_final_edge", 0)
    lines = [
        f"# Kalshi probability repair — {series}", "",
        "> STAGED / report-only. Tests whether better-calibrated or market-shrunk probabilities honestly "
        "reduce the edge-policy calibration buffer. No promotion; no manifest change; live disabled.", "",
        f"- split (windows): {ctx['split']}  gate_windows: {ctx['gate_windows']}  base_rate(TEST): {_f(ctx['base_rate'])}",
        f"- runtime state UNCHANGED after all work: **{verify['unchanged']}** (preservation: {preservation})",
        "", "## Calibration comparison (held-out window ECE; lower=better)",
        f"- best source: **{compare_reports.get('best_source')}**  (full table: {compare_reports['compare_md']})",
    ]
    for name, m in metrics.items():
        lines.append(f"  - {name}: ECE_window={_f(m.get('ece_window'))} brier={_f(m.get('brier'))} "
                     f"YES_overpred={_f(m.get('yes_overprediction_cents'),2)}c")
    lines += ["", "## Market-shrink recommendation",
              f"- base={rec['recommended_base']} alpha={rec['recommended_alpha']} "
              f"beats_market={rec.get('beats_market_baseline')} stable={stability.get('stable')}",
              "", "## Executable backtest (held-out TEST; asks/fees/depth/gates)"] + bt_lines
    lines += ["", "## Candidate-cohort repair",
              f"- any REPAIRED source passes full edge policy: **{any_repaired_pass}** "
              f"(best repaired final {_f(best_repaired,2)}c; promoted-reference passes {promoted_ref_pass} row(s))  "
              f"(detail: {cohort_reports.get('candidate_md')})"]
    for n, v in cohort_pm.items():
        lines.append(f"  - {n}: +unc_adj={v['n_pos_uncertainty_adjusted']}/{v['n_rows']} "
                     f"pass={v['n_pass_final_edge']} med_final={_f(v['median_final_edge_cents'],2)}c "
                     f"med_calib_buf={_f(v['median_calib_buffer_cents'],2)}c")
    lines += ["", "## Staged artifacts (NON-PROMOTED; data/models/staged/ only)",
              f"- platt: {staged_platt}", f"- market_shrink: {staged_blender}",
              "", "## Safety",
              "- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.",
              f"- Promoted manifest + artifacts + active pointers UNCHANGED: {verify['unchanged']}.",
              "- No paper/live enabled; no gates weakened; no buffers removed; live_submission_allowed=false."]
    main_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "series": series, "status": "OK", "split": ctx["split"], "gate_windows": ctx["gate_windows"],
        "calibration_compare": compare_reports, "market_shrink": {**shrink_reports, "recommendation": rec,
                                                                  "stability": stability},
        "backtest": backtest, "candidate": {**cohort_reports,
                                            "per_method": cohort_pm},
        "staged_artifacts": {"platt": staged_platt, "market_shrink": staged_blender},
        "reports": {"main_md": str(main_md), **compare_reports, **shrink_reports, **cohort_reports},
        "preservation_manifest": preservation, "runtime_unchanged": verify["unchanged"],
        "runtime_diff": verify, "live_submission_allowed": False}
