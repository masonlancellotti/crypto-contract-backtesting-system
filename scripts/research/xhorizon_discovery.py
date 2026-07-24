"""Cross-horizon discovery scan (⑥) — READ-ONLY.

Probe the public Kalshi API for BTC (and crypto) series across horizons beyond
KXBTC15M, and report for each: title/settlement subtitle, # open markets, and a
sample top-of-book spread. Gates whether a cross-horizon relative-value study is
viable (same venue, same CF Benchmarks settlement, different time horizon).

Usage: python scripts/research/xhorizon_discovery.py
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
from btc5m.venues.kalshi.client import KalshiClient  # noqa: E402

UA = "btc5m-research/1.0"


def get(base: str, path: str, params: dict | None = None, timeout: float = 20.0):
    url = f"{base}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_series(base: str, category: str) -> list[dict]:
    """GET /series?category=Crypto (public). Returns [] if unsupported."""
    try:
        data = get(base, "/series/", {"category": category})
        return data.get("series") or []
    except urllib.error.HTTPError as e:
        print(f"  /series?category={category} -> HTTP {e.code}")
        return []
    except Exception as e:  # noqa: BLE001
        print(f"  /series list failed: {e!r}")
        return []


def best_spread(client: KalshiClient, ticker: str) -> str:
    try:
        ob = client.get_orderbook(ticker).get("orderbook") or {}
        # Kalshi orderbook: yes/no are [[price_cents, size], ...] ascending bids
        yes = ob.get("yes") or []
        no = ob.get("no") or []
        # best YES bid = max yes price; best YES ask = 100 - best NO bid
        yes_bid = max((lvl[0] for lvl in yes), default=None)
        no_bid = max((lvl[0] for lvl in no), default=None)
        yes_ask = (100 - no_bid) if no_bid is not None else None
        if yes_bid is not None and yes_ask is not None:
            return f"YES {yes_bid}c/{yes_ask}c (spread {yes_ask - yes_bid}c)"
        return f"yes_bid={yes_bid} no_bid={no_bid} (one-sided/empty)"
    except Exception as e:  # noqa: BLE001
        return f"ob_err {e!r}"


def main() -> int:
    cfg = load_config(mode="paper")
    base = cfg.kalshi.api_base.rstrip("/")
    client = KalshiClient(cfg)
    print(f"=== xhorizon discovery | base={base} ===")

    # 1) Enumerate crypto series
    series = list_series(base, "Crypto")
    print(f"\n[crypto series found: {len(series)}]")
    btc_like = []
    for s in series:
        tkr = s.get("ticker") or s.get("series_ticker") or "?"
        title = s.get("title") or s.get("name") or ""
        freq = s.get("frequency") or s.get("settlement_period") or ""
        print(f"  {tkr:14s} freq={freq!s:10s} {title}")
        if any(k in (tkr + title).upper() for k in ("BTC", "BITCOIN")):
            btc_like.append(tkr)

    # 2) Always also probe known/guessed BTC horizon tickers
    candidates = sorted(set(btc_like) | {
        "KXBTC15M", "KXBTCD", "KXBTC", "KXBTCH", "KXBTC1H", "KXBTCHOURLY",
        "KXBTCDAILY", "KXBTCUPDOWN", "KXBTCRANGE",
    })
    print(f"\n[probing {len(candidates)} candidate BTC series tickers]")
    viable = []
    for tkr in candidates:
        try:
            s = client.get_series(tkr)
            sd = s.get("series") or s
            title = sd.get("title") or sd.get("name") or ""
        except urllib.error.HTTPError as e:
            print(f"  {tkr:14s} get_series HTTP {e.code} (absent)")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"  {tkr:14s} get_series err {e!r}")
            continue
        # list open markets
        try:
            mkts = client.list_markets(series_ticker=tkr, status="open", max_pages=3)
        except Exception as e:  # noqa: BLE001
            print(f"  {tkr:14s} EXISTS '{title}' but list_markets err {e!r}")
            continue
        n_open = len(mkts)
        sample = mkts[0] if mkts else None
        sub = (sample or {}).get("subtitle") or (sample or {}).get("yes_sub_title") or ""
        sm_tkr = (sample or {}).get("ticker")
        vol = sum((m.get("volume") or 0) for m in mkts)
        spread = best_spread(client, sm_tkr) if sm_tkr else "n/a"
        print(f"  {tkr:14s} EXISTS '{title}' open={n_open} totVol={vol} "
              f"sub='{sub}' sample={sm_tkr} {spread}")
        if n_open > 0:
            viable.append((tkr, n_open, vol))
        time.sleep(0.15)

    print("\n=== VIABLE (open markets > 0) ===")
    for tkr, n, vol in sorted(viable, key=lambda x: -x[2]):
        print(f"  {tkr:14s} open={n} totVol={vol}")
    if not viable:
        print("  (none with open markets — cross-horizon fork is BLOCKED at the API level)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
