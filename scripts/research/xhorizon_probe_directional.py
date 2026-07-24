"""Focused cross-horizon probe (⑥) — directional BTC siblings only. READ-ONLY.

Gentle (sleeps + 429 backoff) probe of the BTC directional series that could form
a same-underlying / same-settlement relative-value set across horizons:
    KXBTC15M  fifteen_min  Bitcoin price up down   (baseline, settles vs open)
    KXBTCD    hourly       Bitcoin price Above/below
    BTCD      daily        Bitcoin price Above/below
    KXBTC     hourly       Bitcoin range            (range buckets — structure check)
For each: series title, a few OPEN markets with subtitle + strike fields, and a
real top-of-book spread on the nearest-dated market.

Usage: python scripts/research/xhorizon_probe_directional.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "src")
from btc5m.config import load_config  # noqa: E402

UA = "btc5m-research/1.0"
SERIES = ["KXBTC15M", "KXBTCD", "BTCD", "KXBTC"]


def get(base: str, path: str, params: dict | None = None, timeout: float = 20.0, tries: int = 5):
    url = f"{base}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                wait = 2.0 * (i + 1)
                time.sleep(wait)
                continue
            raise
    raise last


def topbook(base: str, ticker: str) -> str:
    try:
        data = get(base, f"/markets/{ticker}/orderbook")
        ob = data.get("orderbook") or {}
        yes = ob.get("yes") or []
        no = ob.get("no") or []
        yes_bid = max((lvl[0] for lvl in yes), default=None)
        no_bid = max((lvl[0] for lvl in no), default=None)
        yes_ask = (100 - no_bid) if no_bid is not None else None
        yb_sz = sum(lvl[1] for lvl in yes) if yes else 0
        nb_sz = sum(lvl[1] for lvl in no) if no else 0
        if yes_bid is not None and yes_ask is not None:
            return (f"YES {yes_bid}c x {yes_ask}c  spread={yes_ask - yes_bid}c  "
                    f"depth(yes_bids={yb_sz}, no_bids={nb_sz})")
        return f"one-sided: yes_bid={yes_bid} no_bid={no_bid} (yb_sz={yb_sz} nb_sz={nb_sz})"
    except Exception as e:  # noqa: BLE001
        return f"ob_err {e!r}"


def main() -> int:
    cfg = load_config(mode="paper")
    base = cfg.kalshi.api_base.rstrip("/")
    now_s = int(time.time())
    print(f"=== directional cross-horizon probe | base={base} | now={now_s} ===\n")

    for s in SERIES:
        print(f"### {s}")
        try:
            sd = get(base, f"/series/{s}").get("series", {})
            print(f"  title='{sd.get('title')}' freq={sd.get('frequency')} "
                  f"category={sd.get('category')} settlement_sources="
                  f"{[x.get('name') for x in (sd.get('settlement_sources') or [])]}")
        except Exception as e:  # noqa: BLE001
            print(f"  series err {e!r}")
        time.sleep(1.0)
        # open markets closing soonest
        try:
            data = get(base, "/markets", {"series_ticker": s, "status": "open",
                                          "limit": 100})
            mkts = data.get("markets") or []
        except Exception as e:  # noqa: BLE001
            print(f"  markets err {e!r}\n")
            continue
        mkts = [m for m in mkts if (m.get("close_ts") or 0) >= now_s]
        mkts.sort(key=lambda m: m.get("close_ts") or 0)
        print(f"  open(future-close)={len(mkts)}")
        for m in mkts[:4]:
            close_in = (m.get("close_ts") or 0) - now_s
            print(f"   - {m.get('ticker')}  closes_in={close_in}s "
                  f"sub='{m.get('yes_sub_title') or m.get('subtitle')}' "
                  f"strike_type={m.get('strike_type')} "
                  f"floor={m.get('floor_strike')} cap={m.get('cap_strike')} "
                  f"vol={m.get('volume')} oi={m.get('open_interest')}")
        if mkts:
            time.sleep(1.0)
            print(f"   topbook[{mkts[0].get('ticker')}]: {topbook(base, mkts[0]['ticker'])}")
        print()
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
