"""Expand the committed zero-key sample to multiple coins and days (WS4).

Adds downsampled ETH/SOL/DOGE 15-minute feature rows + OFFICIAL labels alongside
the existing BTC day, so the dashboard's calibration/backtest curves pool several
thousand real market-implied-vs-outcome pairs across coins and days. BTC is left
untouched, so the committed BTC demo chain and its expected reports still reproduce
exactly.

Downsamples to a few evenly-spaced feature rows per 15-minute window (matching the
BTC sample's density) to keep the committed footprint small. Regenerate with:
  python scripts/curate_multicoin_sample.py
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COINS = ["KXETH15M", "KXSOL15M", "KXDOGE15M"]
DAYS = ["20260610", "20260611", "20260612", "20260614"]
ROWS_PER_WINDOW = 3
MAX_WINDOWS_PER_DAY = 90


def _load(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def curate_coin_day(coin, day):
    feats = _load(f"{BASE}/data/series/{coin}/features/kalshi_feature_rows-{day}.jsonl")
    labels = _load(f"{BASE}/data/series/{coin}/labels/kalshi_settlement_labels-{day}.jsonl")
    lab_by_tkr = {L["market_ticker"]: L for L in labels
                  if L.get("market_ticker") and L.get("label_yes_resolved") is not None}
    # group feature rows by window, keep only labeled windows with a usable book
    by_window: dict[str, list] = {}
    for r in feats:
        mt = r.get("market_ticker")
        if mt in lab_by_tkr and r.get("yes_bid") is not None and r.get("yes_ask") is not None:
            by_window.setdefault(mt, []).append(r)
    windows = sorted(by_window)[:MAX_WINDOWS_PER_DAY]
    picked_rows, picked_tkrs = [], []
    for mt in windows:
        rows = sorted(by_window[mt], key=lambda r: r.get("as_of_ms") or 0)
        if not rows:
            continue
        # evenly spaced sample across the window's life
        n = len(rows)
        idxs = sorted(set(int(i * (n - 1) / max(ROWS_PER_WINDOW - 1, 1)) for i in range(ROWS_PER_WINDOW)))
        for i in idxs:
            picked_rows.append(rows[i])
        picked_tkrs.append(mt)
    return picked_rows, [lab_by_tkr[t] for t in picked_tkrs]


def main():
    fdir = f"{BASE}/sample_data/features"
    ldir = f"{BASE}/sample_data/labels"
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(ldir, exist_ok=True)
    total_rows = total_windows = 0
    summary = []
    for coin in COINS:
        crows = cwins = 0
        for day in DAYS:
            rows, labs = curate_coin_day(coin, day)
            if not rows:
                continue
            with open(f"{fdir}/kalshi_feature_rows_{coin}-{day}.jsonl", "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
            with open(f"{ldir}/kalshi_settlement_labels_{coin}-{day}.jsonl", "w", encoding="utf-8") as fh:
                for L in labs:
                    fh.write(json.dumps(L) + "\n")
            crows += len(rows); cwins += len(labs)
        summary.append((coin, cwins, crows))
        total_rows += crows; total_windows += cwins
    print("coin        windows  rows")
    for coin, w, r in summary:
        print(f"{coin:<11} {w:>7}  {r:>5}")
    print(f"{'TOTAL':<11} {total_windows:>7}  {total_rows:>5}")
    # size
    def dirsize(d):
        return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
    total = 0
    for root, _, files in os.walk(f"{BASE}/sample_data"):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print(f"sample_data total: {total/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
