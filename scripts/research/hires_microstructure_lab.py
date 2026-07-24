"""Hi-res (sub-second / WS) microstructure research lab — READ-ONLY, no orders.

Exploits the joined-snapshot layer (`kalshi_hires_joined_snapshots`) to test whether
sub-second microstructure carries a 15m-binary edge the ~1-4s REST grid blurred away.
Everything here is backtest/measurement only; live submission is never touched.

Targets
  A) 15m window OUTCOME (label_yes_resolved): the tradeable target. Bar = the
     market-implied probability (mid of yes_ask / 1-no_ask), which no REST strategy
     has beaten after ~cost. Eval = walk-forward (purge+embargo) Brier/ECE + after-cost
     EV of a divergence taker, with the Kalshi price-dependent fee model.
  B) forward sub-second SPOT MOVE (next H ms): diagnostic — is there ANY exploitable
     microstructure structure at sub-second scale (information coefficients).

Sub-second features (only meaningful with WS data):
  z_fair      standardized distance-to-line ln(mid/ref)/(rv60*sqrt(T))  -> Phi(z) fair value
  mom_*       spot_return_250ms/1s/5s (short-horizon momentum/drift)
  perp_lead   perp_return_1s - spot_return_1s (perp leads spot)
  basis_chg_* basis_change_1s/5s (Kalshi-vs-CEX basis dynamics)
  size_imb    (yes_ask_size-no_ask_size)/(sum) (book pressure)
  rv60        point-in-time realized vol (sub-second)
  book_age    kalshi_book_age_ms (quote staleness)

Usage:
  python -m scripts.research.hires_microstructure_lab --series KXBTC15M \
      --start-date 20260608 --end-date 20260614 --mode all --lead-seconds 120
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

import numpy as np

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.reprice_lag_hires import load_joined


# --------------------------------------------------------------------------- #
# feature engineering
# --------------------------------------------------------------------------- #
def _f(x):
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def mkt_p_yes(row) -> float | None:
    ya, na = _f(row.get("yes_ask")), _f(row.get("no_ask"))
    if ya is None and na is None:
        return None
    lo = (1.0 - na) if na is not None else None      # YES value implied by NO ask
    hi = ya if ya is not None else None               # YES ask
    vals = [v for v in (lo, hi) if v is not None and 0.0 < v < 1.0]
    return sum(vals) / len(vals) if vals else None


def spread_cents(row) -> float | None:
    ya, na = _f(row.get("yes_ask")), _f(row.get("no_ask"))
    if ya is None or na is None:
        return None
    return (ya - (1.0 - na)) * 100.0


def features(row) -> dict:
    """Per-snapshot sub-second feature dict (None where the WS feed wasn't warm)."""
    mid = _f(row.get("coinbase_mid")) or _f(row.get("binance_mid"))
    ref = _f(row.get("reference_start_price"))
    secs = _f(row.get("seconds_to_close"))
    rv = _f(row.get("realized_vol_60s"))
    out = {
        "mkt_p": mkt_p_yes(row),
        "spread_c": spread_cents(row),
        "mom_250ms": _f(row.get("spot_return_250ms")),
        "mom_1s": _f(row.get("spot_return_1s")),
        "mom_5s": _f(row.get("spot_return_5s")),
        "perp_1s": _f(row.get("perp_return_1s")),
        "basis_chg_1s": _f(row.get("basis_change_1s")),
        "basis_chg_5s": _f(row.get("basis_change_5s")),
        "rv60": rv,
        "book_age_ms": _f(row.get("kalshi_book_age_ms")),
    }
    ys, ns = _f(row.get("yes_ask_size")), _f(row.get("no_ask_size"))
    out["size_imb"] = ((ys - ns) / (ys + ns)) if (ys is not None and ns is not None and ys + ns > 0) else None
    pl = _f(row.get("perp_return_1s"))
    out["perp_lead"] = (pl - out["mom_1s"]) if (pl is not None and out["mom_1s"] is not None) else None
    # standardized distance-to-line (theoretical driver of P(YES) for GTE settle)
    if mid is not None and ref is not None and ref > 0 and rv and rv > 0 and secs and secs > 0:
        z = math.log(mid / ref) / (rv * math.sqrt(secs))
        out["z_fair"] = z
        out["phi_z"] = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))   # fair-value P(YES)
    else:
        out["z_fair"] = None
        out["phi_z"] = None
    out["dist_bps"] = ((mid - ref) / ref * 1e4) if (mid is not None and ref is not None and ref > 0) else None
    return out


# --------------------------------------------------------------------------- #
# calibration metrics
# --------------------------------------------------------------------------- #
def brier(ps, ys):
    return statistics.fmean((p - y) ** 2 for p, y in zip(ps, ys)) if ps else float("nan")


def ece(ps, ys, bins=10):
    if not ps:
        return float("nan")
    idx = defaultdict(list)
    for p, y in zip(ps, ys):
        b = min(bins - 1, int(p * bins))
        idx[b].append((p, y))
    n = len(ps)
    e = 0.0
    for b, pairs in idx.items():
        conf = statistics.fmean(p for p, _ in pairs)
        acc = statistics.fmean(y for _, y in pairs)
        e += (len(pairs) / n) * abs(conf - acc)
    return e


def log_loss(ps, ys, eps=1e-6):
    s = 0.0
    for p, y in zip(ps, ys):
        p = min(1 - eps, max(eps, p))
        s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return s / len(ps) if ps else float("nan")


# --------------------------------------------------------------------------- #
# decision-snapshot extraction (one row per window at ~lead seconds to close)
# --------------------------------------------------------------------------- #
def decision_rows(by_ticker, labels, *, lead_seconds, tol=20.0):
    """For each window, the snapshot whose seconds_to_close is closest to ``lead_seconds``.
    Returns list of (ticker, close_ms, y, feat_row_raw)."""
    out = []
    for tk, rows in by_ticker.items():
        lab = labels.get(tk, {})
        y = lab.get("label_yes_resolved")
        if y is None:
            continue
        best, bestd = None, tol + 1
        for r in rows:
            s = _f(r.get("seconds_to_close"))
            if s is None:
                continue
            d = abs(s - lead_seconds)
            if d < bestd:
                best, bestd = r, d
        if best is not None and bestd <= tol:
            out.append((tk, lab.get("close_ms") or best.get("close_ms") or best.get("as_of_ms"),
                        int(y), best))
    out.sort(key=lambda t: (t[1] if t[1] is not None else 0))
    return out


# --------------------------------------------------------------------------- #
# A) window-outcome model — walk-forward logistic vs market, after-cost EV
# --------------------------------------------------------------------------- #
FEATURE_SETS = {
    # physics-only fair value (no learned params beyond logistic on z)
    "fair_z": ["z_fair"],
    # sub-second microstructure only (NO mkt_p) — can it stand alone?
    "micro": ["z_fair", "mom_1s", "mom_5s", "perp_lead", "basis_chg_5s", "size_imb", "rv60"],
    # market + microstructure residual — does micro ADD to the market's own forecast?
    "mkt_plus_micro": ["mkt_p", "mom_1s", "mom_5s", "perp_lead", "basis_chg_5s", "size_imb"],
}


def _design(drows, names):
    X, Y, P_mkt = [], [], []
    for _tk, _c, y, raw in drows:
        feat = features(raw)
        mp = feat.get("mkt_p")
        if mp is None:
            continue
        vec = []
        ok = True
        for n in names:
            v = feat.get(n)
            if v is None:
                v = 0.0   # impute missing sub-second feature to neutral (honest: flagged via coverage)
            vec.append(v)
        if ok:
            X.append(vec)
            Y.append(y)
            P_mkt.append(mp)
    return np.array(X, float), np.array(Y, int), np.array(P_mkt, float)


def walk_forward_model(drows, names, *, folds=5, embargo=1, C=0.5):
    """Expanding-window walk-forward logistic. Returns OOS predictions aligned to test windows."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X, Y, Pmkt = _design(drows, names)
    n = len(Y)
    if n < 40 or len(set(Y.tolist())) < 2:
        return None
    fold_edges = [int(round(n * k / (folds + 1))) for k in range(1, folds + 2)]
    oos_p, oos_y, oos_mkt = [], [], []
    for i in range(1, len(fold_edges)):
        tr_end = fold_edges[i - 1]
        te_start = min(n, tr_end + embargo)
        te_end = fold_edges[i]
        if tr_end < 25 or te_start >= te_end:
            continue
        Xtr, Ytr = X[:tr_end], Y[:tr_end]
        if len(set(Ytr.tolist())) < 2:
            continue
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(C=C, max_iter=1000)
        clf.fit(sc.transform(Xtr), Ytr)
        p = clf.predict_proba(sc.transform(X[te_start:te_end]))[:, 1]
        oos_p.extend(p.tolist())
        oos_y.extend(Y[te_start:te_end].tolist())
        oos_mkt.extend(Pmkt[te_start:te_end].tolist())
    if len(oos_p) < 10:
        return None
    return {"p": oos_p, "y": oos_y, "mkt": oos_mkt, "n_oos": len(oos_p), "n_total": n}


def after_cost_eval(drows, res, fee: KalshiFeeModel, *, edge_thresh=0.03):
    """Trade when |model_p - mkt_p| clears cost; net cents per trade with real fees."""
    if res is None:
        return None
    p, y, mkt = res["p"], res["y"], res["mkt"]
    # we need the executable asks at the decision snapshot to price entries; reuse mkt as proxy
    # for the ask side (YES taker pays ~mkt+half-spread). To stay honest we charge the worse side.
    trades = []
    for pi, yi, mi in zip(p, y, mkt):
        diff = pi - mi
        if abs(diff) < edge_thresh:
            continue
        if diff > 0:                      # model: YES underpriced -> buy YES at ~mi
            price = min(0.99, mi)
            payoff = (1.0 - price) if yi == 1 else -price
        else:                              # buy NO at ~1-mi
            price = min(0.99, 1.0 - mi)
            payoff = (1.0 - price) if yi == 0 else -price
        fee_c = fee.taker_fee(price, 1.0) * 100.0
        trades.append(payoff * 100.0 - fee_c)
    if not trades:
        return {"n_trades": 0}
    mean = statistics.fmean(trades)
    se = (statistics.pstdev(trades) / math.sqrt(len(trades))) if len(trades) > 1 else float("nan")
    wins = sum(1 for t in trades if t > 0)
    return {"n_trades": len(trades), "net_c_mean": mean, "net_c_se": se,
            "t_stat": (mean / se) if se and se == se and se > 0 else float("nan"),
            "win_rate": wins / len(trades), "total_c": sum(trades)}


# --------------------------------------------------------------------------- #
# D) deep-favorite cell (④ re-test): calibration + after-cost taker EV by band,
#    optionally sharpened by |z_fair|. Returns per-band rows; pool across series.
# --------------------------------------------------------------------------- #
def favorite_cells(drows, fee: KalshiFeeModel, *, z_split=False):
    """For each decision window, take the FAVORITE side (implied>=0.5) and bucket by
    favorite-implied band. Report realized win-rate vs implied + after-cost taker EV."""
    bands = [(0.80, 0.90), (0.90, 0.95), (0.95, 0.98), (0.98, 1.01)]
    cells = defaultdict(list)   # (band, zbucket) -> list of (won, ask, fav_implied, side)
    for _tk, _c, y, raw in drows:
        mp = mkt_p_yes(raw)
        if mp is None:
            continue
        ya, na = _f(raw.get("yes_ask")), _f(raw.get("no_ask"))
        if mp >= 0.5:                 # favorite = YES
            fav_imp, ask, won, side = mp, ya, (y == 1), "YES"
        else:                          # favorite = NO
            fav_imp, ask, won, side = 1.0 - mp, na, (y == 0), "NO"
        if ask is None or not (0.0 < ask < 1.0):
            continue
        zb = "all"
        if z_split:
            z = features(raw).get("z_fair")
            if z is None:
                continue
            zb = "hi|z|" if abs(z) >= 1.0 else "lo|z|"
        for lo, hi in bands:
            if lo <= fav_imp < hi:
                cells[((lo, hi), zb)].append((won, ask, fav_imp, side))
                break
    out = []
    for (band, zb), obs in sorted(cells.items()):
        n = len(obs)
        if n == 0:
            continue
        winrate = statistics.fmean(1.0 if w else 0.0 for w, *_ in obs)
        imp = statistics.fmean(a for _w, a, *_ in obs)        # avg ask paid
        fav_imp = statistics.fmean(fi for _w, _a, fi, _s in obs)
        # after-cost taker buying the favorite at its ask
        nets = []
        for won, ask, *_ in obs:
            fee_c = fee.taker_fee(ask, 1.0) * 100.0
            nets.append(((1.0 - ask) if won else (-ask)) * 100.0 - fee_c)
        mean = statistics.fmean(nets)
        se = (statistics.pstdev(nets) / math.sqrt(n)) if n > 1 else float("nan")
        yn = sum(1 for _w, _a, _fi, s in obs if s == "YES")
        out.append({"band": f"{band[0]:.2f}-{band[1]:.2f}", "z": zb, "n": n,
                    "fav_implied": fav_imp, "avg_ask": imp, "realized_win": winrate,
                    "calib_gap_c": (winrate - fav_imp) * 100.0,
                    "net_c": mean, "net_se": se,
                    "t": (mean / se) if (se == se and se > 0) else float("nan"),
                    "yes_share": yn / n})
    return out


# --------------------------------------------------------------------------- #
# B) forward sub-second move — information coefficients
# --------------------------------------------------------------------------- #
def forward_returns(by_ticker, horizon_ms):
    """Per-row forward spot log-return over horizon_ms (no look-ahead beyond horizon)."""
    samples = []   # (feat_dict, fwd_ret)
    for tk, rows in by_ticker.items():
        seq = [(_f(r.get("as_of_ms")), _f(r.get("coinbase_mid")) or _f(r.get("binance_mid")), r)
               for r in rows]
        seq = [(t, m, r) for t, m, r in seq if t is not None and m is not None and m > 0]
        j = 0
        for i in range(len(seq)):
            ti, mi, ri = seq[i]
            tgt = ti + horizon_ms
            if j < i:
                j = i
            while j < len(seq) and seq[j][0] < tgt:
                j += 1
            if j >= len(seq):
                break
            fwd = math.log(seq[j][1] / mi)
            samples.append((features(ri), fwd))
    return samples


def ic_table(samples, sig_names):
    from scipy.stats import spearmanr
    out = {}
    for s in sig_names:
        xs, ys = [], []
        for feat, fwd in samples:
            v = feat.get(s)
            if v is not None and fwd is not None and math.isfinite(fwd):
                xs.append(v)
                ys.append(fwd)
        if len(xs) >= 200 and len(set(xs)) > 5:
            rho, pval = spearmanr(xs, ys)
            out[s] = {"ic": rho, "p": pval, "n": len(xs)}
        else:
            out[s] = {"ic": float("nan"), "p": float("nan"), "n": len(xs)}
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def run(series, start, end, *, lead_seconds, mode, config=None):
    cfg = config or load_config(mode="paper")
    fee = KalshiFeeModel.from_config(cfg)
    print(f"\n{'='*78}\nHIRES MICROSTRUCTURE LAB — {series}  [{start}..{end}]  lead={lead_seconds}s\n{'='*78}")
    jr = load_joined(cfg, start_date=start, end_date=end)
    by_ticker = {tk: rows for tk, rows in jr["by_ticker"].items() if str(tk).startswith(series)}
    labels = jr["labels"]
    n_lab = sum(1 for tk in by_ticker if labels.get(tk, {}).get("label_yes_resolved") is not None)
    print(f"loaded: {sum(len(v) for v in by_ticker.values()):,} snapshots / {len(by_ticker)} windows "
          f"({n_lab} with OFFICIAL labels)")

    drows = decision_rows(by_ticker, labels, lead_seconds=lead_seconds)
    print(f"decision snapshots @~{lead_seconds}s-to-close: {len(drows)} windows")
    if drows:
        ybar = statistics.fmean(y for *_x, y, _r in drows)
        print(f"  base rate P(YES)={ybar:.3f}")

    if mode in ("all", "model") and len(drows) >= 40:
        # market baseline calibration
        mkt_p, ys = [], []
        for *_x, y, raw in drows:
            mp = mkt_p_yes(raw)
            if mp is not None:
                mkt_p.append(mp); ys.append(y)
        print(f"\n-- MARKET-IMPLIED baseline (the bar) --  n={len(ys)}")
        print(f"   Brier={brier(mkt_p, ys):.4f}  ECE={ece(mkt_p, ys):.4f}  logloss={log_loss(mkt_p, ys):.4f}")

        # physics fair value (phi_z) calibration
        pz, yz = [], []
        for *_x, y, raw in drows:
            v = features(raw).get("phi_z")
            if v is not None:
                pz.append(v); yz.append(y)
        if pz:
            print(f"-- Phi(z) physics fair value --  n={len(pz)} (cov={len(pz)/len(drows):.0%})")
            print(f"   Brier={brier(pz, yz):.4f}  ECE={ece(pz, yz):.4f}")

        for setname, names in FEATURE_SETS.items():
            res = walk_forward_model(drows, names)
            if res is None:
                print(f"\n-- model[{setname}] --  insufficient/degenerate")
                continue
            b = brier(res["p"], res["y"]); e = ece(res["p"], res["y"]); ll = log_loss(res["p"], res["y"])
            bm = brier(res["mkt"], res["y"])
            ac = after_cost_eval(drows, res, fee)
            print(f"\n-- model[{setname}]  feats={names} --  OOS n={res['n_oos']}/{res['n_total']}")
            print(f"   model Brier={b:.4f} ECE={e:.4f} logloss={ll:.4f}  |  mkt Brier(same rows)={bm:.4f}  "
                  f"deltaBrier(model-mkt)={b-bm:+.4f}")
            if ac and ac.get("n_trades"):
                print(f"   after-cost taker: trades={ac['n_trades']} net_c/trade={ac['net_c_mean']:+.3f} "
                      f"+/-{ac['net_c_se']:.3f} (t={ac['t_stat']:+.2f}) win={ac['win_rate']:.2%} "
                      f"total={ac['total_c']:+.1f}c")
            else:
                print(f"   after-cost taker: no trades cleared the divergence threshold")

    if mode in ("all", "favorite") and drows:
        print(f"\n-- deep-favorite cell (taker, after real fee) --")
        rowsf = favorite_cells(drows, fee, z_split=True)
        print(f"   {'band':11s} {'z':6s} {'n':>4s} {'fav_imp':>7s} {'realwin':>7s} "
              f"{'gap_c':>6s} {'net_c':>7s} {'t':>5s} {'yes%':>5s}")
        for r in rowsf:
            print(f"   {r['band']:11s} {r['z']:6s} {r['n']:>4d} {r['fav_implied']:>7.3f} "
                  f"{r['realized_win']:>7.3f} {r['calib_gap_c']:>+6.1f} {r['net_c']:>+7.2f} "
                  f"{r['t']:>+5.1f} {r['yes_share']:>5.0%}")

    if mode in ("all", "ic"):
        print(f"\n-- forward sub-second move ICs (Spearman, diagnostic) --")
        for H in (1000, 5000):
            samples = forward_returns(by_ticker, H)
            tab = ic_table(samples, ["mom_250ms", "mom_1s", "mom_5s", "perp_lead",
                                     "basis_chg_1s", "basis_chg_5s", "size_imb", "z_fair"])
            print(f"   horizon={H}ms  (n_samples={len(samples):,})")
            for s, d in sorted(tab.items(), key=lambda kv: -(abs(kv[1]['ic']) if kv[1]['ic']==kv[1]['ic'] else -1)):
                flag = "  <--" if (d["ic"] == d["ic"] and abs(d["ic"]) > 0.03 and d["p"] < 0.01) else ""
                print(f"     {s:14s} IC={d['ic']:+.4f} p={d['p']:.3g} n={d['n']:,}{flag}")

    return {"series": series, "n_windows": len(by_ticker), "n_decision": len(drows)}


SERIES_DATA_DIR = {
    "KXBTC15M": "data",
    "KXETH15M": "data/series/KXETH15M", "KXSOL15M": "data/series/KXSOL15M",
    "KXDOGE15M": "data/series/KXDOGE15M", "KXXRP15M": "data/series/KXXRP15M",
}


def run_pooled_favorites(series_list, *, lead_seconds, start=None, end=None):
    """Pool decision-window favorites across series for honest n in each band.
    Reports per-series counts + the POOLED cell table (multiple-comparison aware)."""
    import os
    fee = KalshiFeeModel()
    all_drows = []
    per_series_n = {}
    for s in series_list:
        os.environ["DATA_DIR"] = SERIES_DATA_DIR.get(s, "data")
        cfg = load_config(mode="paper")
        st, en = (start, end) if s == "KXBTC15M" else (None, None)
        jr = load_joined(cfg, start_date=st, end_date=en)
        by_ticker = {tk: rows for tk, rows in jr["by_ticker"].items() if str(tk).startswith(s)}
        dr = decision_rows(by_ticker, jr["labels"], lead_seconds=lead_seconds)
        per_series_n[s] = len(dr)
        all_drows.extend(dr)
    print(f"\n{'='*78}\nPOOLED DEEP-FAVORITE CELL — {series_list}  lead={lead_seconds}s\n{'='*78}")
    print(f"decision windows per series: {per_series_n}  pooled={len(all_drows)}")
    for zsplit, title in ((False, "ALL"), (True, "split by |z_fair|")):
        print(f"\n-- pooled favorite taker EV ({title}) --")
        rowsf = favorite_cells(all_drows, fee, z_split=zsplit)
        print(f"   {'band':11s} {'z':6s} {'n':>4s} {'fav_imp':>7s} {'realwin':>7s} "
              f"{'gap_c':>6s} {'net_c':>7s} {'t':>5s} {'yes%':>5s}")
        for r in rowsf:
            print(f"   {r['band']:11s} {r['z']:6s} {r['n']:>4d} {r['fav_implied']:>7.3f} "
                  f"{r['realized_win']:>7.3f} {r['calib_gap_c']:>+6.1f} {r['net_c']:>+7.2f} "
                  f"{r['t']:>+5.1f} {r['yes_share']:>5.0%}")
    print("\n  NOTE: pooling mixes assets; treat as power-boost not a single instrument. "
          "Many cells swept -> apply multiple-comparison skepticism (t>~3 to take seriously).")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hi-res microstructure research lab (READ-ONLY).")
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--lead-seconds", type=float, default=120.0)
    ap.add_argument("--mode", choices=("all", "model", "ic", "favorite", "favorite-pool"),
                    default="all")
    ap.add_argument("--data-dir", default=None, help="override DATA_DIR (per-series alts)")
    args = ap.parse_args(argv)
    if args.mode == "favorite-pool":
        run_pooled_favorites(["KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"],
                             lead_seconds=args.lead_seconds,
                             start=args.start_date, end=args.end_date)
        return
    if args.data_dir:
        import os
        os.environ["DATA_DIR"] = args.data_dir
    run(args.series, args.start_date, args.end_date,
        lead_seconds=args.lead_seconds, mode=args.mode)


if __name__ == "__main__":
    main()
