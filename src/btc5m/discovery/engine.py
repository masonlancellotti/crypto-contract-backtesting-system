"""Stage 0-5 orchestrator — run the discovery pipeline end to end, honestly.

Load the window panel, seal a holdout vault, screen features on the search set, search
after-cost entry rules, force the best through the gauntlet (DSR deflated by the CUMULATIVE
trial budget, PBO, parameter plateau, cross-asset replication), and ONLY if it survives,
validate it once on the sealed holdout. Every run is logged to the registry. The expected
honest outcome on this near-efficient market is 'no edge survives' — that is a feature."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np

from ..venues.kalshi.fees import KalshiFeeModel
from . import feature_factory, gauntlet, holdout, panel, registry, screen, search

SERIES_DATA_DIR = {
    "KXBTC15M": "data", "KXETH15M": "data/series/KXETH15M", "KXSOL15M": "data/series/KXSOL15M",
    "KXDOGE15M": "data/series/KXDOGE15M", "KXXRP15M": "data/series/KXXRP15M",
}
SPACE_ID = "binary_v1"
ALTS = ["KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"]


def _build_panel(series, lead_seconds, exec_lag_seconds):
    from ..config import load_config
    from ..venues.kalshi.model_dataset import build_model_dataset
    os.environ["DATA_DIR"] = SERIES_DATA_DIR.get(series, "data")
    cfg = load_config(mode="paper")
    rows = build_model_dataset(cfg, series=series)["rows"]
    return panel.build_panel(rows, asset=series, lead_seconds=lead_seconds,
                             exec_lag_seconds=exec_lag_seconds), cfg


def _eval_rule_on_panel(pn, rule, fee):
    """Per-trade after-cost net cents of `rule` on an arbitrary panel (for replication/holdout)."""
    fv = np.array([(o.feats.get(rule["feature"]) if o.feats.get(rule["feature"]) is not None
                    else np.nan) for o in pn], dtype=float)
    valid = ~np.isnan(fv)
    trade = valid & ((fv >= rule["thr"]) if rule["tail"] == "hi" else (fv <= rule["thr"]))
    nets = []
    for o, t in zip(pn, trade):
        if not t:
            continue
        if rule["side"] == "YES":
            nets.append(100.0 * (o.y - o.exec_yes) - fee.taker_fee(o.exec_yes, 1) * 100.0)
        else:
            nets.append(100.0 * ((1 - o.y) - o.exec_no) - fee.taker_fee(o.exec_no, 1) * 100.0)
    from . import metrics
    return {"n_trades": len(nets), "mean_c": (metrics.mean(nets) if nets else float("nan")),
            "t": (metrics.tstat(nets) if len(nets) > 1 else float("nan"))}


def run_mine(*, series: str = "KXBTC15M", lead_seconds: float = 180.0, top_features: int = 10,
             n_groups: int = 8, k_test: int = 2, embargo: int = 1, exec_lag_seconds: float = 3.0,
             registry_path: str | None = None, validate_holdout: bool = True,
             replicate: bool = True, verbose: bool = True) -> dict:
    pn_all, cfg = _build_panel(series, lead_seconds, exec_lag_seconds)
    fee = KalshiFeeModel.from_config(cfg)
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))

    # vault: seal the holdout from the full panel windows
    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))

    # Stage 2 — screen
    feats = feature_factory.feature_names()
    screened = screen.screen_features(search_pn, feats, n_splits=5, embargo=embargo)
    # keep top by |residual IC| with non-trivial coverage and OOS sign-stability
    kept = [s["feature"] for s in screened
            if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                         or s["oos_sign_stability"] >= 0.6)][:top_features]

    # Stage 3 — search trials on the SEARCH set only
    res = search.generate_trials(search_pn, kept, fee)
    ranked = search.rank_trials(res)
    n_trials = res["n_trials"]
    cum_trials = reg.cumulative_trials(space_id=SPACE_ID,
                                       data_fingerprint=vault.fingerprint) + n_trials

    report = {"series": series, "lead_seconds": lead_seconds,
              "exec_lag_seconds": exec_lag_seconds,
              "feature_version": feature_factory.version(),
              "n_windows_total": len(pn_all), "n_search": len(search_pn),
              "n_holdout": len(hold_pn), "vault_fingerprint": vault.fingerprint[:16],
              "n_features_screened": len(screened), "n_features_kept": len(kept),
              "kept_features": kept, "n_trials_this_run": n_trials,
              "cumulative_trials": cum_trials, "top_screened": screened[:8],
              "best": None, "gauntlet": None, "holdout_validation": None,
              "replication": None, "verdict": None}

    if ranked:
        best = ranked[0]
        report["best"] = best
        all_sharpes = [s["window_sharpe"] for s in ranked]
        col = next(j for j, m in enumerate(res["meta"])
                   if m["feature"] == best["feature"] and m["tail"] == best["tail"]
                   and m["side"] == best["side"] and abs(m["q"] - best["q"]) < 1e-9)
        dsr = gauntlet.deflated_sharpe_ratio(res["matrix"][:, col].tolist(),
                                             n_trials=cum_trials, trial_sharpes=all_sharpes)
        pbo = gauntlet.pbo_cscv(res["matrix"], n_partitions=10)
        plateau_scores = {s["q"]: s["window_sharpe"] for s in ranked
                          if s["feature"] == best["feature"] and s["tail"] == best["tail"]
                          and s["side"] == best["side"]}
        plateau = gauntlet.parameter_plateau(plateau_scores) if len(plateau_scores) >= 3 else None

        # replication: only worth paying for if DSR & PBO already look interesting
        rep_count = None
        if replicate and dsr["significant"] and pbo.pbo == pbo.pbo and pbo.pbo < 0.5:
            rep_count = 0
            rule = {k: best[k] for k in ("feature", "tail", "thr", "side")}
            for alt in ALTS:
                try:
                    alt_pn, alt_cfg = _build_panel(alt, lead_seconds, exec_lag_seconds)
                    r = _eval_rule_on_panel(alt_pn, rule, KalshiFeeModel.from_config(alt_cfg))
                    if r["n_trades"] >= 15 and r["mean_c"] > 0:
                        rep_count += 1
                    report.setdefault("replication_detail", {})[alt] = r
                except Exception as e:  # noqa: BLE001
                    report.setdefault("replication_detail", {})[alt] = {"error": repr(e)}
        report["replication"] = rep_count
        report["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plateau}
        v = gauntlet.verdict(dsr, pbo, plateau=plateau, replication_assets=rep_count)
        report["verdict"] = v

        # Stage 5 — sealed-holdout validation, ONLY for a gauntlet survivor
        if v["passed"] and validate_holdout and hold_pn:
            rule = {k: best[k] for k in ("feature", "tail", "thr", "side")}
            report["holdout_validation"] = _eval_rule_on_panel(hold_pn, rule, fee)

    reg.log_run(data_fingerprint=vault.fingerprint, space_id=SPACE_ID, n_trials=n_trials,
                candidates=[report["best"]] if report["best"] else [],
                meta={"series": series, "lead_seconds": lead_seconds,
                      "feature_version": feature_factory.version(),
                      "ts": datetime.now(timezone.utc).isoformat(),
                      "verdict_passed": bool(report["verdict"] and report["verdict"]["passed"])})
    if verbose:
        print(format_report(report))
    return report


def run_mine_pooled(*, series_list: list[str] | None = None, lead_seconds: float = 180.0,
                    exec_lag_seconds: float = 3.0, top_features: int = 10, embargo: int = 1,
                    registry_path: str | None = None, validate_holdout: bool = True,
                    verbose: bool = True) -> dict:
    """Cross-asset domain: pool all series with per-asset rank-normalized features and mine
    once. A rule that survives here had to generalize across independent assets — the
    strongest anti-overfit test we can run. Reports the per-asset breakdown of the best rule."""
    series_list = series_list or (["KXBTC15M"] + ALTS)
    fee = None
    pn_raw, per_asset = [], {}
    for s in series_list:
        pn, cfg = _build_panel(s, lead_seconds, exec_lag_seconds)
        per_asset[s] = len(pn)
        pn_raw.extend(pn)
        fee = KalshiFeeModel.from_config(cfg)
    pn_all = panel.rank_normalize_per_asset(pn_raw)
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))

    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))

    feats = feature_factory.feature_names()
    screened = screen.screen_features(search_pn, feats, n_splits=5, embargo=embargo)
    kept = [s["feature"] for s in screened
            if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                         or s["oos_sign_stability"] >= 0.6)][:top_features]
    res = search.generate_trials(search_pn, kept, fee)
    ranked = search.rank_trials(res)
    n_trials = res["n_trials"]
    cum = reg.cumulative_trials(space_id="binary_pooled_v1",
                               data_fingerprint=vault.fingerprint) + n_trials

    report = {"mode": "pooled", "series_list": series_list, "per_asset_windows": per_asset,
              "lead_seconds": lead_seconds, "exec_lag_seconds": exec_lag_seconds,
              "feature_version": feature_factory.version(), "n_windows_total": len(pn_all),
              "n_search": len(search_pn), "n_holdout": len(hold_pn),
              "vault_fingerprint": vault.fingerprint[:16], "n_features_kept": len(kept),
              "kept_features": kept, "n_trials_this_run": n_trials, "cumulative_trials": cum,
              "top_screened": screened[:8], "best": None, "gauntlet": None,
              "per_asset_best": None, "holdout_validation": None, "verdict": None}

    if ranked:
        best = ranked[0]
        report["best"] = best
        col = next(j for j, m in enumerate(res["meta"])
                   if m["feature"] == best["feature"] and m["tail"] == best["tail"]
                   and m["side"] == best["side"] and abs(m["q"] - best["q"]) < 1e-9)
        dsr = gauntlet.deflated_sharpe_ratio(res["matrix"][:, col].tolist(),
                                             n_trials=cum, trial_sharpes=[s["window_sharpe"] for s in ranked])
        pbo = gauntlet.pbo_cscv(res["matrix"], n_partitions=10)
        plateau_scores = {s["q"]: s["window_sharpe"] for s in ranked
                          if s["feature"] == best["feature"] and s["tail"] == best["tail"]
                          and s["side"] == best["side"]}
        plateau = gauntlet.parameter_plateau(plateau_scores) if len(plateau_scores) >= 3 else None
        # per-asset breakdown of the best rule = the cross-asset replication, made explicit
        rule = {k: best[k] for k in ("feature", "tail", "thr", "side")}
        per_asset_best, rep_count = {}, 0
        for s in series_list:
            sub = [o for o in search_pn if o.asset == s]
            r = _eval_rule_on_panel(sub, rule, fee)
            per_asset_best[s] = r
            if r["n_trades"] >= 10 and r["mean_c"] > 0:
                rep_count += 1
        report["per_asset_best"] = per_asset_best
        report["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plateau}
        v = gauntlet.verdict(dsr, pbo, plateau=plateau, replication_assets=rep_count,
                             replication_required=3)
        report["verdict"] = v
        if v["passed"] and validate_holdout and hold_pn:
            report["holdout_validation"] = _eval_rule_on_panel(hold_pn, rule, fee)

    reg.log_run(data_fingerprint=vault.fingerprint, space_id="binary_pooled_v1", n_trials=n_trials,
                candidates=[report["best"]] if report["best"] else [],
                meta={"mode": "pooled", "series": series_list, "lead_seconds": lead_seconds,
                      "exec_lag_seconds": exec_lag_seconds,
                      "verdict_passed": bool(report["verdict"] and report["verdict"]["passed"])})
    if verbose:
        print(format_pooled_report(report))
    return report


def format_pooled_report(r: dict) -> str:
    L = [f"\n{'='*82}\nALPHA DISCOVERY ENGINE — POOLED cross-asset mine  "
         f"lead={r['lead_seconds']}s exec_lag={r['exec_lag_seconds']}s  {r['feature_version']}\n{'='*82}",
         f"assets: {r['per_asset_windows']}",
         f"pooled windows: {r['n_windows_total']} -> {r['n_search']} search / {r['n_holdout']} holdout "
         f"(vault {r['vault_fingerprint']})  [features rank-normalized per asset]",
         f"kept {r['n_features_kept']} features; trials {r['n_trials_this_run']} (cum {r['cumulative_trials']})", "",
         "top features by |market-residual IC| (pooled, cross-asset):"]
    for s in r["top_screened"]:
        L.append(f"   {s['feature']:34s} IC_resid={s['ic_residual']:+.3f} stab={s['oos_sign_stability']:.2f} cov={s['coverage']:.0%}")
    b = r["best"]
    if not b:
        L.append("\nno eligible trials.")
        return "\n".join(L)
    L += ["", f"best rule: {b['feature']} {b['tail']}-tail q{b['q']} -> buy {b['side']}  "
          f"(n={b['n_trades']}, per_trade={b['per_trade_mean_c']:+.2f}c t={b['per_trade_t']:+.2f}, "
          f"window_sharpe={b['window_sharpe']:+.3f})", "",
          "per-asset breakdown of that rule (the cross-asset replication, explicit):"]
    for s, rr in r["per_asset_best"].items():
        L.append(f"   {s:10s} n={rr['n_trades']:>4d}  mean={rr['mean_c']:+.2f}c  t={rr['t']:+.2f}")
    g = r["gauntlet"]; d = g["dsr"]
    L += ["", "GAUNTLET:",
          f"   Deflated Sharpe = {d['deflated_sharpe_ratio']:.3f} (raw {d['sharpe']:+.3f} vs "
          f"E[maxSR|{d['n_trials']}] {d['expected_max_sharpe']:.3f}) -> {'PASS' if d['significant'] else 'fail'}",
          f"   PBO = {g['pbo']['pbo']:.2f} -> {'PASS' if (g['pbo']['pbo']==g['pbo']['pbo'] and g['pbo']['pbo']<0.5) else 'fail'}"]
    if g["plateau"]:
        L.append(f"   plateau_ratio = {g['plateau'].get('plateau_ratio'):.2f} -> "
                 f"{'SPIKE (fail)' if g['plateau'].get('is_spike') else 'plateau (ok)'}")
    v = r["verdict"]
    L.append(f"\nVERDICT: {'*** EDGE SURVIVES ***' if v['passed'] else 'NO EDGE (rejected)'}")
    for reason in (v["reasons"] if not v["passed"] else []):
        L.append(f"   - {reason}")
    if r["holdout_validation"]:
        h = r["holdout_validation"]
        L.append(f"SEALED-HOLDOUT: n={h['n_trades']} mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    return "\n".join(L)


def mine_prebuilt_panel(pn_all, fee, feat_list, *, space_id, label="", top_features=12,
                        embargo=1, registry_path=None, validate_holdout=True, verbose=True,
                        force_features=None) -> dict:
    """Run vault -> screen -> search -> gauntlet -> sealed-holdout on an ALREADY-built panel
    with a caller-supplied feature list (for augmented signals: cross-sectional, print
    microstructure, etc.). Shares the engine's discipline so new signals get an honest verdict."""
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))
    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))
    screened = screen.screen_features(search_pn, feat_list, n_splits=5, embargo=embargo)
    kept = [s["feature"] for s in screened
            if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                         or s["oos_sign_stability"] >= 0.6)][:top_features]
    for f in (force_features or []):
        if f not in kept and any(s["feature"] == f and s["coverage"] >= 0.4 for s in screened):
            kept.append(f)
    res = search.generate_trials(search_pn, kept, fee)
    ranked = search.rank_trials(res)
    cum = reg.cumulative_trials(space_id=space_id, data_fingerprint=vault.fingerprint) + res["n_trials"]
    rep = {"label": label, "n_windows": len(pn_all), "n_search": len(search_pn),
           "n_holdout": len(hold_pn), "kept": kept, "n_trials": res["n_trials"],
           "cumulative_trials": cum, "screened": screened[:10], "best": None,
           "gauntlet": None, "holdout_validation": None, "verdict": None}
    if ranked:
        b = ranked[0]
        rep["best"] = b
        col = next(j for j, m in enumerate(res["meta"])
                   if m["feature"] == b["feature"] and m["tail"] == b["tail"]
                   and m["side"] == b["side"] and abs(m["q"] - b["q"]) < 1e-9)
        dsr = gauntlet.deflated_sharpe_ratio(res["matrix"][:, col].tolist(), n_trials=cum,
                                             trial_sharpes=[s["window_sharpe"] for s in ranked])
        pbo = gauntlet.pbo_cscv(res["matrix"], n_partitions=10)
        plat = gauntlet.parameter_plateau({s["q"]: s["window_sharpe"] for s in ranked
                                           if s["feature"] == b["feature"] and s["tail"] == b["tail"]
                                           and s["side"] == b["side"]})
        rep["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plat}
        rep["verdict"] = gauntlet.verdict(dsr, pbo, plateau=plat)
        if rep["verdict"]["passed"] and validate_holdout and hold_pn:
            rule = {k: b[k] for k in ("feature", "tail", "thr", "side")}
            rep["holdout_validation"] = _eval_rule_on_panel(hold_pn, rule, fee)
    reg.log_run(data_fingerprint=vault.fingerprint, space_id=space_id, n_trials=res["n_trials"],
                candidates=[rep["best"]] if rep["best"] else [],
                meta={"label": label, "verdict_passed": bool(rep["verdict"] and rep["verdict"]["passed"])})
    if verbose:
        print(_fmt_prebuilt(rep, space_id))
    return rep


def _fmt_prebuilt(r, space_id):
    L = [f"\n{'='*82}\nADE mine [{space_id}] — {r['label']}\n{'='*82}",
         f"windows {r['n_windows']} (search {r['n_search']} / holdout {r['n_holdout']}); "
         f"kept {len(r['kept'])}; trials {r['n_trials']} (cum {r['cumulative_trials']})",
         "top features by |market-residual IC|:"]
    for s in r["screened"][:8]:
        L.append(f"   {s['feature']:30s} IC_resid={s['ic_residual']:+.3f} "
                 f"stab={s['oos_sign_stability']:.2f} cov={s['coverage']:.0%}")
    b = r["best"]
    if not b:
        return "\n".join(L + ["\nno eligible trials."])
    g = r["gauntlet"]; d = g["dsr"]
    L += ["", f"best rule: {b['feature']} {b['tail']}q{b['q']} -> {b['side']}  "
          f"(n={b['n_trades']}, per_trade={b['per_trade_mean_c']:+.2f}c t={b['per_trade_t']:+.2f}, "
          f"win_sharpe={b['window_sharpe']:+.3f})",
          f"GAUNTLET: DSR={d['deflated_sharpe_ratio']:.3f} (vs E[maxSR|{d['n_trials']}]={d['expected_max_sharpe']:.3f}) "
          f"PBO={g['pbo']['pbo']:.2f} " + (f"plateau={g['plateau'].get('plateau_ratio'):.2f}" if g['plateau'] else ""),
          f"VERDICT: {'*** EDGE SURVIVES ***' if r['verdict']['passed'] else 'NO EDGE (rejected)'}"]
    if not r["verdict"]["passed"]:
        for reason in r["verdict"]["reasons"]:
            L.append(f"   - {reason}")
    if r["holdout_validation"]:
        h = r["holdout_validation"]
        L.append(f"SEALED-HOLDOUT: n={h['n_trades']} mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    return "\n".join(L)


def format_report(r: dict) -> str:
    L = [f"\n{'='*82}\nALPHA DISCOVERY ENGINE — mine  {r['series']}  lead={r['lead_seconds']}s  "
         f"exec_lag={r.get('exec_lag_seconds')}s  features={r['feature_version']}\n{'='*82}",
         f"windows: {r['n_windows_total']} total -> {r['n_search']} search / {r['n_holdout']} "
         f"holdout (vault {r['vault_fingerprint']})",
         f"screened {r['n_features_screened']} features, kept {r['n_features_kept']}: {r['kept_features']}",
         f"trials this run: {r['n_trials_this_run']}  |  cumulative budget (DSR deflation N): "
         f"{r['cumulative_trials']}", "",
         "top features by |market-residual IC| (>0 = predicts what the market misses):"]
    for s in r["top_screened"]:
        L.append(f"   {s['feature']:34s} IC_resid={s['ic_residual']:+.3f} "
                 f"IC_out={s['ic_outcome']:+.3f} stab={s['oos_sign_stability']:.2f} cov={s['coverage']:.0%}")
    b = r["best"]
    if not b:
        L.append("\nno eligible trials (insufficient trade counts).")
        return "\n".join(L)
    L += ["", f"best trial: {b['feature']} {b['tail']}-tail q{b['q']} -> buy {b['side']} "
          f"(thr={b['thr']:.4g})",
          f"   n_trades={b['n_trades']}  per_trade={b['per_trade_mean_c']:+.2f}c "
          f"(t={b['per_trade_t']:+.2f})  win={b['win_rate']:.0%}  window_sharpe={b['window_sharpe']:+.3f}"]
    g = r["gauntlet"]
    d = g["dsr"]
    L += ["", "GAUNTLET:",
          f"   Deflated Sharpe = {d['deflated_sharpe_ratio']:.3f}  (raw SR {d['sharpe']:+.3f} vs "
          f"E[maxSR under {d['n_trials']} trials] {d['expected_max_sharpe']:.3f})  "
          f"-> {'PASS' if d['significant'] else 'fail'}",
          f"   PBO = {g['pbo']['pbo'] if g['pbo']['pbo']==g['pbo']['pbo'] else float('nan'):.2f}  "
          f"-> {'PASS' if (g['pbo']['pbo']==g['pbo']['pbo'] and g['pbo']['pbo']<0.5) else 'fail'}"]
    if g["plateau"]:
        L.append(f"   parameter plateau_ratio = {g['plateau'].get('plateau_ratio'):.2f} "
                 f"-> {'SPIKE (fail)' if g['plateau'].get('is_spike') else 'plateau (ok)'}")
    if r["replication"] is not None:
        L.append(f"   cross-asset replication = {r['replication']}/4 alts positive")
    v = r["verdict"]
    L.append(f"\nVERDICT: {'*** EDGE SURVIVES — validate on holdout ***' if v['passed'] else 'NO EDGE (rejected)'}")
    if not v["passed"]:
        for reason in v["reasons"]:
            L.append(f"   - {reason}")
    if r["holdout_validation"]:
        h = r["holdout_validation"]
        L.append(f"SEALED-HOLDOUT VALIDATION: n_trades={h['n_trades']} "
                 f"mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    return "\n".join(L)
