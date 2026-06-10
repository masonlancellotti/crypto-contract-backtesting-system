"""Market-implied RESIDUAL alpha research (STAGED / report-only; NEVER live/paper).

The model has lost to the Kalshi price at predicting YES directly. The real question is
whether any feature predicts the RESIDUAL of the executable market price:

    residual = y - p_market      (p_market = ya / (ya + na), executable asks, never midpoint)

Every model here uses p_market as the BASELINE and only learns an incremental correction
``residual_hat``; ``p_repaired = clip(p_market + residual_hat)``. A residual model is only
interesting if it beats market-implied OUT-OF-SAMPLE (lower Brier/log-loss/ECE, non-zero IC)
AND produces positive final edge across MULTIPLE distinct windows through the unchanged
confidence-aware edge policy (buffers intact, +2c gate intact, distinct-window reliability).

Safety: reads recorded data + the promoted model only to READ; writes staged artifacts +
reports only; never trades, promotes, changes the manifest/active pointers, weakens a gate,
or removes a buffer. ``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import csv
import json
import math
import pickle
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .edge_policy import EdgeInputs, EdgePolicyConfig, evaluate_edge
from .executable_backtest import BacktestParams, _attach, market_implied_probs, simulate_backtest
from .feature_schema import SCHEMA, feature_vector, training_feature_names
from .fees import KalshiFeeModel
from .model_artifacts import (
    DIAGNOSTIC_ONLY, STAGED_NON_PROMOTED, staged_models_dir, tradable_status_for,
)
from .model_dataset import build_model_dataset
from .paper_promotion import load_active_promotion, sha256_file
from .probability_repair import (
    market_implied_yes, snapshot_runtime_state, source_metrics, verify_runtime_unchanged,
    write_preservation_manifest,
)
from .splits import three_way_window_split, walk_forward_indices
from .uncertainty import build_calibration_buckets, build_window_calibration_buckets

try:
    import numpy as np
    from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
    _SK = True
except Exception:  # noqa: BLE001
    _SK = False
try:
    from ...models.sklearn_models import LIGHTGBM_AVAILABLE
except Exception:  # noqa: BLE001
    LIGHTGBM_AVAILABLE = False

EPS = 1e-4


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _median(xs):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _f(x, nd=4):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _clip(p, lo=EPS, hi=1 - EPS):
    return max(lo, min(hi, p))


def _logit(p):
    p = _clip(p)
    return math.log(p / (1.0 - p))


def _spearman(a: list, b: list) -> Optional[float]:
    """Spearman rank correlation (IC). None if degenerate."""
    pairs = [(x, y) for x, y in zip(a, b) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if len(pairs) < 3:
        return None

    def _rank(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = _rank([p[0] for p in pairs]), _rank([p[1] for p in pairs])
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return (cov / (va * vb)) if (va > 0 and vb > 0) else None


# --------------------------------------------------------------------------- #
# Feature groups (Part D ablations)
# --------------------------------------------------------------------------- #
def _group_feats(*groups) -> list[str]:
    allowed = set(training_feature_names())
    return [s.name for s in SCHEMA if s.group in groups and s.name in allowed]


def feature_groups() -> dict:
    return {
        "market_only": [],
        "market+time": _group_feats("A"),
        "market+kalshi_book": _group_feats("B"),
        "market+underlying": _group_feats("C", "D", "E"),
        "market+deribit": _group_feats("F"),
        "market+all": sorted(set(training_feature_names())),
    }


ALL_FEATS = sorted(set(training_feature_names()))


# --------------------------------------------------------------------------- #
# Part B/C — residual rows + dataset
# --------------------------------------------------------------------------- #
def residual_targets(y: int, ya: float, na: float, fee_model) -> Optional[dict]:
    """Pure residual-target math for one executable row (no midpoint, fees subtracted).

    residual = y - p_market; realized YES/NO edge = (settle - executable ask) - fee.
    Returns None when there is no executable YES ask.
    """
    p_market = market_implied_yes(ya, na)
    if p_market is None:
        return None
    y = int(y)
    fee_yes = fee_model.per_contract_fee(ya)
    fee_no = fee_model.per_contract_fee(na)
    edge_yes = y - ya - fee_yes
    edge_no = (1 - y) - na - fee_no
    return {"y": y, "p_market": p_market, "logit_market": _logit(p_market),
            "residual": y - p_market, "residual_positive": 1 if (y - p_market) > 0 else 0,
            "edge_realized_yes": edge_yes, "edge_realized_no": edge_no,
            "candidate_pnl_label": 1 if max(edge_yes, edge_no) > 0 else 0,
            "best_realized_edge": max(edge_yes, edge_no)}


def build_residual_rows(config, *, series: str) -> tuple:
    """Per labelled executable row: market-implied prob, residual target, realized edges."""
    ds = build_model_dataset(config, series=series)
    fee_model = KalshiFeeModel.from_config(config)
    rows = []
    for r in ds["rows"]:
        ya, na = r.get("yes_ask"), r.get("no_ask")
        y = r.get("label_yes_resolved")
        if ya is None or na is None or y is None:
            continue
        t = residual_targets(int(y), ya, na, fee_model)
        if t is None:
            continue
        out = dict(r)                                    # carries all schema feature columns
        out.update(t)
        out.update({"time_to_close_bucket": _ttc_bucket(r.get("seconds_to_close")),
                    "price_bucket": _price_bucket(t["p_market"]), "window_id": r.get("ticker")})
        rows.append(out)
    return rows, fee_model, ds.get("distinct_windows")


def _ttc_bucket(secs) -> str:
    if secs is None:
        return "na"
    return ("<60s" if secs < 60 else "60-180s" if secs < 180 else "180-300s" if secs < 300
            else "300-600s" if secs < 600 else "600-900s")


def _price_bucket(p) -> str:
    if p is None:
        return "na"
    b = min(9, max(0, int(p * 10)))
    return f"[{b/10:.1f},{(b+1)/10:.1f})"


def _residual_dataset_metadata(rows, distinct_windows) -> dict:
    y = [r["y"] for r in rows]
    pm = [r["p_market"] for r in rows]
    res = [r["residual"] for r in rows]
    tk = [r["window_id"] for r in rows]
    edges = [r["best_realized_edge"] for r in rows]
    n = len(rows) or 1
    mean_res = sum(res) / n
    std_res = math.sqrt(sum((x - mean_res) ** 2 for x in res) / n) if rows else None
    by_ttc = Counter(r["time_to_close_bucket"] for r in rows)
    by_price = Counter(r["price_bucket"] for r in rows)
    return {
        "n_rows": len(rows), "distinct_windows": len(set(tk)),
        "dataset_distinct_windows": distinct_windows,
        "label_balance": {"YES": sum(y), "NO": len(y) - sum(y)},
        "base_rate": (sum(y) / n) if rows else None,
        "residual_mean": mean_res, "residual_std": std_res,
        "market_implied_calibration": {k: source_metrics(y, pm, tk, (sum(y) / n) if rows else None).get(k)
                                       for k in ("brier", "log_loss", "ece_row", "ece_window")},
        "realized_edge_yes_mean": (sum(r["edge_realized_yes"] for r in rows) / n) if rows else None,
        "realized_edge_no_mean": (sum(r["edge_realized_no"] for r in rows) / n) if rows else None,
        "candidate_pnl_positive_rows": sum(r["candidate_pnl_label"] for r in rows),
        "best_realized_edge_mean": (sum(edges) / n) if rows else None,
        "rows_by_time_to_close": dict(by_ttc.most_common()),
        "rows_by_price_bucket": dict(sorted(by_price.items())),
        "leakage_excluded_from_features": "see feature_schema.LEAKAGE_EXCLUDED; "
            "label/result/levels never enter features; p_market uses executable asks (no midpoint).",
    }


_DATASET_COLS = ["series", "window_id", "ticker", "as_of_ts_ms", "market_close_ts_ms",
                 "seconds_to_close", "y", "yes_ask", "no_ask", "p_market", "logit_market",
                 "residual", "residual_positive", "edge_realized_yes", "edge_realized_no",
                 "candidate_pnl_label", "best_realized_edge", "time_to_close_bucket",
                 "price_bucket", "coinbase_stale", "binance_stale"]


def run_build_residual_dataset(config, *, series: str = "KXBTC15M") -> dict:
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    rows, _fee, dw = build_residual_rows(config, series=series)
    meta = _residual_dataset_metadata(rows, dw)
    d = staged_models_dir(config)
    stamp = _ts()
    base = d / f"kalshi_residual_dataset_{stamp}"
    cols = _DATASET_COLS + ALL_FEATS
    fmt, data_path = _write_dataset(base, rows, cols)
    meta_path = str(base) + ".metadata.json"
    Path(meta_path).write_text(json.dumps({
        "artifact_type": "residual_alpha_dataset", "series": series, "format": fmt,
        "uses_market_baseline": True, "target": "residual_vs_market (y - p_market)",
        "is_staged": True, "is_promoted": False, "live_approved": False,
        "tradable_status": DIAGNOSTIC_ONLY, "promotion_required": True,
        "created_by_command": "kalshi-build-residual-dataset",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": ALL_FEATS, **meta}, indent=2, default=str), encoding="utf-8")
    report = _write_dataset_report(config, series, meta, data_path)
    verify = verify_runtime_unchanged(config, snap)
    return {"series": series, "status": "OK", "dataset_file": data_path, "metadata_file": meta_path,
            "report": report, "format": fmt, "metadata": meta, "preservation_manifest": preservation,
            "runtime_unchanged": verify["unchanged"], "live_submission_allowed": False}


def _write_dataset(base: Path, rows: list[dict], cols: list[str]) -> tuple:
    try:
        import pandas as pd  # noqa
        import pyarrow  # noqa
        df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows])
        path = str(base) + ".parquet"
        df.to_parquet(path, index=False)
        return "parquet", path
    except Exception:  # noqa: BLE001 — safe fallback, never add a fragile dep
        path = str(base) + ".jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps({c: r.get(c) for c in cols}, default=str) + "\n")
        return "jsonl", path


def _write_dataset_report(config, series, meta, data_path) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_residual_dataset_report_{_ts()}.md"
    mc = meta["market_implied_calibration"]
    lines = [
        f"# Kalshi residual-alpha dataset report — {series}", "",
        "> STAGED / report-only. Target = residual = y - p_market (executable asks; no midpoint). "
        "No promotion; live/paper disabled.", "",
        f"- dataset_file: `{data_path}`",
        f"- rows: {meta['n_rows']}  distinct_windows: {meta['distinct_windows']}  "
        f"base_rate(YES): {_f(meta['base_rate'])}",
        f"- label_balance: {meta['label_balance']}",
        f"- residual mean/std: {_f(meta['residual_mean'])} / {_f(meta['residual_std'])}",
        f"- market-implied calibration (the BASELINE to beat): brier={_f(mc.get('brier'))} "
        f"log_loss={_f(mc.get('log_loss'))} ECE_row={_f(mc.get('ece_row'))} ECE_window={_f(mc.get('ece_window'))}",
        f"- realized edge means (after fees): YES={_f(meta['realized_edge_yes_mean'])} "
        f"NO={_f(meta['realized_edge_no_mean'])}  best_edge_mean={_f(meta['best_realized_edge_mean'])}",
        f"- candidate_pnl_positive_rows (a side had +realized P&L): {meta['candidate_pnl_positive_rows']}"
        f" / {meta['n_rows']}",
        f"- rows_by_time_to_close: {meta['rows_by_time_to_close']}",
        f"- rows_by_price_bucket: {meta['rows_by_price_bucket']}",
        "", "## Leakage", f"- {meta['leakage_excluded_from_features']}",
        "", "## Safety", "- STAGED dataset; no promotion; no paper/live; live_submission_allowed=false."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# Part D/E/F — residual models, validation, metrics
# --------------------------------------------------------------------------- #
def _Xy(rows, idx, feats):
    X = [feature_vector(rows[i], feats) for i in idx]
    y = [rows[i]["y"] for i in idx]
    return X, y


def _market_p(rows, idx):
    return [rows[i]["p_market"] for i in idx]


def _to_nan_array(X):
    """list-of-rows (None for missing) -> float ndarray with np.nan (for the imputer)."""
    if not X:
        return np.empty((0, 0), dtype=float)
    return np.array([[(np.nan if v is None else float(v)) for v in row] for row in X], dtype=float)


def _aug_feats(rows, idx, feats):
    """feature vectors with logit_market appended as the final, market-anchoring column."""
    return [feature_vector(rows[i], feats) + [rows[i]["logit_market"]] for i in idx]


def _reg_pipeline(est):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                         StandardScaler(), est)


def _clf_pipeline(est, *, scale=True):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    steps = [SimpleImputer(strategy="median", keep_empty_features=True)]
    if scale:
        steps.append(StandardScaler())
    steps.append(est)
    return make_pipeline(*steps)


def _proba_pipe(pipe, arr):
    if arr.shape[0] == 0:
        return []
    pr = pipe.predict_proba(arr)
    est = pipe.steps[-1][1]
    classes = list(getattr(est, "classes_", [0, 1]))
    pos = classes.index(1) if 1 in classes else pr.shape[1] - 1
    return [float(_clip(row[pos], 0.0, 1.0)) for row in pr]


def _fit_predict(kind: str, rows, train_idx, test_idx, feats) -> Optional[dict]:
    """Fit a residual/market model; return TEST predictions (p in [0,1]) or None.

    Every model anchors on p_market: regression models predict the residual (with
    imputation + standardization) and add it back; classifier models include
    logit_market as a feature. market_only is the no-op baseline.
    """
    import warnings
    p_market_te = _market_p(rows, test_idx)
    if kind == "market_only":
        return {"kind": kind, "p_test": list(p_market_te),
                "resid_hat_test": [0.0] * len(test_idx), "feature_importance": {}, "info": "baseline"}
    if not _SK:
        return None
    y_tr = [rows[i]["y"] for i in train_idx]
    if len(set(y_tr)) < 2 or not train_idx:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if kind in ("ridge", "elasticnet"):
            X_tr = [feature_vector(rows[i], feats) for i in train_idx]
            X_te = [feature_vector(rows[i], feats) for i in test_idx]
            res_tr = np.array([rows[i]["residual"] for i in train_idx], dtype=float)
            est = (Ridge(alpha=10.0) if kind == "ridge"
                   else ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=5000))
            pipe = _reg_pipeline(est).fit(_to_nan_array(X_tr), res_tr)
            rh_te = pipe.predict(_to_nan_array(X_te)) if test_idx else np.array([])
            p_te = [_clip(pm + rh) for pm, rh in zip(p_market_te, rh_te)]
            fi = _coef_importance(getattr(pipe.steps[-1][1], "coef_", None), feats)
            return {"kind": kind, "p_test": p_te, "resid_hat_test": [float(x) for x in rh_te],
                    "feature_importance": fi}
        # logistic_offset / lightgbm — classifiers anchored on logit_market
        feats2 = feats + ["__logit_market__"]
        Xtr = _aug_feats(rows, train_idx, feats)
        Xte = _aug_feats(rows, test_idx, feats)
        if kind == "logistic_offset":
            pipe = _clf_pipeline(LogisticRegression(C=0.5, max_iter=1000, solver="lbfgs"), scale=True)
        else:
            if not LIGHTGBM_AVAILABLE:
                return None
            from lightgbm import LGBMClassifier
            pipe = _clf_pipeline(LGBMClassifier(
                n_estimators=150, num_leaves=15, max_depth=4, learning_rate=0.05, subsample=0.8,
                colsample_bytree=0.8, reg_lambda=5.0, min_child_samples=50, verbose=-1), scale=False)
        pipe.fit(_to_nan_array(Xtr), np.array(y_tr))
        p_te = _proba_pipe(pipe, _to_nan_array(Xte)) if test_idx else []
        rh_te = [pt - pm for pt, pm in zip(p_te, p_market_te)]
        est = pipe.steps[-1][1]
        fi = (_coef_importance(getattr(est, "coef_", [None])[0] if hasattr(est, "coef_") else None, feats2)
              if kind == "logistic_offset" else _lgbm_importance(est, feats2))
        return {"kind": kind, "p_test": p_te, "resid_hat_test": rh_te, "feature_importance": fi}


def _coef_importance(coef, feats) -> dict:
    if coef is None:
        return {}
    coef = list(coef)
    pairs = sorted(zip(feats, coef), key=lambda t: abs(t[1]), reverse=True)
    return {name: round(float(c), 5) for name, c in pairs[:12]}


def _lgbm_importance(clf, feats) -> dict:
    imp = list(getattr(clf, "feature_importances_", []))
    pairs = sorted(zip(feats, imp), key=lambda t: t[1], reverse=True)
    return {name: int(c) for name, c in pairs[:12]}


def _model_metrics(rows, test_idx, p_test, market_metrics) -> dict:
    y = [rows[i]["y"] for i in test_idx]
    tk = [rows[i]["window_id"] for i in test_idx]
    pm = [rows[i]["p_market"] for i in test_idx]
    base = (sum(y) / len(y)) if y else None
    m = source_metrics(y, p_test, tk, base)
    pred_resid = [pt - p for pt, p in zip(p_test, pm)]
    real_resid = [yy - p for yy, p in zip(y, pm)]
    ic = _spearman(pred_resid, real_resid)
    nz = [(pr, rr) for pr, rr in zip(pred_resid, real_resid) if abs(pr) > 1e-9]
    hit = (sum(1 for pr, rr in nz if (pr > 0) == (rr > 0)) / len(nz)) if nz else None
    corr = _pearson(pred_resid, real_resid)
    return {
        "n": m["n"], "brier": m["brier"], "log_loss": m["log_loss"],
        "ece_row": m["ece_row"], "ece_window": m["ece_window"],
        "slope": m["slope"], "intercept": m["intercept"],
        "yes_overprediction_cents": m["yes_overprediction_cents"],
        "delta_brier_vs_market": (m["brier"] - market_metrics["brier"]) if (m["brier"] is not None
                                  and market_metrics.get("brier") is not None) else None,
        "delta_log_loss_vs_market": (m["log_loss"] - market_metrics["log_loss"]) if (m["log_loss"] is not None
                                     and market_metrics.get("log_loss") is not None) else None,
        "delta_ece_window_vs_market": (m["ece_window"] - market_metrics["ece_window"]) if (m["ece_window"]
                                       is not None and market_metrics.get("ece_window") is not None) else None,
        "residual_ic_spearman": ic, "residual_pearson": corr, "residual_sign_hit_rate": hit,
        "mean_abs_residual_hat_cents": (sum(abs(x) for x in pred_resid) / len(pred_resid) * 100.0)
                                       if pred_resid else None,
    }


def _pearson(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if len(pairs) < 3:
        return None
    n = len(pairs)
    ax = [p[0] for p in pairs]
    bx = [p[1] for p in pairs]
    ma, mb = sum(ax) / n, sum(bx) / n
    cov = sum((x - ma) * (y - mb) for x, y in pairs)
    va = math.sqrt(sum((x - ma) ** 2 for x in ax))
    vb = math.sqrt(sum((y - mb) ** 2 for y in bx))
    return (cov / (va * vb)) if (va > 0 and vb > 0) else None


# --------------------------------------------------------------------------- #
# Part G — edge-policy integration (window reliability; buffers intact)
# --------------------------------------------------------------------------- #
def _edge_eval(config, rows, test_idx, p_all_test, *, unit: str = "window") -> dict:
    """Run p_repaired through the UNCHANGED edge policy with distinct-window reliability."""
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    y = [rows[i]["y"] for i in test_idx]
    tk = [rows[i]["window_id"] for i in test_idx]
    pairs = [(yy, pp) for yy, pp in zip(y, p_all_test) if pp is not None]
    if unit == "window":
        buckets = build_window_calibration_buckets([a for a, _ in pairs], [b for _, b in pairs], tk)
    else:
        buckets = build_calibration_buckets([a for a, _ in pairs], [b for _, b in pairs])
    recs = []
    for j, i in enumerate(test_idx):
        p = p_all_test[j]
        ya, na = rows[i].get("yes_ask"), rows[i].get("no_ask")
        if p is None or ya is None or na is None:
            continue
        mkt = market_implied_yes(ya, na)
        ens = {"model": p}
        if mkt is not None:
            ens["market_implied"] = mkt
        dec = evaluate_edge(EdgeInputs(p_yes_hat=p, yes_ask=ya, no_ask=na,
                                       calibration_buckets=buckets, ensemble_probs=ens,
                                       model_calibrated=True, model_tradable=True, backtest_valid=True),
                            edge_cfg, fee_model)
        recs.append({"ticker": rows[i]["window_id"], "side": dec.side, "raw": dec.raw_edge_cents,
                     "final": dec.final_policy_edge_cents, "state": dec.state,
                     "calib_buf": dec.calibration_uncertainty_buffer_cents,
                     "model_buf": dec.model_uncertainty_buffer_cents})
    passers = [r for r in recs if r["state"] == "EDGE_OK"]
    cand = [r for r in recs if (r["raw"] or -9) >= edge_cfg.min_raw_edge_cents - 1e-9]
    win = Counter(r["ticker"] for r in passers)
    return {"unit": unit, "n_rows": len(recs), "candidate_like": len(cand),
            "pass_final": len(passers), "distinct_pass_windows": len(win),
            "top1_pass_window_share": (win.most_common(1)[0][1] / len(passers)) if passers else None,
            "best_final_cents": max((r["final"] for r in recs if r["final"] is not None), default=None),
            "median_final_cents": _median([r["final"] for r in recs]),
            "median_calib_buffer_cents": _median([r["calib_buf"] for r in recs]),
            "median_model_buffer_cents": _median([r["model_buf"] for r in recs]),
            "side_distribution": dict(Counter(r["side"] for r in recs if r["side"]))}


def _backtest(config, rows, test_idx, p_test) -> dict:
    params = BacktestParams.from_config(config)
    fee_model = KalshiFeeModel.from_config(config)
    arows = _attach(rows, test_idx, p_test)
    agg = simulate_backtest(arows, params=params, fee_model=fee_model, diagnostic=True,
                            model_version="residual")
    return {k: agg.get(k) for k in ("total_simulated_trades", "windows_touched", "net_pnl", "hit_rate",
                                    "max_drawdown", "pnl_by_side", "pnl_by_seconds_to_close",
                                    "pnl_by_prob_bucket", "pnl_by_net_edge_bucket")}


# --------------------------------------------------------------------------- #
# Train + evaluate all models (Parts D/E/F/G/I)
# --------------------------------------------------------------------------- #
def train_residual_models(config, *, series: str = "KXBTC15M", embargo_windows: int = 1,
                          stage: bool = True) -> dict:
    rows, _fee, dw = build_residual_rows(config, series=series)
    sp = three_way_window_split(rows, embargo_windows=embargo_windows)
    if not sp["applied"]:
        return {"series": series, "status": "SPLIT_UNAVAILABLE", "reason": sp.get("reason"),
                "n_rows": len(rows)}
    train_idx = sp["train_idx"] + sp["calib_idx"]
    test_idx = sp["test_idx"]
    # market baseline metrics (the bar to beat)
    mk = _fit_predict("market_only", rows, train_idx, test_idx, ALL_FEATS)
    y_te = [rows[i]["y"] for i in test_idx]
    tk_te = [rows[i]["window_id"] for i in test_idx]
    base = (sum(y_te) / len(y_te)) if y_te else None
    market_metrics = source_metrics(y_te, mk["p_test"], tk_te, base)

    specs = [("market_only", ALL_FEATS), ("ridge", ALL_FEATS), ("elasticnet", ALL_FEATS),
             ("logistic_offset", ALL_FEATS)]
    if LIGHTGBM_AVAILABLE:
        specs.append(("lightgbm", ALL_FEATS))
    results: dict = {}
    fitted: dict = {}
    for kind, feats in specs:
        fit = _fit_predict(kind, rows, train_idx, test_idx, feats)
        if fit is None:
            results[kind] = {"error": "unavailable_or_single_class"}
            continue
        met = _model_metrics(rows, test_idx, fit["p_test"], market_metrics)
        edge_win = _edge_eval(config, rows, test_idx, fit["p_test"], unit="window")
        edge_row = _edge_eval(config, rows, test_idx, fit["p_test"], unit="row")
        bt = _backtest(config, rows, test_idx, fit["p_test"])
        wf = _walk_forward(config, rows, kind, feats, embargo_windows, market_only=(kind == "market_only"))
        results[kind] = {"metrics": met, "edge_window": edge_win, "edge_row": edge_row,
                         "backtest": bt, "feature_importance": fit.get("feature_importance", {}),
                         "walk_forward": wf}
        fitted[kind] = fit

    # feature-group ablations (ridge residual on each group)
    ablations: dict = {}
    for gname, feats in feature_groups().items():
        if gname == "market_only":
            ablations[gname] = {"delta_brier_vs_market": 0.0, "residual_ic_spearman": None,
                                "ece_window": market_metrics.get("ece_window")}
            continue
        fit = _fit_predict("ridge", rows, train_idx, test_idx, feats) if feats else None
        if fit is None:
            ablations[gname] = {"error": "no_features_or_unavailable"}
            continue
        met = _model_metrics(rows, test_idx, fit["p_test"], market_metrics)
        ablations[gname] = {"delta_brier_vs_market": met["delta_brier_vs_market"],
                            "delta_ece_window_vs_market": met["delta_ece_window_vs_market"],
                            "residual_ic_spearman": met["residual_ic_spearman"],
                            "ece_window": met["ece_window"], "n_features": len(feats)}

    staged = _stage_residual_models(config, results, fitted, sp, series=series, dw=dw) if stage else []
    verdict = _verdict(results, market_metrics)
    return {"series": series, "status": "OK", "n_rows": len(rows),
            "split": {k: sp.get(k) for k in ("n_windows", "train_windows", "calib_windows",
                                             "test_windows", "embargo_windows")},
            "market_metrics": {k: market_metrics.get(k) for k in
                               ("brier", "log_loss", "ece_row", "ece_window")},
            "results": results, "ablations": ablations, "verdict": verdict,
            "staged_artifacts": staged, "lightgbm_available": LIGHTGBM_AVAILABLE,
            "sklearn_available": _SK}


def _walk_forward(config, rows, kind, feats, embargo_windows, *, market_only=False) -> dict:
    folds = walk_forward_indices(rows, n_splits=3, embargo_windows=embargo_windows)
    deltas, ics = [], []
    for tr, vl in folds:
        mk = _fit_predict("market_only", rows, tr, vl, feats)
        y = [rows[i]["y"] for i in vl]
        tk = [rows[i]["window_id"] for i in vl]
        base = (sum(y) / len(y)) if y else None
        mm = source_metrics(y, mk["p_test"], tk, base)
        if market_only:
            deltas.append(0.0); ics.append(None); continue
        fit = _fit_predict(kind, rows, tr, vl, feats)
        if fit is None:
            continue
        met = _model_metrics(rows, vl, fit["p_test"], mm)
        deltas.append(met["delta_brier_vs_market"])
        ics.append(met["residual_ic_spearman"])
    dvals = [d for d in deltas if isinstance(d, (int, float))]
    ivals = [i for i in ics if isinstance(i, (int, float))]
    return {"folds": len(folds), "delta_brier_per_fold": [round(d, 5) for d in dvals],
            "ic_per_fold": [round(i, 4) for i in ivals],
            "mean_delta_brier": (sum(dvals) / len(dvals)) if dvals else None,
            "mean_ic": (sum(ivals) / len(ivals)) if ivals else None,
            "stable_improvement": bool(dvals and all(d < 0 for d in dvals))}


def _verdict(results: dict, market_metrics: dict) -> dict:
    """A residual model is interesting only if it beats market OOS AND passes multiple windows."""
    beats, edge_winners = [], []
    for kind, r in results.items():
        if kind == "market_only" or "metrics" not in r:
            continue
        m = r["metrics"]
        wf = r.get("walk_forward", {})
        beats_market = bool(m.get("delta_brier_vs_market") is not None and m["delta_brier_vs_market"] < 0
                            and wf.get("stable_improvement"))
        passes_multi = (r.get("edge_window", {}).get("distinct_pass_windows", 0) >= 2)
        if beats_market:
            beats.append(kind)
        if beats_market and passes_multi:
            edge_winners.append(kind)
    any_beats = bool(beats)
    any_edge = bool(edge_winners)
    if any_edge:
        rec = (f"{edge_winners} beat market OOS AND clear final edge across >=2 windows — worth a STAGED "
               "shadow-candidate REVIEW (not promotion). Validate concentration + stability first.")
    elif any_beats:
        rec = (f"{beats} marginally beat market OOS on Brier but produce NO multi-window final edge — "
               "interesting but not tradable; continue research/collection, do not promote.")
    else:
        rec = ("NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The "
               "apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and "
               "research only; do not promote, do not lower gates, do not remove buffers.")
    return {"any_model_beats_market_oos": any_beats, "models_beating_market": beats,
            "any_model_multi_window_edge": any_edge, "edge_winners": edge_winners, "recommendation": rec}


# --------------------------------------------------------------------------- #
# Part J — staged residual artifacts
# --------------------------------------------------------------------------- #
def _stage_residual_models(config, results, fitted, sp, *, series, dw) -> list[dict]:
    promo = load_active_promotion(config, series=series)
    bb = promo.get("model_path")
    input_sha = sha256_file(bb) if (bb and Path(bb).exists()) else None
    d = staged_models_dir(config)
    sm = {k: sp.get(k) for k in ("train_windows", "calib_windows", "test_windows", "embargo_windows")}
    staged = []
    for kind, fit in fitted.items():
        if kind == "market_only":
            continue
        met = results.get(kind, {}).get("metrics", {})
        artifact = {
            "artifact_type": "residual_alpha_model", "model_type": kind,
            "uses_market_baseline": True, "target": "residual_vs_market (y - p_market)",
            "input_dataset": "(in-memory build_model_dataset -> residual rows)",
            "model_backbone_path": bb, "input_model_sha256": input_sha,
            "train_windows": sm.get("train_windows"), "calib_windows": sm.get("calib_windows"),
            "test_windows": sm.get("test_windows"), "dataset_distinct_windows": dw,
            "metrics_vs_market": {k: met.get(k) for k in (
                "brier", "log_loss", "ece_window", "delta_brier_vs_market",
                "delta_log_loss_vs_market", "delta_ece_window_vs_market",
                "residual_ic_spearman", "residual_sign_hit_rate")},
            "feature_importance": fit.get("feature_importance", {}),
            "is_staged": True, "is_promoted": False, "live_approved": False,
            "tradable_status": DIAGNOSTIC_ONLY, "promotion_required": True,
            "calibration_status": "diagnostic",
            "created_by_command": "kalshi-train-residual-models", "series": series,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notes": f"STAGED residual-alpha model ({kind}); DIAGNOSTIC_ONLY; never promoted; "
                     "report-only research over the market-implied baseline.",
            "tradable_status_check": tradable_status_for(is_diagnostic=True, is_staged=True, is_promoted=False),
        }
        stem = f"kalshi_residual_model_{kind}_{_ts()}"
        (d / f"{stem}.pkl").write_bytes(pickle.dumps(artifact))
        (d / f"{stem}.json").write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
        staged.append({"artifact_file": str(d / f"{stem}.pkl"), "summary_file": str(d / f"{stem}.json"),
                       "model_type": kind, "tradable_status": DIAGNOSTIC_ONLY})
    return staged


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _write_model_report(config, res) -> dict:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    md = d / f"kalshi_residual_model_report_{stamp}.md"
    csvp = d / f"kalshi_residual_model_report_{stamp}.csv"
    mm = res["market_metrics"]
    lines = [
        f"# Kalshi residual-alpha model report — {res['series']}", "",
        "> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on "
        "held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged "
        "+2c final edge gate across >=2 windows. No promotion; live/paper disabled.", "",
        f"- split(windows): {res['split']}  rows: {res['n_rows']}  "
        f"sklearn={res['sklearn_available']} lightgbm={res['lightgbm_available']}",
        f"- **market-implied baseline (TEST)**: brier={_f(mm.get('brier'))} log_loss={_f(mm.get('log_loss'))} "
        f"ECE_row={_f(mm.get('ece_row'))} ECE_window={_f(mm.get('ece_window'))}",
        "", "| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | "
        "sign_hit | pass_final(win) | dist_pass_win | backtest_net |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kind, r in res["results"].items():
        if "metrics" not in r:
            lines.append(f"| {kind} | (error: {r.get('error')}) |||||||||| ")
            continue
        m = r["metrics"]; ew = r["edge_window"]; bt = r["backtest"]
        lines.append(
            f"| {kind} | {_f(m['brier'])} | {_f(m['delta_brier_vs_market'])} | {_f(m['log_loss'])} | "
            f"{_f(m['ece_window'])} | {_f(m['delta_ece_window_vs_market'])} | {_f(m['residual_ic_spearman'])} | "
            f"{_f(m['residual_sign_hit_rate'])} | {ew['pass_final']} | {ew['distinct_pass_windows']} | "
            f"{_f(bt.get('net_pnl'))} |")
    lines += ["", "## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)"]
    for g, a in res["ablations"].items():
        lines.append(f"- {g}: dBrier={_f(a.get('delta_brier_vs_market'))} "
                     f"dECE_win={_f(a.get('delta_ece_window_vs_market'))} IC={_f(a.get('residual_ic_spearman'))}")
    lines += ["", "## Walk-forward stability (delta-Brier per fold; negative=beats market)"]
    for kind, r in res["results"].items():
        if "walk_forward" in r:
            wf = r["walk_forward"]
            lines.append(f"- {kind}: deltas={wf.get('delta_brier_per_fold')} ic={wf.get('ic_per_fold')} "
                         f"stable_improvement={wf.get('stable_improvement')}")
    lines += ["", "## Top features (incremental residual signal, if any)"]
    for kind, r in res["results"].items():
        fi = r.get("feature_importance")
        if fi:
            lines.append(f"- {kind}: {dict(list(fi.items())[:8])}")
    v = res["verdict"]
    lines += ["", "## Verdict",
              f"- any model beats market OOS: **{v['any_model_beats_market_oos']}** {v['models_beating_market']}",
              f"- any model multi-window final edge: **{v['any_model_multi_window_edge']}** {v['edge_winners']}",
              f"- **recommendation: {v['recommendation']}**",
              "", "## Safety",
              "- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; "
              "live/paper disabled; live_submission_allowed=false."]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csvp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "brier", "delta_brier_vs_market", "log_loss", "ece_window",
                    "delta_ece_window_vs_market", "residual_ic_spearman", "residual_sign_hit_rate",
                    "pass_final_window", "distinct_pass_windows", "backtest_net_pnl"])
        for kind, r in res["results"].items():
            if "metrics" not in r:
                continue
            m = r["metrics"]; ew = r["edge_window"]; bt = r["backtest"]
            w.writerow([kind, m["brier"], m["delta_brier_vs_market"], m["log_loss"], m["ece_window"],
                        m["delta_ece_window_vs_market"], m["residual_ic_spearman"],
                        m["residual_sign_hit_rate"], ew["pass_final"], ew["distinct_pass_windows"],
                        bt.get("net_pnl")])
    return {"model_report_md": str(md), "model_report_csv": str(csvp)}


def _write_backtest_edge_reports(config, res) -> dict:
    bd = config.reports_path() / "backtests"
    ed = config.reports_path() / "edge"
    bd.mkdir(parents=True, exist_ok=True)
    ed.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    btmd = bd / f"kalshi_residual_backtest_{stamp}.md"
    edmd = ed / f"kalshi_residual_edge_policy_report_{stamp}.md"
    blines = [f"# Kalshi residual backtest — {res['series']}", "",
              "> STAGED / report-only. Executable asks + fees + gates on held-out TEST windows. EVIDENCE only; "
              "in-sample P&L must NOT select a policy. No promotion; live disabled.", ""]
    elines = [f"# Kalshi residual edge-policy report — {res['series']}", "",
              "> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge "
              "policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.", ""]
    for kind, r in res["results"].items():
        if "metrics" not in r:
            continue
        bt = r["backtest"]; ew = r["edge_window"]; erow = r["edge_row"]
        blines += [f"### {kind}",
                   f"- trades: {bt.get('total_simulated_trades')}  windows: {bt.get('windows_touched')}  "
                   f"net_pnl: {_f(bt.get('net_pnl'))}  hit_rate: {_f(bt.get('hit_rate'))}  "
                   f"max_drawdown: {_f(bt.get('max_drawdown'))}",
                   f"- pnl_by_side: {bt.get('pnl_by_side')}",
                   f"- pnl_by_seconds_to_close: {bt.get('pnl_by_seconds_to_close')}",
                   f"- pnl_by_prob_bucket: {bt.get('pnl_by_prob_bucket')}", ""]
        elines += [f"### {kind}",
                   f"- WINDOW unit: candidate_like={ew['candidate_like']} pass_final={ew['pass_final']} "
                   f"distinct_pass_windows={ew['distinct_pass_windows']} best_final={_f(ew['best_final_cents'])}c "
                   f"med_calib_buf={_f(ew['median_calib_buffer_cents'])}c side={ew['side_distribution']}",
                   f"- ROW unit: candidate_like={erow['candidate_like']} pass_final={erow['pass_final']} "
                   f"best_final={_f(erow['best_final_cents'])}c", ""]
    blines += ["## Safety", "- EVIDENCE only; no promotion; live disabled."]
    elines += ["## Safety", "- buffers never removed; +2c gate intact; window reliability is honest/wider; "
               "no promotion; live disabled."]
    btmd.write_text("\n".join(blines) + "\n", encoding="utf-8")
    edmd.write_text("\n".join(elines) + "\n", encoding="utf-8")
    return {"backtest_md": str(btmd), "edge_policy_md": str(edmd)}


# --------------------------------------------------------------------------- #
# Runners (Part K)
# --------------------------------------------------------------------------- #
def run_train_residual_models(config, *, series: str = "KXBTC15M") -> dict:
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    res = train_residual_models(config, series=series, stage=True)
    if res.get("status") != "OK":
        res["preservation_manifest"] = preservation
        res["runtime_unchanged"] = verify_runtime_unchanged(config, snap)["unchanged"]
        res["live_submission_allowed"] = False
        return res
    reports = {**_write_model_report(config, res), **_write_backtest_edge_reports(config, res)}
    verify = verify_runtime_unchanged(config, snap)
    res.update(reports=reports, preservation_manifest=preservation,
               runtime_unchanged=verify["unchanged"], live_submission_allowed=False)
    return res


def run_residual_model_report(config, *, series: str = "KXBTC15M") -> dict:
    return run_train_residual_models(config, series=series)


def run_residual_replay(config, *, series: str = "KXBTC15M", ledger: Optional[str] = None,
                        latest_shadow: bool = True) -> dict:
    """Offline replay: score the latest shadow ledger's rows with market + residual candidates."""
    from .uncertainty_audit import latest_ledger, load_decisions
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    rows, _fee, dw = build_residual_rows(config, series=series)
    sp = three_way_window_split(rows, embargo_windows=1)
    base = {"series": series, "live_submission_allowed": False, "preservation_manifest": preservation}
    if not sp["applied"]:
        return {**base, "status": "SPLIT_UNAVAILABLE", "reason": sp.get("reason"),
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    lp = Path(ledger) if ledger else latest_ledger(config)
    if lp is None or not Path(lp).exists():
        return {**base, "status": "NO_LEDGER",
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    # fit models on the dataset; build a scorer for arbitrary (features,p_market) rows
    train_idx = sp["train_idx"] + sp["calib_idx"]
    scorers = _build_scorers(rows, train_idx, ALL_FEATS)
    decs = load_decisions(lp)
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    # window buckets per method from the dataset TEST predictions
    test_idx = sp["test_idx"]
    buckets = {}
    for name, sc in scorers.items():
        p_te = [sc(rows[i]) for i in test_idx]
        y = [rows[i]["y"] for i in test_idx]
        tk = [rows[i]["window_id"] for i in test_idx]
        pairs = [(yy, pp, tt) for yy, pp, tt in zip(y, p_te, tk) if pp is not None]
        buckets[name] = (build_window_calibration_buckets([a for a, _, _ in pairs], [b for _, b, _ in pairs],
                                                          [c for _, _, c in pairs]) if pairs else [])
    acc = {name: _EAcc(edge_cfg.min_raw_edge_cents) for name in scorers}
    n = 0
    for d in decs:
        ya, na = d.get("executable_yes_price"), d.get("executable_no_price")
        if ya is None or na is None:
            continue
        feat_row = {**d, "yes_ask": ya, "no_ask": na}
        # the ledger rows lack microstructure feature columns; market-anchored scorers still work
        n += 1
        for name, sc in scorers.items():
            p = sc(feat_row)
            if p is None:
                continue
            mkt = market_implied_yes(ya, na)
            ens = {"model": p, **({"market_implied": mkt} if mkt is not None else {})}
            dec = evaluate_edge(EdgeInputs(p_yes_hat=p, yes_ask=ya, no_ask=na,
                                           calibration_buckets=buckets.get(name, []), ensemble_probs=ens,
                                           model_calibrated=True, model_tradable=True, backtest_valid=True),
                                edge_cfg, fee_model)
            acc[name].add(dec, d.get("ticker"))
    summary = {name: a.summary() for name, a in acc.items()}
    report = _write_replay_report(config, series, str(lp), n, summary)
    verify = verify_runtime_unchanged(config, snap)
    return {**base, "status": "OK", "ledger": str(lp), "rows_scored": n, "summary": summary,
            "report": report, "runtime_unchanged": verify["unchanged"]}


def _build_scorers(rows, train_idx, feats) -> dict:
    """Return {method: scorer(feature_row)->p} for market_only + fitted residual models."""
    scorers = {"market_only": lambda r: market_implied_yes(r.get("yes_ask"), r.get("no_ask"))}
    if not _SK or len(set(rows[i]["y"] for i in train_idx)) < 2:
        return scorers
    for kind in ("ridge", "logistic_offset"):
        try:
            scorers[kind] = _make_scorer(kind, rows, train_idx, feats)
        except Exception:  # noqa: BLE001 — a failed candidate scorer just drops out
            continue
    return scorers


def _make_scorer(kind, rows, train_idx, feats):
    """Fit a pipeline once and return a closure scoring a single feature row to p_repaired."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if kind == "ridge":
            X_tr = [feature_vector(rows[i], feats) for i in train_idx]
            res = np.array([rows[i]["residual"] for i in train_idx], dtype=float)
            pipe = _reg_pipeline(Ridge(alpha=10.0)).fit(_to_nan_array(X_tr), res)

            def _score(r):
                pm = market_implied_yes(r.get("yes_ask"), r.get("no_ask"))
                if pm is None:
                    return None
                rh = float(pipe.predict(_to_nan_array([feature_vector(r, feats)]))[0])
                return _clip(pm + rh)
            return _score
        # logistic_offset
        y = [rows[i]["y"] for i in train_idx]
        Xtr = _aug_feats(rows, train_idx, feats)
        pipe = _clf_pipeline(LogisticRegression(C=0.5, max_iter=1000, solver="lbfgs"),
                             scale=True).fit(_to_nan_array(Xtr), np.array(y))

        def _score2(r):
            pm = market_implied_yes(r.get("yes_ask"), r.get("no_ask"))
            if pm is None:
                return None
            x = _to_nan_array([feature_vector(r, feats) + [_logit(pm)]])
            return _proba_pipe(pipe, x)[0]
        return _score2


class _EAcc:
    def __init__(self, min_raw):
        self.min_raw = min_raw
        self.n = 0
        self.cand = 0
        self.passes = 0
        self.finals = []
        self.windows = Counter()
        self.sides = Counter()

    def add(self, dec, ticker):
        self.n += 1
        if (dec.raw_edge_cents or -9) >= self.min_raw - 1e-9:
            self.cand += 1
        if dec.state == "EDGE_OK":
            self.passes += 1
            self.windows[ticker] += 1
        if dec.final_policy_edge_cents is not None:
            self.finals.append(dec.final_policy_edge_cents)
        if dec.side:
            self.sides[dec.side] += 1

    def summary(self):
        return {"n_rows": self.n, "candidate_like": self.cand, "pass_final": self.passes,
                "distinct_pass_windows": len(self.windows),
                "best_final_cents": (max(self.finals) if self.finals else None),
                "median_final_cents": _median(self.finals), "side_distribution": dict(self.sides)}


def _write_replay_report(config, series, ledger, n, summary) -> str:
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_residual_replay_{_ts()}.md"
    lines = [f"# Kalshi residual replay — {series}", "",
             "> STAGED / report-only. Latest shadow ledger rows re-scored with the market baseline + residual "
             "models through the unchanged edge policy. No fills; no promotion; live disabled.", "",
             f"- ledger: `{ledger}`  rows_scored: {n}", "",
             "| method | candidate_like | pass_final | distinct_pass_windows | best_final(c) | sides |",
             "|---|---|---|---|---|---|"]
    for name, s in summary.items():
        lines.append(f"| {name} | {s['candidate_like']} | {s['pass_final']} | {s['distinct_pass_windows']} | "
                     f"{_f(s['best_final_cents'])} | {s['side_distribution']} |")
    lines += ["", "## Safety", "- replay only; buffers intact; no promotion; live disabled."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# Part H #2 — live shadow compare of residual models
# --------------------------------------------------------------------------- #
def run_shadow_compare_residual(config, *, series: str = "KXBTC15M", minutes: float = 30.0,
                                poll_interval: float = 0.5) -> dict:
    import time as _time
    from .paper_runtime import _decision_eligibility, _prepare_runtime, latest_feature_rows
    snap = snapshot_runtime_state(config)
    preservation = write_preservation_manifest(config, snap)
    rows, _fee, dw = build_residual_rows(config, series=series)
    sp = three_way_window_split(rows, embargo_windows=1)
    base = {"series": series, "live_submission_allowed": False, "preservation_manifest": preservation}
    if not sp["applied"]:
        return {**base, "status": "SPLIT_UNAVAILABLE", "reason": sp.get("reason"),
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    prep = _prepare_runtime(config, series=series, mode="shadow")
    if prep.get("status") != "OK":
        return {**base, "status": prep.get("status"), "blockers": prep.get("base", {}).get("blockers", []),
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    train_idx = sp["train_idx"] + sp["calib_idx"]
    test_idx = sp["test_idx"]
    scorers = _build_scorers(rows, train_idx, ALL_FEATS)
    edge_cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    buckets = {}
    for name, sc in scorers.items():
        p_te = [sc(rows[i]) for i in test_idx]
        y = [rows[i]["y"] for i in test_idx]
        tk = [rows[i]["window_id"] for i in test_idx]
        pairs = [(yy, pp, tt) for yy, pp, tt in zip(y, p_te, tk) if pp is not None]
        buckets[name] = (build_window_calibration_buckets([a for a, _, _ in pairs], [b for _, b, _ in pairs],
                                                          [c for _, _, c in pairs]) if pairs else [])
    acc = {name: _EAcc(edge_cfg.min_raw_edge_cents) for name in scorers}
    fcfg = config.freshness
    ftr = int(max(int(fcfg.coinbase_decision_max_age_ms), int(float(poll_interval) * 1000 * 2)))
    md_secs = int(getattr(getattr(config, "low_latency", None), "market_duration_seconds", 900))
    pc_eff = prep["pc_eff"]
    seen = set()
    start = _time.monotonic()
    end = start + max(0.0, float(minutes) * 60.0)
    rows_read = 0
    executable = 0
    while True:
        now = __import__("btc5m.timeutils", fromlist=["now_ms"]).now_ms()
        for r in latest_feature_rows(config, series=series, lines=4000):
            key = (r.get("ticker"), r.get("as_of_ts_ms"))
            if key in seen:
                continue
            seen.add(key)
            rows_read += 1
            ok, _reasons, _flags = _decision_eligibility(r, pc=pc_eff, market_duration_seconds=md_secs,
                                                         feature_row_max_age_ms=ftr, now=now)
            if not ok:
                continue
            executable += 1
            for name, sc in scorers.items():
                p = sc(r)
                if p is None:
                    continue
                mkt = market_implied_yes(r.get("yes_ask"), r.get("no_ask"))
                ens = {"model": p, **({"market_implied": mkt} if mkt is not None else {})}
                dec = evaluate_edge(EdgeInputs(p_yes_hat=p, yes_ask=r.get("yes_ask"), no_ask=r.get("no_ask"),
                                               calibration_buckets=buckets.get(name, []), ensemble_probs=ens,
                                               model_calibrated=True, model_tradable=True, backtest_valid=True),
                                    edge_cfg, fee_model)
                acc[name].add(dec, r.get("ticker"))
        if _time.monotonic() >= end:
            break
        _time.sleep(max(0.2, min(float(poll_interval), max(0.0, end - _time.monotonic()))))
    # offline fallback if no fresh active rows
    mode = "live"
    if executable == 0:
        r = run_residual_replay(config, series=series, latest_shadow=True)
        if r.get("status") == "OK":
            return {**base, "status": "OK", "mode": "replay_fallback", "rows_scored": r.get("rows_scored"),
                    "summary": r.get("summary"), "report": r.get("report"),
                    "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    summary = {name: a.summary() for name, a in acc.items()}
    report = _write_shadow_report(config, series, mode, rows_read, executable, summary)
    verify = verify_runtime_unchanged(config, snap)
    return {**base, "status": "OK", "mode": mode, "rows_read": rows_read, "executable_rows": executable,
            "summary": summary, "report": report, "runtime_unchanged": verify["unchanged"]}


def _write_shadow_report(config, series, mode, rows_read, executable, summary) -> str:
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_shadow_compare_residual_models_{_ts()}.md"
    lines = [f"# Kalshi shadow compare — residual models ({series})", "",
             "> STAGED / report-only. Same live executable rows scored by the market baseline + residual "
             "models through the unchanged edge policy. No fills; no promotion; live disabled.", "",
             f"- mode: {mode}  rows_read: {rows_read}  executable_rows: {executable}", "",
             "| method | candidate_like | pass_final | distinct_pass_windows | best_final(c) | sides |",
             "|---|---|---|---|---|---|"]
    for name, s in summary.items():
        lines.append(f"| {name} | {s['candidate_like']} | {s['pass_final']} | {s['distinct_pass_windows']} | "
                     f"{_f(s['best_final_cents'])} | {s['side_distribution']} |")
    lines += ["", "## Safety", "- shadow only; buffers intact; no promotion; live/paper disabled."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
