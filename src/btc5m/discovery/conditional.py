"""Regime-conditional mining — the disciplined search for a CONDITIONAL edge.

The market is efficient on average; this asks whether it mis-prices in a specific regime
(high vol, thin liquidity, low volume, strong trend, a time-of-day, an options-vol regime).
The danger is obvious: slice the data enough ways and one pocket looks profitable by luck.
So the DSR for ANY regime's best candidate is deflated by the TOTAL trials across ALL regime
cells (not just that cell), and the cross-cell selection variance feeds the benchmark. A
conditional edge must be strong enough to clear the whole multiple-testing budget. READ-ONLY."""
from __future__ import annotations

import os

from ..venues.kalshi.fees import KalshiFeeModel
from . import (engine, feature_factory, gauntlet, holdout, panel, regimes, registry,
               screen, search)

MIN_CELL_WINDOWS = 70


def run_conditional_mine(*, series="KXBTC15M", lead_seconds=180.0, exec_lag_seconds=3.0,
                         top_features=10, embargo=1, registry_path=None, verbose=True) -> dict:
    pn_all, cfg = engine._build_panel(series, lead_seconds, exec_lag_seconds)
    fee = KalshiFeeModel.from_config(cfg)
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))
    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))

    tags = regimes.assign_regimes(search_pn)
    cells = regimes.regime_cells(tags)
    feat_list = feature_factory.feature_names()

    # feature coverage across the search set (so we can report volume/Deribit availability)
    cover = {}
    for f in feat_list:
        c = sum(1 for o in search_pn if o.feats.get(f) is not None)
        cover[f] = c / max(1, len(search_pn))

    # pass 1: per regime cell, screen + search; collect best + all sharpes for global deflation
    per_cell, all_sharpes, n_total = [], [], 0
    for dim, bucket in cells:
        sub = [o for o in search_pn if tags.get(o.ticker, {}).get(dim) == bucket]
        if len(sub) < MIN_CELL_WINDOWS:
            continue
        screened = screen.screen_features(sub, feat_list, n_splits=4, embargo=embargo)
        kept = [s["feature"] for s in screened
                if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                             or s["oos_sign_stability"] >= 0.6)][:top_features]
        res = search.generate_trials(sub, kept, fee, min_trades=15)
        if res["n_trials"] == 0:
            continue
        ranked = search.rank_trials(res)
        all_sharpes += [s["window_sharpe"] for s in ranked if s["window_sharpe"] == s["window_sharpe"]]
        n_total += res["n_trials"]
        per_cell.append({"dim": dim, "bucket": bucket, "n_windows": len(sub),
                         "best": ranked[0], "res": res, "ranked": ranked})

    cum = reg.cumulative_trials(space_id="conditional_v1", data_fingerprint=vault.fingerprint) + n_total

    # pass 2: gauntlet each cell's best, deflated by the GLOBAL trial budget
    for c in per_cell:
        b = c["best"]
        col = next(j for j, m in enumerate(c["res"]["meta"])
                   if m["feature"] == b["feature"] and m["tail"] == b["tail"]
                   and m["side"] == b["side"] and abs(m["q"] - b["q"]) < 1e-9)
        dsr = gauntlet.deflated_sharpe_ratio(c["res"]["matrix"][:, col].tolist(),
                                             n_trials=cum, trial_sharpes=all_sharpes)
        pbo = gauntlet.pbo_cscv(c["res"]["matrix"], n_partitions=8)
        plat_scores = {s["q"]: s["window_sharpe"] for s in c["ranked"]
                       if s["feature"] == b["feature"] and s["tail"] == b["tail"]
                       and s["side"] == b["side"]}
        plat = gauntlet.parameter_plateau(plat_scores) if len(plat_scores) >= 3 else None
        c["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plat}
        c["verdict"] = gauntlet.verdict(dsr, pbo, plateau=plat)

    per_cell.sort(key=lambda c: c["gauntlet"]["dsr"]["deflated_sharpe_ratio"]
                  if c["gauntlet"]["dsr"]["deflated_sharpe_ratio"] == c["gauntlet"]["dsr"]["deflated_sharpe_ratio"]
                  else -1, reverse=True)
    survivors = [c for c in per_cell if c["verdict"]["passed"]]

    # holdout validation of the single best survivor, on its OWN regime subset
    holdout_val = None
    if survivors:
        top = survivors[0]
        htags = regimes.assign_regimes(hold_pn, terciles_from=search_pn)
        hsub = [o for o in hold_pn if htags.get(o.ticker, {}).get(top["dim"]) == top["bucket"]]
        rule = {k: top["best"][k] for k in ("feature", "tail", "thr", "side")}
        holdout_val = {**engine._eval_rule_on_panel(hsub, rule, fee),
                       "regime": f"{top['dim']}={top['bucket']}"}

    report = {"series": series, "n_windows": len(pn_all), "n_search": len(search_pn),
              "n_cells_tested": len(per_cell), "n_trials_total": n_total, "cumulative_trials": cum,
              "feature_coverage": cover, "cells": per_cell, "survivors": len(survivors),
              "holdout_validation": holdout_val}
    reg.log_run(data_fingerprint=vault.fingerprint, space_id="conditional_v1", n_trials=n_total,
                candidates=[c["best"] for c in per_cell[:3]],
                meta={"mode": "conditional", "survivors": len(survivors)})
    if verbose:
        print(format_conditional_report(report))
    return report


def format_conditional_report(r: dict) -> str:
    L = [f"\n{'='*84}\nALPHA DISCOVERY ENGINE — REGIME-CONDITIONAL mine  {r['series']}\n{'='*84}",
         f"windows {r['n_windows']} (search {r['n_search']}); regime cells tested {r['n_cells_tested']}; "
         f"total trials {r['n_trials_total']} (cum {r['cumulative_trials']}) -> DSR deflated by ALL slices"]
    # volume / deribit availability (the user asked we prioritize these)
    vol_feats = ["spot_trade_intensity_60s", "perp_trade_intensity_60s", "top_depth",
                 "yes_ask_size", "no_ask_size", "kalshi_top_size", "book_size_imb"]
    der_feats = [f for f in r["feature_coverage"] if f.startswith("deribit")]
    L.append("  volume/liquidity coverage: " + ", ".join(
        f"{f.replace('_60s','')}={r['feature_coverage'].get(f,0):.0%}" for f in vol_feats if f in r["feature_coverage"]))
    L.append("  deribit coverage: " + (", ".join(f"{f.split('deribit_')[1]}={r['feature_coverage'][f]:.0%}"
             for f in der_feats) or "none") + ("   (Deribit was OFF during collection -> nothing to mine)"
             if der_feats and max((r["feature_coverage"][f] for f in der_feats), default=0) < 0.05 else ""))
    L += ["", f"{'regime cell':18s} {'n':>4s} {'best rule':38s} {'per_trade':>9s} {'DSR':>5s} {'PBO':>5s} verdict",
          "-" * 84]
    for c in r["cells"][:18]:
        b, g = c["best"], c["gauntlet"]
        rule = f"{b['feature']}.{b['tail']}q{b['q']}->{b['side']}"
        L.append(f"  {c['dim']+'='+c['bucket']:16s} {c['n_windows']:>4d} {rule:38.38s} "
                 f"{b['per_trade_mean_c']:>+7.2f}c {g['dsr']['deflated_sharpe_ratio']:>5.2f} "
                 f"{g['pbo']['pbo']:>5.2f} {'PASS' if c['verdict']['passed'] else 'no'}")
    L.append("")
    if r["survivors"]:
        L.append(f"*** {r['survivors']} regime cell(s) PASSED the gauntlet ***")
        if r["holdout_validation"]:
            h = r["holdout_validation"]
            L.append(f"SEALED-HOLDOUT (regime {h['regime']}): n={h['n_trades']} mean={h['mean_c']:+.2f}c (t={h['t']:+.2f})")
    else:
        L.append("VERDICT: NO conditional edge — no regime cell cleared the (globally-deflated) gauntlet.")
    return "\n".join(L)
