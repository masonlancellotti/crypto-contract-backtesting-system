"""Autopsy of the maker mine's near-passing candidate (DSR 0.998, PBO 0.00, plateau spike).

Rule: distance_to_line_vol_normalized top-quartile -> rest a YES bid (prints-through fill).
Decisive question the engine deferred: does +4.20c/fill, 100%-win SURVIVE on the SEALED HOLDOUT,
or collapse (fragile/overfit, consistent with #15's forward failure)? Also dissect the economics
(entry price, y-rate) to confirm it is the known deep-favorite spread-capture, not a leak.
READ-ONLY."""
from __future__ import annotations

import sys
import numpy as np

sys.path.insert(0, "src")
from btc5m.discovery import engine, holdout, maker_mine, panel  # noqa: E402
from btc5m.venues.kalshi.backfill_trades import load_trade_prints  # noqa: E402
from btc5m.venues.kalshi.fees import KalshiFeeModel  # noqa: E402

FEATURE, TAIL, Q, SIDE = "distance_to_line_vol_normalized", "hi", 0.75, "YES"


def dissect(name, pn, nets):
    fv = np.array([o.feats.get(FEATURE) if o.feats.get(FEATURE) is not None else np.nan for o in pn])
    valid = ~np.isnan(fv)
    thr = float(np.quantile(fv[valid], Q))
    quoted = valid & (fv >= thr)
    rows = []
    for o, q in zip(pn, quoted):
        if not q:
            continue
        rec = nets.get(o.ticker, {}).get(SIDE, (0.0, False))
        if rec[1]:                                   # filled
            rows.append((rec[0], o.yes_bid, o.y))
    if not rows:
        print(f"  {name}: no fills"); return
    nets_c = [r[0] for r in rows]
    bids = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    m = np.mean(nets_c)
    se = np.std(nets_c, ddof=1) / np.sqrt(len(nets_c)) if len(nets_c) > 1 else float("nan")
    print(f"  {name:8s} fills={len(rows):3d}  per_fill={m:+.2f}c  t={m/se if se>0 else float('nan'):+.2f}  "
          f"win(y=1)={np.mean(ys):.0%}  mean_bid={np.mean(bids):.3f}  thr={thr:.3f}")


def main():
    pn_all, cfg = engine._build_panel("KXBTC15M", 180.0, 0.0)
    prints = load_trade_prints(cfg, series="KXBTC15M")
    fee = KalshiFeeModel(rate=0.0, status="ASSUMED_ZERO_MAKER_FEE")
    nets = maker_mine.compute_maker_nets(pn_all, prints, fee, queue="through")
    pn = [o for o in pn_all if o.ticker in nets]
    windows = [{"ticker": o.ticker, "close_ms": o.close_ms, "label": o.y} for o in pn]
    vault = holdout.HoldoutVault.build(windows)
    search_pn = panel.filter_panel(pn, set(vault.search_keys))
    hold_pn = panel.filter_panel(pn, set(vault.holdout_keys))
    print(f"=== AUTOPSY: {FEATURE} {TAIL} q{Q} -> rest {SIDE} bid (prints-through) ===")
    print(f"windows w/ tape: {len(pn)}  search={len(search_pn)} holdout={len(hold_pn)}")
    dissect("SEARCH", search_pn, nets)
    dissect("HOLDOUT", hold_pn, nets)
    # also: same cell as a TAKER (buy at ask) for contrast, and a realistic queue (front) maker
    nets_front = maker_mine.compute_maker_nets(pn_all, prints, fee, queue="front")
    print("  -- same cell, FRONT-of-queue fill (still optimistic but less so) --")
    dissect("SEARCH", search_pn, nets_front)
    dissect("HOLDOUT", hold_pn, nets_front)


if __name__ == "__main__":
    main()
