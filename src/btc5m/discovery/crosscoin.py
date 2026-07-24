"""Path 1 — cross-coin relative-value mining (the first CROSS-SECTIONAL bet).

Every approach that has failed here was a single-instrument predictive bet, and the market
is efficient per instrument. This asks a different question: does ANOTHER coin's concurrent
state predict an alt's 15m outcome beyond the alt's own price? Crypto is highly correlated
intraday with BTC leading the alts, so:
  * attach BTC's underlying state (ret_60s/180s, distance-z, implied prob) sampled at each
    alt window's DECISION time via a fine-grained BTC time-clock (not BTC's 15m decision
    snapshots, which are ~15 min apart — too coarse);
  * add a lead-divergence feature (alt momentum - BTC momentum);
then pool the 4 alts (rank-normalized per asset) and run the gauntlet. A BTC-lead feature
with high IC vs the alt's market RESIDUAL (alt_y - alt_mkt_p) = BTC predicts what the alt's
market misses = a genuine cross-coin edge. READ-ONLY."""
from __future__ import annotations

import bisect
import os

from ..venues.kalshi.fees import KalshiFeeModel
from . import engine, feature_factory, gauntlet, holdout, panel, registry, screen, search

ALTS = ["KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"]
XFEATS = ["btc_ret_60s", "btc_ret_180s", "btc_dist_z", "btc_mkt_p", "lead_div_60s"]


def _f(x):
    try:
        return float(x) if x is not None and x == x else None
    except (TypeError, ValueError):
        return None


def build_btc_clock(series="KXBTC15M", lead_seconds=180.0):
    """Fine-grained (~1-4s) BTC state series keyed by epoch ms, from BTC's full feature rows."""
    from ..config import load_config
    from ..venues.kalshi.model_dataset import build_model_dataset
    os.environ["DATA_DIR"] = engine.SERIES_DATA_DIR[series]
    cfg = load_config(mode="paper")
    rows = build_model_dataset(cfg, series=series)["rows"]
    idx = []
    for r in rows:
        cm = r.get("market_close_ts_ms") or r.get("close_ms")
        s = _f(r.get("seconds_to_close"))
        if cm is None or s is None:
            continue
        idx.append((int(cm - s * 1000), {
            "btc_ret_60s": _f(r.get("spot_return_60s")),
            "btc_ret_180s": _f(r.get("spot_return_180s")),
            "btc_dist_z": _f(r.get("distance_to_line_vol_normalized")),
            "btc_mkt_p": panel.market_prob_yes(r),
        }))
    idx.sort(key=lambda t: t[0])
    return idx


def attach_concurrent(alt_obs, btc_clock, *, tol_ms=8000):
    ts = [t for t, _ in btc_clock]
    matched = 0
    for o in alt_obs:
        if o.t0_ms is None:
            continue
        i = bisect.bisect_left(ts, o.t0_ms)
        best, bestd = None, tol_ms + 1
        for j in (i - 1, i):
            if 0 <= j < len(ts):
                d = abs(ts[j] - o.t0_ms)
                if d < bestd:
                    best, bestd = btc_clock[j][1], d
        if best is None or bestd > tol_ms:
            continue
        matched += 1
        for k, v in best.items():
            o.feats[k] = v
        own = o.feats.get("spot_return_60s")
        if own is not None and best.get("btc_ret_60s") is not None:
            o.feats["lead_div_60s"] = own - best["btc_ret_60s"]
    return matched


def run_crosscoin_mine(*, lead_seconds=180.0, exec_lag_seconds=3.0, top_features=12, embargo=1,
                       registry_path=None, validate_holdout=True, verbose=True) -> dict:
    btc_clock = build_btc_clock(lead_seconds=lead_seconds)
    pn_raw, per_asset, matched_tot = [], {}, 0
    fee = None
    for s in ALTS:
        pn, cfg = engine._build_panel(s, lead_seconds, exec_lag_seconds)
        m = attach_concurrent(pn, btc_clock)
        per_asset[s] = {"windows": len(pn), "btc_matched": m}
        matched_tot += m
        pn_raw.extend(pn)
        fee = KalshiFeeModel.from_config(cfg)
    pn_all = panel.rank_normalize_per_asset(pn_raw)
    reg = registry.TrialRegistry(registry_path
                                 or os.path.join("data", "discovery", "trial_registry.jsonl"))

    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn_all]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn_all, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn_all, set(vault.holdout_keys))

    feat_list = feature_factory.feature_names() + XFEATS
    screened = screen.screen_features(search_pn, feat_list, n_splits=5, embargo=embargo)
    kept = [s["feature"] for s in screened
            if s["coverage"] >= 0.5 and (s["oos_sign_stability"] != s["oos_sign_stability"]
                                         or s["oos_sign_stability"] >= 0.6)][:top_features]
    # ensure cross-coin features are in the search even if just outside top-N (they ARE the point)
    for xf in XFEATS:
        if xf not in kept and any(s["feature"] == xf and s["coverage"] >= 0.5 for s in screened):
            kept.append(xf)
    res = search.generate_trials(search_pn, kept, fee)
    ranked = search.rank_trials(res)
    cum = reg.cumulative_trials(space_id="crosscoin_v1",
                               data_fingerprint=vault.fingerprint) + res["n_trials"]

    report = {"mode": "crosscoin", "alts": ALTS, "per_asset": per_asset,
              "btc_matched_total": matched_tot, "lead_seconds": lead_seconds,
              "n_windows": len(pn_all), "n_search": len(search_pn), "n_holdout": len(hold_pn),
              "vault": vault.fingerprint[:16], "kept": kept, "n_trials": res["n_trials"],
              "cumulative_trials": cum, "screened_x": [s for s in screened if s["feature"] in XFEATS],
              "top_screened": screened[:8], "best": None, "gauntlet": None,
              "per_asset_best": None, "holdout_validation": None, "verdict": None}
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
        rule = {k: best[k] for k in ("feature", "tail", "thr", "side")}
        per_asset_best, rep = {}, 0
        for s in ALTS:
            sub = [o for o in search_pn if o.asset == s]
            r = engine._eval_rule_on_panel(sub, rule, fee)
            per_asset_best[s] = r
            if r["n_trades"] >= 8 and r["mean_c"] > 0:
                rep += 1
        report["per_asset_best"] = per_asset_best
        report["gauntlet"] = {"dsr": dsr, "pbo": pbo.as_dict(), "plateau": plateau}
        v = gauntlet.verdict(dsr, pbo, plateau=plateau, replication_assets=rep, replication_required=3)
        report["verdict"] = v
        if v["passed"] and validate_holdout and hold_pn:
            report["holdout_validation"] = engine._eval_rule_on_panel(hold_pn, rule, fee)
    reg.log_run(data_fingerprint=vault.fingerprint, space_id="crosscoin_v1", n_trials=res["n_trials"],
                candidates=[report["best"]] if report["best"] else [],
                meta={"mode": "crosscoin", "verdict_passed":
                      bool(report["verdict"] and report["verdict"]["passed"])})
    if verbose:
        print(format_crosscoin_report(report))
    return report


def format_crosscoin_report(r: dict) -> str:
    L = [f"\n{'='*82}\nALPHA DISCOVERY ENGINE — CROSS-COIN relative value (BTC-lead)  "
         f"lead={r['lead_seconds']}s\n{'='*82}",
         f"alts: {r['per_asset']}", f"BTC concurrent matches: {r['btc_matched_total']}",
         f"pooled windows: {r['n_windows']} -> {r['n_search']} search / {r['n_holdout']} holdout "
         f"(vault {r['vault']})",
         f"kept {len(r['kept'])} features; trials {r['n_trials']} (cum {r['cumulative_trials']})", "",
         "CROSS-COIN feature screen (IC vs alt market-RESIDUAL = does BTC predict what the alt misses?):"]
    for s in r["screened_x"]:
        L.append(f"   {s['feature']:16s} IC_resid={s['ic_residual']:+.3f} IC_out={s['ic_outcome']:+.3f} "
                 f"stab={s['oos_sign_stability']:.2f} cov={s['coverage']:.0%}")
    b = r["best"]
    if not b:
        L.append("\nno eligible trials.")
        return "\n".join(L)
    L += ["", f"best rule: {b['feature']} {b['tail']}-tail q{b['q']} -> buy {b['side']}  "
          f"(n={b['n_trades']}, per_trade={b['per_trade_mean_c']:+.2f}c t={b['per_trade_t']:+.2f}, "
          f"window_sharpe={b['window_sharpe']:+.3f})", "", "per-asset breakdown of that rule:"]
    for s, rr in r["per_asset_best"].items():
        L.append(f"   {s:10s} n={rr['n_trades']:>4d} mean={rr['mean_c']:+.2f}c t={rr['t']:+.2f}")
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
