"""Multi-feature COMBINATION mine — does combining all signals beat the price after cost?

Every prior mine tested SINGLE-feature threshold rules (plus a calibration-fit logistic scored
on Brier, not P&L). This is the missing test: a walk-forward (purged) logistic on the top-K
residual-IC features (the full library incl. volume + cross-coin), generating OOS predictions,
trading the divergence vs the market price after real cost. Trials = {feature-set sizes} ×
{divergence thresholds}; the best goes through the DSR/PBO/plateau gauntlet + sealed holdout. If
a full EV-relevant combination of every signal still cannot beat the price, that is close to a
definitive close on existing data. READ-ONLY."""
from __future__ import annotations

import os

import numpy as np

from ..venues.kalshi.fees import KalshiFeeModel
from . import cpcv, engine, gauntlet, holdout, panel, registry, screen

KSET = [3, 5, 8, 12]
THRESH = [0.02, 0.04, 0.06, 0.08, 0.10]


def _design(obs, feats):
    X = np.array([[(o.feats.get(f) if o.feats.get(f) is not None else np.nan) for f in feats]
                  for o in obs], float)
    # impute column means (neutral) for missing
    col_mean = np.nanmean(np.where(np.isnan(X), np.nan, X), axis=0)
    col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_mean, inds[1])
    y = np.array([o.y for o in obs], int)
    return X, y


def _walk_forward_p(obs, feats, *, n_splits=6, embargo=1):
    """OOS model probability per window via expanding purged walk-forward. Returns array
    aligned to obs (NaN where never predicted)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    X, y = _design(obs, feats)
    n = len(obs)
    p = np.full(n, np.nan)
    for tr, te in cpcv.purged_walk_forward(n, n_splits=n_splits, embargo=embargo):
        if len(set(y[tr].tolist())) < 2 or len(tr) < 30:
            continue
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(C=0.5, max_iter=1000).fit(sc.transform(X[tr]), y[tr])
        p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    return p


def _net_vec(obs, p_model, thresh, fee):
    vec = np.zeros(len(obs))
    for i, o in enumerate(obs):
        pm = p_model[i]
        if pm != pm:
            continue
        d = pm - o.mkt_p
        if d > thresh:                      # model: YES underpriced -> buy YES at exec ask
            price = o.exec_yes
            vec[i] = 100 * (o.y - price) - fee.taker_fee(price, 1) * 100
        elif d < -thresh:                   # buy NO
            price = o.exec_no
            vec[i] = 100 * ((1 - o.y) - price) - fee.taker_fee(price, 1) * 100
    return vec


def run_combo_mine(*, series="KXBTC15M", lead_seconds=180.0, exec_lag_seconds=3.0, embargo=1,
                   registry_path=None, validate_holdout=True, verbose=True) -> dict:
    pn_all, cfg = engine._build_panel(series, lead_seconds, exec_lag_seconds)
    fee = KalshiFeeModel.from_config(cfg)
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))
    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))

    from . import feature_factory
    screened = screen.screen_features(search_pn, feature_factory.feature_names(), n_splits=5, embargo=embargo)
    ranked_feats = [s["feature"] for s in screened if s["coverage"] >= 0.7][:max(KSET)]

    cols, meta = [], []
    pcache = {}
    for k in KSET:
        fset = ranked_feats[:k]
        if len(fset) < k:
            continue
        p = _walk_forward_p(search_pn, fset)
        pcache[k] = (fset, p)
        for th in THRESH:
            vec = _net_vec(search_pn, p, th, fee)
            ntr = int((vec != 0).sum())
            if ntr < 20:
                continue
            cols.append(vec)
            meta.append({"k": k, "thresh": th, "n_trades": ntr, "fset": fset})
    n_trials = len(cols)
    report = {"series": series, "n_windows": len(pn_all), "n_search": len(search_pn),
              "n_holdout": len(hold_pn), "ranked_feats": ranked_feats[:max(KSET)],
              "n_trials": n_trials, "best": None, "gauntlet": None,
              "holdout_validation": None, "verdict": None}
    if cols:
        M = np.column_stack(cols)
        from . import metrics
        sharpes = [metrics.sharpe(M[:, j].tolist()) for j in range(M.shape[1])]
        bj = int(np.nanargmax(sharpes))
        b = meta[bj]
        per = M[:, bj][M[:, bj] != 0]
        cum = reg.cumulative_trials(space_id="combo_v1", data_fingerprint=vault.fingerprint) + n_trials
        dsr = gauntlet.deflated_sharpe_ratio(M[:, bj].tolist(), n_trials=cum, trial_sharpes=sharpes)
        pbo = gauntlet.pbo_cscv(M, n_partitions=8)
        plat = gauntlet.parameter_plateau({m["thresh"]: metrics.sharpe(M[:, j].tolist())
                                           for j, m in enumerate(meta) if m["k"] == b["k"]})
        report["best"] = {"k": b["k"], "thresh": b["thresh"], "n_trades": b["n_trades"],
                          "per_trade_mean_c": float(per.mean()) if len(per) else float("nan"),
                          "per_trade_t": metrics.tstat(per.tolist()), "window_sharpe": sharpes[bj],
                          "fset": b["fset"]}
        report["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plat}
        report["verdict"] = gauntlet.verdict(dsr, pbo, plateau=plat)
        if report["verdict"]["passed"] and validate_holdout and hold_pn:
            fset, _ = pcache[b["k"]]
            # refit on all search, predict holdout
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
            Xs, ys = _design(search_pn, fset)
            Xh, _yh = _design(hold_pn, fset)
            sc = StandardScaler().fit(Xs)
            clf = LogisticRegression(C=0.5, max_iter=1000).fit(sc.transform(Xs), ys)
            ph = clf.predict_proba(sc.transform(Xh))[:, 1]
            vh = _net_vec(hold_pn, ph, b["thresh"], fee)
            per_h = vh[vh != 0]
            report["holdout_validation"] = {"n_trades": int(len(per_h)),
                                            "mean_c": float(per_h.mean()) if len(per_h) else float("nan"),
                                            "t": metrics.tstat(per_h.tolist())}
    reg.log_run(data_fingerprint=vault.fingerprint, space_id="combo_v1", n_trials=n_trials,
                candidates=[report["best"]] if report["best"] else [],
                meta={"mode": "combo", "verdict_passed":
                      bool(report["verdict"] and report["verdict"]["passed"])})
    if verbose:
        print(format_combo_report(report))
    return report


def format_combo_report(r: dict) -> str:
    L = [f"\n{'='*82}\nALPHA DISCOVERY ENGINE — MULTI-FEATURE COMBINATION mine  {r['series']}\n{'='*82}",
         f"windows {r['n_windows']} (search {r['n_search']} / holdout {r['n_holdout']}); "
         f"trials {r['n_trials']} (feature-sets {len(set(0 for _ in [1]))})",
         f"top features fed to the model: {r['ranked_feats'][:8]}"]
    b = r["best"]
    if not b:
        L.append("\nno eligible combination trials.")
        return "\n".join(L)
    L += ["", f"best combination: logistic on top-{b['k']} features, divergence>={b['thresh']:.2f}",
          f"   features: {b['fset']}",
          f"   n_trades={b['n_trades']}  per_trade={b['per_trade_mean_c']:+.2f}c "
          f"(t={b['per_trade_t']:+.2f})  window_sharpe={b['window_sharpe']:+.3f}"]
    g = r["gauntlet"]; d = g["dsr"]
    L += ["", "GAUNTLET:",
          f"   Deflated Sharpe = {d['deflated_sharpe_ratio']:.3f} (raw {d['sharpe']:+.3f} vs "
          f"E[maxSR|{d['n_trials']}] {d['expected_max_sharpe']:.3f}) -> {'PASS' if d['significant'] else 'fail'}",
          f"   PBO = {g['pbo']['pbo']:.2f} -> {'PASS' if (g['pbo']['pbo']==g['pbo']['pbo'] and g['pbo']['pbo']<0.5) else 'fail'}"]
    if g["plateau"]:
        L.append(f"   plateau_ratio = {g['plateau'].get('plateau_ratio'):.2f} -> "
                 f"{'SPIKE (fail)' if g['plateau'].get('is_spike') else 'plateau (ok)'}")
    v = r["verdict"]
    L.append(f"\nVERDICT: {'*** COMBINATION EDGE SURVIVES ***' if v['passed'] else 'NO EDGE (rejected)'}")
    for reason in (v["reasons"] if not v["passed"] else []):
        L.append(f"   - {reason}")
    if r["holdout_validation"]:
        h = r["holdout_validation"]
        L.append(f"SEALED-HOLDOUT: n={h['n_trades']} mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    return "\n".join(L)
