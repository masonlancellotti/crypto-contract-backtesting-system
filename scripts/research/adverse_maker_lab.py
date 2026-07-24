"""Adverse-selection-aware maker simulator — READ-ONLY, no orders.

The one open edge thread in this project is the MAKER lens: resting (passive) entries
save the spread+fee, but STATIC quoting dies to adverse selection (#14: naked legs avg
~ -21c when the market runs through one side; both-sides static -3.15c/quote). The
existing maker-entry study (`maker_entry.py`) posts a resting bid and HOLDS it to
fill/close -- it never cancels. Its own code flags the gap (maker_entry.py:589:
"cancel/replace latency not modeled. Next iteration needs trade [signals]").

EXP2 (ledger #22) proved sub-second microstructure carries REAL predictive structure for
the next 1-5s underlying move (mom_1s IC +0.195, robust, cross-asset) -- but it does NOT
bridge to a TAKER edge on the 15m binary (EXP1/EXP3 negative). This script tests the one
bridge nobody tested: does that real sub-second signal let a MAKER CANCEL adversely-
selected resting quotes before they fill, turning the negative static-maker result
positive?

Mechanic (per window, one resting quote per side at a decision snapshot):
  * resting YES bid at limit L = best YES bid = 1 - no_ask (binary identity; "join").
    Filled by taker_side=="no" prints at yes_price <= L (front) / < L (through).
  * BASELINE (hold-to-fill): if a print fills it before close, EV = (y_side - L)*100 - maker_fee.
  * CANCEL-AWARE: walk joined sub-second snapshots in (t0, t_fill]; if the adverse signal
    fires (for a YES quote: downward momentum mom_1s <= -theta) at any snap strictly
    BEFORE the fill, CANCEL -> no trade (EV 0). Else the fill stands. Decision uses only
    info available at cancel time (momentum over the trailing 1s); outcome is the window
    label -> no lookahead.

The crux is the diagnostic: do the CANCELLED fills have worse realized EV than the
SURVIVED fills? If yes, the signal selects losers and the cancel rule adds maker value.

Usage:
  python scripts/research/adverse_maker_lab.py --series KXBTC15M \
      --start-date 20260608 --end-date 20260614 --lead-seconds 120 --queue front
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
from collections import defaultdict

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.reprice_lag_hires import load_joined
from btc5m.venues.kalshi.backfill_trades import load_trade_prints

SERIES_DATA_DIR = {
    "KXBTC15M": "data",
    "KXETH15M": "data/series/KXETH15M", "KXSOL15M": "data/series/KXSOL15M",
    "KXDOGE15M": "data/series/KXDOGE15M", "KXXRP15M": "data/series/KXXRP15M",
}
BANDS = [(0.50, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 1.01)]


def _f(x):
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def yes_bid_from(row):
    """Best YES bid = 1 - best NO ask (binary identity). NO bid = 1 - YES ask."""
    na, ya = _f(row.get("no_ask")), _f(row.get("yes_ask"))
    yb = (1.0 - na) if na is not None else None
    nb = (1.0 - ya) if ya is not None else None
    return yb, nb


def mkt_p_yes(row):
    ya, na = _f(row.get("yes_ask")), _f(row.get("no_ask"))
    lo = (1.0 - na) if na is not None else None
    hi = ya if ya is not None else None
    vals = [v for v in (lo, hi) if v is not None and 0.0 < v < 1.0]
    return sum(vals) / len(vals) if vals else None


def decision_index(rows, lead_seconds, tol=20.0):
    """Index of the snapshot whose seconds_to_close is nearest lead_seconds (<= tol)."""
    best, bestd = None, tol + 1
    for i, r in enumerate(rows):
        s = _f(r.get("seconds_to_close"))
        if s is None:
            continue
        d = abs(s - lead_seconds)
        if d < bestd:
            best, bestd = i, d
    return best if (best is not None and bestd <= tol) else None


def first_print_fill_ms(prints, t0, close_ms, side, limit, queue):
    """First REAL print filling a resting `side` buy at `limit` (mirrors maker_entry)."""
    taker = "no" if side == "YES" else "yes"
    price_key = "yes_price" if side == "YES" else "no_price"
    eps = 1e-9
    for p in prints:
        ts = p.get("created_time_ms")
        if ts is None or ts <= t0:
            continue
        if close_ms is not None and ts >= close_ms:
            return None
        if p.get("taker_side") != taker:
            continue
        px = _f(p.get(price_key))
        if px is None:
            continue
        if (queue == "through" and px < limit - 0.005) or (queue == "front" and px <= limit + eps):
            return int(ts)
    return None


def first_adverse_ms(rows, i0, t_fill, side, theta):
    """Earliest snapshot recv time in (t0, t_fill) where momentum is adverse by >= theta.
    YES quote adverse = falling (mom_1s <= -theta); NO quote adverse = rising (mom_1s >= +theta).
    Falls back to mom_250ms if mom_1s missing."""
    for r in rows[i0 + 1:]:
        t = r.get("as_of_ms")
        if t is None or t >= t_fill:
            break
        mom = _f(r.get("spot_return_1s"))
        if mom is None:
            mom = _f(r.get("spot_return_250ms"))
        if mom is None:
            continue
        adverse = (mom <= -theta) if side == "YES" else (mom >= theta)
        if adverse:
            return int(t)
    return None


def band_of(fav_imp):
    for lo, hi in BANDS:
        if lo <= fav_imp < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return None


def load_inputs(series, start, end):
    """Load the heavy inputs ONCE so callers can sweep lead/theta in-memory."""
    cfg = load_config(mode="paper")
    jr = load_joined(cfg, start_date=start, end_date=end)
    by_ticker = {tk: rows for tk, rows in jr["by_ticker"].items() if str(tk).startswith(series)}
    prints_by_tk = load_trade_prints(cfg, series=series)
    return {"by_ticker": by_ticker, "labels": jr["labels"], "prints": prints_by_tk}


def simulate(series, inputs, *, lead_seconds, queue, theta, maker_fee_rate):
    fee = KalshiFeeModel(rate=maker_fee_rate,
                         status="ASSUMED_ZERO_MAKER_FEE" if maker_fee_rate == 0 else "ASSUMED")
    by_ticker = inputs["by_ticker"]
    labels = inputs["labels"]
    prints_by_tk = inputs["prints"]

    recs = []  # one per (window, side) that posted a quote
    n_win = n_win_used = 0
    for tk, rows in by_ticker.items():
        lab = labels.get(tk, {})
        y = lab.get("label_yes_resolved")
        prs = prints_by_tk.get(tk)
        if y is None or not rows or not prs:
            continue
        n_win += 1
        i0 = decision_index(rows, lead_seconds)
        if i0 is None:
            continue
        e = rows[i0]
        t0 = e.get("as_of_ms")
        close_ms = e.get("close_ms")
        if t0 is None:
            continue
        mp = mkt_p_yes(e)
        if mp is None:
            continue
        yb, nb = yes_bid_from(e)
        n_win_used += 1
        for side, limit, y_side, fav_imp in (
            ("YES", yb, int(y), mp),
            ("NO", nb, 1 - int(y), 1.0 - mp),
        ):
            if limit is None or not (0.0 < limit < 1.0):
                continue
            t_fill = first_print_fill_ms(prs, t0, close_ms, side, limit, queue)
            rec = {"tk": tk, "side": side, "fav_imp": fav_imp, "limit": limit,
                   "y_side": y_side, "filled": t_fill is not None,
                   "cancelled": False, "ev_c": None, "day": _day(t0)}
            if t_fill is not None:
                rec["ev_c"] = (y_side - limit) * 100.0 - fee.per_contract_fee(limit) * 100.0
                t_cancel = first_adverse_ms(rows, i0, t_fill, side, theta)
                rec["cancelled"] = t_cancel is not None
            recs.append(rec)
    return {"recs": recs, "n_windows": n_win, "n_windows_used": n_win_used,
            "series": series, "queue": queue, "theta": theta,
            "lead_seconds": lead_seconds, "maker_fee_rate": maker_fee_rate}


def _day(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ms else "?"


def _stats(vals):
    if not vals:
        return None
    m = statistics.fmean(vals)
    se = (statistics.pstdev(vals) / math.sqrt(len(vals))) if len(vals) > 1 else float("nan")
    return {"n": len(vals), "mean": m, "se": se,
            "t": (m / se) if (se == se and se > 0) else float("nan")}


def report(sim):
    recs = sim["recs"]
    filled = [r for r in recs if r["filled"]]
    survived = [r for r in filled if not r["cancelled"]]
    cancelled = [r for r in filled if r["cancelled"]]
    print(f"\n{'='*80}\nADVERSE-SELECTION-AWARE MAKER — {sim['series']}  lead={sim['lead_seconds']}s  "
          f"queue={sim['queue']}  theta={sim['theta']:.1e}  maker_fee={sim['maker_fee_rate']}\n{'='*80}")
    print(f"windows: {sim['n_windows']} labeled+prints, {sim['n_windows_used']} with a decision snapshot")
    print(f"quotes posted: {len(recs)}  filled: {len(filled)} ({len(filled)/max(1,len(recs)):.0%})  "
          f"-> cancelled-by-signal: {len(cancelled)} ({len(cancelled)/max(1,len(filled)):.0%})  "
          f"survived: {len(survived)}")

    base = _stats([r["ev_c"] for r in filled])
    surv = _stats([r["ev_c"] for r in survived])
    canc = _stats([r["ev_c"] for r in cancelled])
    print("\n-- maker EV per FILLED quote (cents) --")
    _line("hold-to-fill (BASELINE #13/#14)", base)
    _line("cancel-aware (survived only)", surv)
    _line("  >> cancelled fills (removed)", canc)
    if base and surv and base["mean"] == base["mean"]:
        print(f"\n  CRUX: cancel rule {'REMOVED LOSERS' if (canc and canc['mean'] < base['mean']) else 'did NOT select losers'} "
              f"-> survived EV {surv['mean']:+.2f}c vs baseline {base['mean']:+.2f}c "
              f"(delta {surv['mean']-base['mean']:+.2f}c); "
              f"cancelled-fill EV {canc['mean'] if canc else float('nan'):+.2f}c")

    # per-quote EV (cancel + unfilled count as 0) -- the honest "every attempt" view
    base_all = _stats([(r["ev_c"] if r["filled"] else 0.0) for r in recs])
    canc_all = _stats([(0.0 if (not r["filled"] or r["cancelled"]) else r["ev_c"]) for r in recs])
    print("\n-- maker EV per POSTED quote (unfilled & cancelled = 0c) --")
    _line("hold-to-fill", base_all)
    _line("cancel-aware", canc_all)

    # by favorite band
    print("\n-- by FAVORITE band: filled EV  hold vs survived (cents) --")
    print(f"   {'band':10s} {'side':4s} {'nfill':>5s} {'ncxl':>5s} {'hold_ev':>8s} {'surv_ev':>8s} {'delta':>7s}")
    byb = defaultdict(lambda: {"YES": [], "NO": []})
    for r in filled:
        b = band_of(r["fav_imp"])
        if b:
            byb[b][r["side"]].append(r)
    for b in sorted(byb):
        for side in ("YES", "NO"):
            grp = byb[b][side]
            if not grp:
                continue
            h = _stats([r["ev_c"] for r in grp])
            s = _stats([r["ev_c"] for r in grp if not r["cancelled"]])
            ncxl = sum(1 for r in grp if r["cancelled"])
            sev = f"{s['mean']:+.2f}" if s else "  --"
            dlt = f"{s['mean']-h['mean']:+.2f}" if (s and h) else "  --"
            print(f"   {b:10s} {side:4s} {h['n']:>5d} {ncxl:>5d} {h['mean']:>+8.2f} {sev:>8s} {dlt:>7s}")

    # naked-leg disaster check (#14): windows where exactly one side filled
    print("\n-- naked single-leg fills (#14 disaster source): hold vs cancel-aware --")
    byw = defaultdict(list)
    for r in filled:
        byw[r["tk"]].append(r)
    naked = [grp[0] for grp in byw.values() if len(grp) == 1]
    nh = _stats([r["ev_c"] for r in naked])
    ns = _stats([r["ev_c"] for r in naked if not r["cancelled"]])
    ncxl = sum(1 for r in naked if r["cancelled"])
    _line(f"naked legs hold-to-fill (n={len(naked)})", nh)
    _line(f"naked legs survived (cancelled {ncxl})", ns)
    print(f"\n{'.'*80}\nverdict inputs: survived-vs-baseline delta and naked-leg tail change are the signal. "
          f"A real edge needs survived EV > 0 with t>~2 AND cancelled-fill EV clearly < survived.\n")


def _line(label, st):
    if not st:
        print(f"   {label:38s}  (no data)")
        return
    print(f"   {label:38s}  n={st['n']:>4d}  mean={st['mean']:+.2f}c  se={st['se']:.2f}  t={st['t']:+.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Adverse-selection-aware maker simulator (READ-ONLY).")
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--lead-seconds", type=float, default=120.0)
    ap.add_argument("--lead-sweep", default=None,
                    help="comma list of lead seconds to sweep in one load (e.g. 120,300,450)")
    ap.add_argument("--queue", choices=("front", "through"), default="front")
    ap.add_argument("--theta-bps", type=float, default=2.0,
                    help="adverse 1s-momentum cancel threshold in bps (1 bp=1e-4 log-return); default 2")
    ap.add_argument("--theta-sweep", default=None,
                    help="comma list of theta bps to sweep (e.g. 1,2,3,5); overrides --theta-bps")
    ap.add_argument("--maker-fee-rate", type=float, default=0.0)
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    os.environ["DATA_DIR"] = args.data_dir or SERIES_DATA_DIR.get(args.series, "data")
    thetas = ([float(x) for x in args.theta_sweep.split(",")]
              if args.theta_sweep else [args.theta_bps])
    leads = ([float(x) for x in args.lead_sweep.split(",")]
             if args.lead_sweep else [args.lead_seconds])
    inputs = load_inputs(args.series, args.start_date, args.end_date)
    for lead in leads:
        for tb in thetas:
            sim = simulate(args.series, inputs, lead_seconds=lead, queue=args.queue,
                           theta=tb * 1e-4, maker_fee_rate=args.maker_fee_rate)
            report(sim)


if __name__ == "__main__":
    main()
