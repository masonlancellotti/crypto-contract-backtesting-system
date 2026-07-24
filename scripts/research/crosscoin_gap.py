"""Quantify the cross-coin signal's tradability GAP, per alt. READ-ONLY.

The cross-coin lead-lag is the one REAL signal (BTC's implied prob predicts the alt residual,
IC +0.28) but the gauntlet rejected it on cost. This turns "rejected" into a number: for each
alt, what is the after-cost EV of the simple BTC-lead rule, and how much would the spread have
to tighten to flip it positive? That tells us exactly which coin and how much of a liquidity
change makes our one real signal tradeable."""
from __future__ import annotations

import sys
import statistics
import math

sys.path.insert(0, "src")
from btc5m.discovery import crosscoin, engine  # noqa: E402
from btc5m.venues.kalshi.fees import KalshiFeeModel  # noqa: E402

LEAD = 180.0


def main():
    btc_clock = crosscoin.build_btc_clock(lead_seconds=LEAD)
    print("=== cross-coin tradability gap (rule: BTC implied-prob -> follow on the alt) ===")
    print(f"{'alt':10s} {'n':>4s} {'btc_p IC_resid':>14s} {'taker_net':>10s} {'t':>6s} "
          f"{'spread':>7s} {'breakeven_spread':>16s}")
    for s in crosscoin.ALTS:
        pn, cfg = engine._build_panel(s, LEAD, 3.0)
        crosscoin.attach_concurrent(pn, btc_clock)
        fee = KalshiFeeModel.from_config(cfg)
        # rule: when BTC implied prob (btc_mkt_p) is high -> alt likely up -> buy alt YES;
        # when low -> buy alt NO. Trade only the decisive tails (BTC p in <0.35 or >0.65).
        nets, spreads = [], []
        ics_x, ics_y = [], []
        for o in pn:
            bp = o.feats.get("btc_mkt_p")
            if bp is None:
                continue
            ics_x.append(bp); ics_y.append(o.y - o.mkt_p)
            sp = (o.exec_yes - (1 - o.exec_no))   # yes_ask - yes_bid proxy = spread
            spreads.append(sp)
            if bp >= 0.65:
                price = o.exec_yes
                nets.append((100 * (o.y - price)) - fee.taker_fee(price, 1) * 100)
            elif bp <= 0.35:
                price = o.exec_no
                nets.append((100 * ((1 - o.y) - price)) - fee.taker_fee(price, 1) * 100)
        if len(nets) < 10:
            print(f"{s:10s} {len(nets):>4d}  (too few decisive BTC-lead signals)")
            continue
        m = statistics.fmean(nets)
        se = statistics.pstdev(nets) / math.sqrt(len(nets)) if len(nets) > 1 else float("nan")
        # spearman IC of btc_p vs alt residual
        def sp_ic(xs, ys):
            n = len(xs)
            rx = _rank(xs); ry = _rank(ys)
            mx, my = statistics.fmean(rx), statistics.fmean(ry)
            num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
            den = math.sqrt(sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))
            return num/den if den > 0 else float('nan')
        ic = sp_ic(ics_x, ics_y)
        med_sp = statistics.median(spreads) * 100
        # how much tighter must the spread be to break even? you pay ~half the spread on entry;
        # gain needed = -m cents; tightening spread by d cents saves ~d/2 per trade.
        be = max(0.0, -m) * 2.0   # cents of spread tightening to reach 0 EV (rough)
        print(f"{s:10s} {len(nets):>4d} {ic:>+14.3f} {m:>+9.2f}c {m/se if se>0 else float('nan'):>+6.2f} "
              f"{med_sp:>6.1f}c {('+'+format(be,'.1f')+'c tighter' if m<0 else 'ALREADY +EV'):>16s}")
    print("\n(net is after real taker fee at the lagged executable price; breakeven_spread is the rough")
    print(" spread tightening that would flip the rule to 0 EV — the liquidity threshold for this signal.)")


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0]*len(v); i = 0
    while i < len(v):
        j = i
        while j+1 < len(v) and v[order[j+1]] == v[order[i]]:
            j += 1
        for k in range(i, j+1):
            r[order[k]] = (i+j)/2+1
        i = j+1
    return r


if __name__ == "__main__":
    main()
