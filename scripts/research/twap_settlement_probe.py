"""Path 3 — settlement-TWAP final-60s mechanic. READ-ONLY.

These markets settle on a ~60s-average reference index at close. So at T = close - tau (tau<60),
the average over [close-60, T] is ALREADY realized/frozen; only [T, close] remains stochastic.
The settlement (>= start) is therefore more locked-in near close than an instantaneous-spot
model implies. Hypothesis: the market underweights this freezing, so the realized partial
average ('frozen distance' = partial_avg - start) predicts the outcome BEYOND the market price.

Test (BTC hires): at ~tau s to close, reconstruct partial_avg over [close-60, close-tau] from
the sub-second snapshots; compare the residual IC of frozen_dist vs the instantaneous spot
distance, and run a quick after-cost divergence trade. If frozen_dist's residual IC clearly
beats the instantaneous one AND the trade clears cost, the TWAP mechanic carries an edge.

Usage: python scripts/research/twap_settlement_probe.py [--start 20260608 --end 20260615 --tau 25]
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys

sys.path.insert(0, "src")
from btc5m.config import load_config  # noqa: E402
from btc5m.venues.kalshi.fees import KalshiFeeModel  # noqa: E402
from btc5m.venues.kalshi.reprice_lag_hires import load_joined  # noqa: E402


def _f(x):
    try:
        return float(x) if x is not None and x == x else None
    except (TypeError, ValueError):
        return None


def spearman(xs, ys):
    n = len(xs)
    if n < 10:
        return float("nan")
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def mkt_p(row):
    ya, na = _f(row.get("yes_ask")), _f(row.get("no_ask"))
    vals = [v for v in ((1 - na) if na is not None else None, ya) if v is not None and 0 < v < 1]
    return sum(vals) / len(vals) if vals else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--start", default="20260608")
    ap.add_argument("--end", default="20260615")
    ap.add_argument("--tau", type=float, default=25.0, help="seconds-to-close decision point (<60)")
    ap.add_argument("--win", type=float, default=60.0, help="settlement averaging window (s)")
    args = ap.parse_args(argv)
    cfg = load_config(mode="paper")
    fee = KalshiFeeModel.from_config(cfg)
    jr = load_joined(cfg, start_date=args.start, end_date=args.end)
    by = {tk: r for tk, r in jr["by_ticker"].items() if str(tk).startswith(args.series)}
    labels = jr["labels"]

    samp = []   # (frozen_dist, inst_dist, mkt_p, y)
    for tk, rows in by.items():
        y = labels.get(tk, {}).get("label_yes_resolved")
        if y is None or not rows:
            continue
        rows = [r for r in rows if _f(r.get("seconds_to_close")) is not None]
        ref = next((_f(r.get("reference_start_price")) for r in rows
                    if _f(r.get("reference_start_price"))), None)
        if ref is None:
            continue
        # decision snapshot nearest tau
        dec = min(rows, key=lambda r: abs(_f(r.get("seconds_to_close")) - args.tau))
        if abs(_f(dec.get("seconds_to_close")) - args.tau) > 8:
            continue
        # partial average of spot over [close-win, close-tau] = secs_to_close in [tau, win]
        seg = [(_f(r.get("coinbase_mid")) or _f(r.get("binance_mid"))) for r in rows
               if args.tau - 1 <= _f(r.get("seconds_to_close")) <= args.win + 1
               and (_f(r.get("coinbase_mid")) or _f(r.get("binance_mid"))) is not None]
        if len(seg) < 3:
            continue
        partial_avg = statistics.fmean(seg)
        inst = _f(dec.get("coinbase_mid")) or _f(dec.get("binance_mid"))
        mp = mkt_p(dec)
        if inst is None or mp is None:
            continue
        samp.append(((partial_avg - ref) / ref, (inst - ref) / ref, mp, int(y)))

    n = len(samp)
    if n < 30:
        print(f"insufficient samples (n={n}) — need denser final-60s hires coverage")
        return 0
    frozen = [s[0] for s in samp]
    inst = [s[1] for s in samp]
    resid = [s[3] - s[2] for s in samp]
    ys = [s[3] for s in samp]
    print(f"=== TWAP settlement probe {args.series} [{args.start}..{args.end}] tau={args.tau}s n={n} ===")
    print(f"  IC vs OUTCOME:   frozen_dist={spearman(frozen, ys):+.3f}  inst_dist={spearman(inst, ys):+.3f}")
    print(f"  IC vs RESIDUAL:  frozen_dist={spearman(frozen, resid):+.3f}  inst_dist={spearman(inst, resid):+.3f}")
    print("  (TWAP edge would show frozen_dist residual IC clearly ABOVE instantaneous)")

    # quick after-cost divergence trade: when frozen-implied side disagrees w/ market lean
    nets = []
    for fd, _id, mp, y in samp:
        # frozen-implied: if partial avg already above start, lean YES; size by |fd|
        lean_yes = fd > 0
        # trade only when market is not already extreme (0.1..0.9) and frozen leans same dir hard
        if not (0.10 < mp < 0.90):
            continue
        if lean_yes and mp < 0.5:        # frozen says YES, market still <50 -> buy YES
            price = min(0.99, mp + 0.02)
            nets.append(((1 - price) if y == 1 else -price) * 100 - fee.taker_fee(price, 1) * 100)
        elif (not lean_yes) and mp > 0.5:
            price = min(0.99, (1 - mp) + 0.02)
            nets.append(((1 - price) if y == 0 else -price) * 100 - fee.taker_fee(price, 1) * 100)
    if nets:
        m = statistics.fmean(nets)
        se = statistics.pstdev(nets) / math.sqrt(len(nets)) if len(nets) > 1 else float("nan")
        print(f"  after-cost frozen-vs-market trade: n={len(nets)} net={m:+.2f}c/trade "
              f"t={m/se if se>0 else float('nan'):+.2f}")
    else:
        print("  after-cost trade: no qualifying divergences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
