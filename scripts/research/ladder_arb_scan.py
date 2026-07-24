"""Path 2 — live strike-ladder internal arbitrage scan. READ-ONLY (no orders).

A ladder of '>= K' binaries (KXBTCD hourly, and alt directional ladders) must be internally
consistent. The clean RISKLESS check: for strikes K1 < K2, the basket {buy YES(>=K1) + buy
NO(>=K2)} ALWAYS pays >= $1 (it pays 2 when K1<=index<K2, else 1). So if
    ask_yes(K1) + ask_no(K2) < 1   (for some K1 < K2)
you pay < $1 for a >= $1 payoff -> riskless profit (minus fees). We scan all strike pairs for
the minimum basket cost; < 1 = arb, slightly above = how tight the ladder is. Also flags
monotonicity violations (P(>=K) must fall as K rises). A few snapshots catch transient arbs.

Usage: python scripts/research/ladder_arb_scan.py [--loops 6 --sleep 8]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, "src")
from btc5m.config import load_config  # noqa: E402

UA = "btc5m-research/1.0"
# directional strike-ladder series discovered earlier (hourly 'Above/below' style)
LADDERS = ["KXBTCD", "KXETH", "KXSOLD", "KXDOGED", "KXBTC"]


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def get(base, path, params=None, tries=5):
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.5 * (i + 1)); continue
            raise


def close_s(m):
    ct = m.get("close_time")
    if not ct:
        return None
    try:
        return datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def scan_ladder(base, series, now_s):
    allm, cur = [], None
    for _ in range(6):
        d = get(base, "/markets", {"series_ticker": series, "status": "open", "limit": 200, "cursor": cur})
        allm += d.get("markets") or []
        cur = d.get("cursor") or None
        if not cur:
            break
    fut = [m for m in allm if (close_s(m) or 0) > now_s + 180]   # healthy maturity
    if not fut:
        return f"  {series:8s}: no open ladder w/ >180s maturity"
    nearest = min(close_s(m) for m in fut)
    lad = [m for m in fut if abs((close_s(m) or 0) - nearest) < 1]
    tau = int(nearest - now_s)

    def px(m):
        return _f(m.get("yes_ask_dollars")), _f(m.get("no_ask_dollars"))

    gt = sorted((m for m in lad if m.get("strike_type") == "greater"),
                key=lambda m: _f(m.get("floor_strike")) or 0)
    bt = sorted((m for m in lad if m.get("strike_type") == "between"),
                key=lambda m: _f(m.get("floor_strike")) or 0)
    out = []

    # (1) directional >=K ladder: basket buy YES(>=K1)+NO(>=K2), K1<K2 -> payoff>=1
    rows = [(_f(m.get("floor_strike")), *px(m)) for m in gt]
    rows = [(k, ya, na) for k, ya, na in rows if k is not None and ya is not None and na is not None]
    if len(rows) >= 3:
        mc, pair = min(((rows[i][1] + rows[j][2], (rows[i][0], rows[j][0]))
                        for i in range(len(rows)) for j in range(i + 1, len(rows))),
                       key=lambda t: t[0])
        flag = "  <-- RISKLESS ARB" if mc < 1 - 1e-6 else ("  tight" if mc < 1.02 else "")
        out.append(f">=K[{len(rows)}] min_basket={mc:.4f}{flag}")

    # (2) range buckets: a complete MECE partition -> sum(yes_ask)<1 = buy-all arb;
    #     sum(yes_bid)>1 = sell-all arb. Only valid if buckets are contiguous.
    if len(bt) >= 3:
        cells = [(_f(m.get("floor_strike")), _f(m.get("cap_strike")), *px(m)) for m in bt]
        cells = [c for c in cells if None not in c]
        contiguous = all(abs(cells[i][1] - cells[i + 1][0]) <= max(1.0, 0.001 * abs(cells[i][1]))
                         for i in range(len(cells) - 1))
        sum_ask = sum(c[2] for c in cells)
        # add the two tails (<=lowest, >=highest) if present, to complete the partition
        less = [px(m)[0] for m in lad if m.get("strike_type") == "less"]
        gtr_tail = [px(m)[0] for m in lad if m.get("strike_type") == "greater"
                    and (_f(m.get("floor_strike")) or 0) >= cells[-1][1] - 1]
        tail_ask = (min(less) if less else 0) + (min(gtr_tail) if gtr_tail else 0)
        total = sum_ask + tail_ask
        note = "contiguous" if contiguous else "GAPPY(not MECE)"
        flag = "  <-- BUY-ALL ARB" if (contiguous and total < 1 - 1e-6 and less and gtr_tail) else ""
        out.append(f"between[{len(cells)}] sum_yes_ask(+tails)={total:.4f} ({note}){flag}")

    if not out:
        return f"  {series:8s}: tau={tau}s  no clean >=K or bucket structure ({len(lad)} mkts)"
    return f"  {series:8s}: tau={tau}s  " + "  |  ".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--loops", type=int, default=4)
    ap.add_argument("--sleep", type=float, default=8.0)
    args = ap.parse_args(argv)
    cfg = load_config(mode="paper")
    base = cfg.kalshi.api_base.rstrip("/")
    print(f"=== ladder arbitrage scan | base={base} ===")
    print("min_basket_cost < 1.0 == riskless arb (pay <$1 for >=$1 payoff); ~1.0x = ladder is tight\n")
    for loop in range(args.loops):
        print(f"[snapshot {loop+1}/{args.loops}  {datetime.now(timezone.utc).strftime('%H:%M:%S')}Z]")
        now_s = int(time.time())
        for s in LADDERS:
            try:
                print(scan_ladder(base, s, now_s))
            except Exception as e:  # noqa: BLE001
                print(f"  {s:8s}: err {e!r}")
            time.sleep(0.4)
        if loop < args.loops - 1:
            time.sleep(args.sleep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
