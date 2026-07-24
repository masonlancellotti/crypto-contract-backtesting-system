"""Round-trip market-making simulator + cancel-latency sweep — READ-ONLY, no orders.

Every prior maker study here was BUY-AND-HOLD-to-settlement. This is the missing one: a
spread-capturing MM that quotes BOTH sides of the YES contract (bid B, ask A=1-no_bid), buys
when a taker SELLS into its bid, sells when a taker BUYS its ask, and settles any residual
inventory at close. It requotes to the live book only every `cancel_latency_ms` (staleness =
adverse selection). Sweeping cancel_latency answers the speed question directly: does maker EV
flip positive as cancel/requote speed increases, or does adverse selection win at every speed?

Fills are OPTIMISTIC (no queue: every taker print crossing the quote fills us) -> the P&L is an
UPPER BOUND on a real MM. If even the upper bound is negative, market-making is dead here;
if positive, queue position is the next thing to model. BTC only (prints). maker fee = 0.

Usage: python scripts/research/market_making_sim.py
"""
from __future__ import annotations

import sys
import statistics
import math

sys.path.insert(0, "src")
from btc5m.config import load_config  # noqa: E402
from btc5m.venues.kalshi.maker_entry import load_window_snapshots, _official_label_map  # noqa: E402
from btc5m.venues.kalshi.backfill_trades import load_trade_prints  # noqa: E402

LATENCIES = [250, 1000, 4000, 10**9]   # ms; 1e9 = never requote (static, ~ledger #14)
MAX_INV = 5
MAKER_FEE = 0.0


SKEW = 0.012   # quote shift per unit inventory (inventory-aware, Avellaneda-Stoikov-lite)


def simulate_window(snaps, prints, y, *, cancel_latency_ms):
    inv = 0
    cash = 0.0
    n_buy = n_sell = 0
    book_bid = book_ask = None
    last_requote = None
    cur = None
    si = 0
    bid_live = ask_live = False     # 1 resting contract per side; refills only on requote (queue proxy)
    my_bid = my_ask = None
    for p in prints:
        t = p.get("created_time_ms")
        if t is None:
            continue
        while si < len(snaps) and snaps[si]["recv_ms"] <= t:
            cur = snaps[si]
            si += 1
        if cur is None:
            continue
        if book_bid is None or (t - last_requote) >= cancel_latency_ms:
            book_bid = cur["yes_bid"]
            book_ask = 1.0 - cur["no_bid"]
            # inventory skew: long -> shift both quotes DOWN (discourage buys, encourage sells)
            my_bid = book_bid - inv * SKEW
            my_ask = book_ask - inv * SKEW
            bid_live = ask_live = True
            last_requote = t
        if my_bid is None or my_ask <= my_bid:
            continue
        side = p.get("taker_side")
        px = p.get("yes_price")
        if px is None:
            continue
        if side == "no" and bid_live and px <= my_bid + 1e-9 and inv < MAX_INV and 0 < my_bid < 1:
            inv += 1
            cash -= my_bid
            n_buy += 1
            bid_live = False                 # our 1 contract filled; wait for next requote
        elif side == "yes" and ask_live and px >= my_ask - 1e-9 and inv > -MAX_INV and 0 < my_ask < 1:
            inv -= 1
            cash += my_ask
            n_sell += 1
            ask_live = False
    cash += inv * y                                  # settle residual inventory at outcome
    pnl_c = (cash - MAKER_FEE * (n_buy + n_sell)) * 100.0
    return {"pnl_c": pnl_c, "fills": n_buy + n_sell, "n_buy": n_buy, "n_sell": n_sell,
            "round_trips": min(n_buy, n_sell), "end_inv": inv}


def main():
    cfg = load_config(mode="paper")
    snaps_by = load_window_snapshots(cfg, series="KXBTC15M")
    labels = _official_label_map(cfg)
    prints_by = load_trade_prints(cfg, series="KXBTC15M")
    wins = [tk for tk in snaps_by if tk in labels and prints_by.get(tk)]
    print(f"=== round-trip MM sim (BTC) — {len(wins)} windows w/ book+prints+label ===")
    print("optimistic fills (no queue) -> P&L is an UPPER BOUND. maker fee=0.\n")
    print(f"{'cancel_latency':>14s} {'mean_pnl/win':>13s} {'t':>6s} {'total':>9s} "
          f"{'avg_fills':>9s} {'avg_RT':>7s} {'naked_end%':>10s}")
    for lat in LATENCIES:
        pnls, fills, rts, naked = [], [], [], 0
        for tk in wins:
            r = simulate_window(snaps_by[tk], prints_by[tk], labels[tk], cancel_latency_ms=lat)
            if r["fills"] == 0:
                continue
            pnls.append(r["pnl_c"])
            fills.append(r["fills"])
            rts.append(r["round_trips"])
            if r["end_inv"] != 0:
                naked += 1
        if not pnls:
            print(f"{lat:>14d}  (no fills)")
            continue
        m = statistics.fmean(pnls)
        se = statistics.pstdev(pnls) / math.sqrt(len(pnls)) if len(pnls) > 1 else float("nan")
        tag = "static#14" if lat >= 10**8 else f"{lat}ms"
        print(f"{tag:>14s} {m:>+12.2f}c {m/se if se>0 else float('nan'):>+6.2f} "
              f"{sum(pnls):>+8.0f}c {statistics.fmean(fills):>9.1f} {statistics.fmean(rts):>7.1f} "
              f"{naked/len(pnls):>9.0%}")
    print("\n(if mean_pnl rises toward 0+/positive as latency falls -> speed has value for a MAKER;")
    print(" if negative at every latency -> adverse selection beats spread capture even at 250ms.)")


if __name__ == "__main__":
    main()
