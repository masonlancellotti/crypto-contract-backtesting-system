"""Execution / maker-edge mining — the second 'unchosen' search domain, through the gauntlet.

The maker lens is the only place positive signals ever appeared (#13/#15: resting entries save
the spread+fee; favorite/YES-side cells looked +EV), but every look was a hand-picked cell with
no multiple-testing control. This mines maker strategies systematically and forces the best
through the SAME gauntlet (Deflated Sharpe + PBO + holdout), so the recurring maker-band cells
finally get an honest, overfitting-aware verdict.

Observation = a window's decision snapshot. A maker rule = (feature, tail, side): rest a JOIN bid
on `side` when the feature is in its tail; the fill is the REAL trade tape (prints-through, the
adverse/certain subset); net = after-cost maker P&L (maker fee assumed 0). Per-window vector =
net if quoted&filled else 0 (no position). BTC only (alts have no backfilled prints)."""
from __future__ import annotations

import os

import numpy as np

from ..venues.kalshi.backfill_trades import load_trade_prints
from ..venues.kalshi.fees import KalshiFeeModel
from ..venues.kalshi.maker_entry import _first_print_fill
from . import engine, feature_factory, gauntlet, holdout, metrics, panel, registry, screen

HI_Q = (0.55, 0.65, 0.75, 0.85, 0.92)
LO_Q = (0.45, 0.35, 0.25, 0.15, 0.08)


def compute_maker_nets(pn, prints_by_tk, maker_fee, *, queue="through") -> dict:
    """Per-window maker fill outcome for a resting JOIN bid on each side."""
    out = {}
    for o in pn:
        prs = prints_by_tk.get(o.ticker)
        if not prs or o.t0_ms is None:
            continue
        rec = {}
        for side, limit, y_side in (("YES", o.yes_bid, o.y), ("NO", o.no_bid, 1 - o.y)):
            if limit is None or not (0.0 < limit < 1.0):
                rec[side] = (0.0, False)
                continue
            fill = _first_print_fill(prs, o.t0_ms, o.close_ms, side, limit, queue=queue)
            if fill is not None:
                rec[side] = ((y_side - limit) * 100.0 - maker_fee.per_contract_fee(limit) * 100.0, True)
            else:
                rec[side] = (0.0, False)
        out[o.ticker] = rec
    return out


def _vecs(pn, maker_nets):
    g = lambda o, s, k: maker_nets.get(o.ticker, {}).get(s, (0.0, False))[k]
    return (np.array([g(o, "YES", 0) for o in pn]), np.array([g(o, "YES", 1) for o in pn], bool),
            np.array([g(o, "NO", 0) for o in pn]), np.array([g(o, "NO", 1) for o in pn], bool))


def maker_search(pn, feature_names, maker_nets, *, min_fills=20):
    n = len(pn)
    yn, yf, nn, nf = _vecs(pn, maker_nets)
    cols, meta = [], []
    for name in feature_names:
        fv = np.array([o.feats.get(name) if o.feats.get(name) is not None else np.nan for o in pn])
        valid = ~np.isnan(fv)
        if valid.sum() < min_fills:
            continue
        for tail, qs in (("hi", HI_Q), ("lo", LO_Q)):
            for q in qs:
                thr = float(np.quantile(fv[valid], q))
                quoted = valid & ((fv >= thr) if tail == "hi" else (fv <= thr))
                for side, net, fill in (("YES", yn, yf), ("NO", nn, nf)):
                    filled = quoted & fill
                    if filled.sum() < min_fills:
                        continue
                    cols.append(np.where(filled, net, 0.0))
                    meta.append({"feature": name, "tail": tail, "q": q, "thr": thr, "side": side,
                                 "n_fills": int(filled.sum()), "fill_idx": np.where(filled)[0],
                                 "net": net})
    if not cols:
        return {"matrix": np.zeros((n, 0)), "meta": [], "n_trials": 0}
    return {"matrix": np.column_stack(cols), "meta": meta, "n_trials": len(meta)}


def _rank(res):
    M, meta = res["matrix"], res["meta"]
    stats = []
    for j, m in enumerate(meta):
        vec = M[:, j]
        per = m["net"][m["fill_idx"]]
        stats.append({**{k: v for k, v in m.items() if k not in ("fill_idx", "net")},
                      "window_sharpe": metrics.sharpe(vec.tolist()),
                      "per_fill_mean_c": float(per.mean()) if len(per) else float("nan"),
                      "per_fill_t": metrics.tstat(per.tolist()),
                      "win_rate": float((per > 0).mean()) if len(per) else float("nan")})
    stats.sort(key=lambda s: (s["window_sharpe"] if s["window_sharpe"] == s["window_sharpe"] else -9),
               reverse=True)
    return stats


def run_mine_maker(*, series="KXBTC15M", lead_seconds=180.0, exec_lag_seconds=0.0,
                   top_features=10, embargo=1, queue="through", maker_fee_rate=0.0,
                   registry_path=None, validate_holdout=True, verbose=True) -> dict:
    pn_all, cfg = engine._build_panel(series, lead_seconds, exec_lag_seconds)
    maker_fee = KalshiFeeModel(rate=maker_fee_rate,
                               status="ASSUMED_ZERO_MAKER_FEE" if maker_fee_rate == 0 else "ASSUMED")
    prints = load_trade_prints(cfg, series=series)
    nets = compute_maker_nets(pn_all, prints, maker_fee, queue=queue)
    pn = [o for o in pn_all if o.ticker in nets]      # keep windows with a tape
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))

    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn, set(vault.holdout_keys))

    feats = feature_factory.feature_names()
    screened = screen.screen_features(search_pn, feats, n_splits=5, embargo=embargo)
    kept = [s["feature"] for s in screened
            if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                         or s["oos_sign_stability"] >= 0.6)][:top_features]
    res = maker_search(search_pn, kept, nets)
    ranked = _rank(res)
    cum = reg.cumulative_trials(space_id="maker_v1", data_fingerprint=vault.fingerprint) + res["n_trials"]

    report = {"mode": "maker", "series": series, "queue": queue, "lead_seconds": lead_seconds,
              "n_windows": len(pn), "n_search": len(search_pn), "n_holdout": len(hold_pn),
              "n_features_kept": len(kept), "n_trials": res["n_trials"], "cumulative_trials": cum,
              "top_screened": screened[:6], "best": None, "gauntlet": None,
              "holdout_validation": None, "verdict": None}
    if ranked:
        best = ranked[0]
        report["best"] = best
        col = next(j for j, m in enumerate(res["meta"])
                   if m["feature"] == best["feature"] and m["tail"] == best["tail"]
                   and m["side"] == best["side"] and abs(m["q"] - best["q"]) < 1e-9)
        dsr = gauntlet.deflated_sharpe_ratio(res["matrix"][:, col].tolist(), n_trials=cum,
                                             trial_sharpes=[s["window_sharpe"] for s in ranked])
        pbo = gauntlet.pbo_cscv(res["matrix"], n_partitions=10)
        plateau_scores = {s["q"]: s["window_sharpe"] for s in ranked
                          if s["feature"] == best["feature"] and s["tail"] == best["tail"]
                          and s["side"] == best["side"]}
        plateau = gauntlet.parameter_plateau(plateau_scores) if len(plateau_scores) >= 3 else None
        report["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plateau}
        report["verdict"] = gauntlet.verdict(dsr, pbo, plateau=plateau)
        if report["verdict"]["passed"] and validate_holdout and hold_pn:
            hn = compute_maker_nets(hold_pn, prints, maker_fee, queue=queue)
            res_h = maker_search(hold_pn, [best["feature"]], hn, min_fills=5)
            if res_h["meta"]:
                hr = _rank(res_h)[0]
                report["holdout_validation"] = {"n_fills": hr.get("n_fills"),
                                                "mean_c": hr.get("per_fill_mean_c"),
                                                "t": hr.get("per_fill_t")}
    reg.log_run(data_fingerprint=vault.fingerprint, space_id="maker_v1", n_trials=res["n_trials"],
                candidates=[report["best"]] if report["best"] else [],
                meta={"mode": "maker", "series": series, "queue": queue,
                      "verdict_passed": bool(report["verdict"] and report["verdict"]["passed"])})
    if verbose:
        print(format_maker_report(report))
    return report


def format_maker_report(r: dict) -> str:
    L = [f"\n{'='*82}\nALPHA DISCOVERY ENGINE — MAKER-edge mine  {r['series']}  queue={r['queue']}  "
         f"lead={r['lead_seconds']}s\n{'='*82}",
         f"windows w/ tape: {r['n_windows']} -> {r['n_search']} search / {r['n_holdout']} holdout",
         f"kept {r['n_features_kept']} features; trials {r['n_trials']} (cum {r['cumulative_trials']})", "",
         "top features by |market-residual IC|:"]
    for s in r["top_screened"]:
        L.append(f"   {s['feature']:32s} IC_resid={s['ic_residual']:+.3f} stab={s['oos_sign_stability']:.2f}")
    b = r["best"]
    if not b:
        L.append("\nno eligible maker trials (too few fills).")
        return "\n".join(L)
    L += ["", f"best maker rule: {b['feature']} {b['tail']}-tail q{b['q']} -> rest {b['side']} bid  "
          f"(fills={b['n_fills']}, per_fill={b['per_fill_mean_c']:+.2f}c t={b['per_fill_t']:+.2f}, "
          f"win={b['win_rate']:.0%}, window_sharpe={b['window_sharpe']:+.3f})"]
    g = r["gauntlet"]; d = g["dsr"]
    L += ["", "GAUNTLET:",
          f"   Deflated Sharpe = {d['deflated_sharpe_ratio']:.3f} (raw {d['sharpe']:+.3f} vs "
          f"E[maxSR|{d['n_trials']}] {d['expected_max_sharpe']:.3f}) -> {'PASS' if d['significant'] else 'fail'}",
          f"   PBO = {g['pbo']['pbo']:.2f} -> {'PASS' if (g['pbo']['pbo']==g['pbo']['pbo'] and g['pbo']['pbo']<0.5) else 'fail'}"]
    if g["plateau"]:
        L.append(f"   plateau_ratio = {g['plateau'].get('plateau_ratio'):.2f} -> "
                 f"{'SPIKE (fail)' if g['plateau'].get('is_spike') else 'plateau (ok)'}")
    v = r["verdict"]
    L.append(f"\nVERDICT: {'*** MAKER EDGE SURVIVES ***' if v['passed'] else 'NO EDGE (rejected)'}")
    for reason in (v["reasons"] if not v["passed"] else []):
        L.append(f"   - {reason}")
    if r["holdout_validation"]:
        h = r["holdout_validation"]
        L.append(f"SEALED-HOLDOUT: fills={h['n_fills']} mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    return "\n".join(L)
