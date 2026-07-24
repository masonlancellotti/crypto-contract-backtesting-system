"""Curate ONE fully-recorded 15-minute KXBTC15M window into a compact, committed
replay artifact for the dashboard (sample_data/replay_window/).

Reads locally-recorded (gitignored) normalized data for a single market_ticker:
  - Kalshi top-of-book snapshots (best bid/ask per side + resting size + depth levels)
  - Kalshi trade prints (count, price, taker side)
  - Coinbase BTC-USD spot ticks
  - the OFFICIAL settlement label (start reference + result)

and emits downsampled per-frame JSON (few hundred frames from window open through
settlement). market-implied probability is the book mid; the model probability is a
zero-drift Phi(z) physics baseline (the same lens the research used, RESEARCH_LEDGER
leg 21). Everything is recorded data or a transparent transform of it — nothing is
invented. Regenerate with:  python scripts/curate_replay_window.py
"""
from __future__ import annotations
import json, math, os, sys

TICKER = "KXBTC15M-26JUN111515-15"
DAY = "20260611"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "sample_data", "replay_window")
FRAME_MS = 2000  # downsample cadence
SETTLE_TAIL_MS = 300_000  # show through settlement (label settled_ms is close + 300s)


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _asof(series, t, key="recv_ms"):
    """Latest element with element[key] <= t (series sorted ascending by key)."""
    lo, hi, best = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][key] <= t:
            best = series[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def main():
    nd = os.path.join(BASE, "data", "normalized")
    books = [r["event"] for r in _load_jsonl(os.path.join(nd, f"kalshi_orderbook-{DAY}.jsonl"))
             if r.get("event", {}).get("market_ticker") == TICKER]
    trades = [r["event"] for r in _load_jsonl(os.path.join(nd, f"kalshi_trades-{DAY}.jsonl"))
              if r.get("event", {}).get("market_ticker") == TICKER]
    spot = [r["event"] for r in _load_jsonl(os.path.join(nd, f"underlying_coinbase-{DAY}.jsonl"))
            if r.get("event", {}).get("price")]
    labels = _load_jsonl(os.path.join(BASE, "data", "labels", f"kalshi_settlement_labels-{DAY}.jsonl"))
    label = next((L for L in labels if L.get("market_ticker") == TICKER), None)
    if not books or label is None:
        print(f"insufficient data for {TICKER}: books={len(books)} label={label is not None}")
        return 1

    books.sort(key=lambda e: e["recv_ms"])
    trades.sort(key=lambda e: e.get("created_time_ms") or e.get("recv_ms"))
    spot.sort(key=lambda e: e["recv_ms"])

    window_start = books[0]["window_start_ms"]
    close_ms = books[0]["close_ms"]
    start_ref = label.get("reference_start_price")
    result = label.get("official_result")
    settled_ms = label.get("settled_ms") or (close_ms + SETTLE_TAIL_MS)

    # constant per-sqrt-second return vol from in-window spot ticks (honest realized sigma)
    win_spot = [s for s in spot if window_start <= s["recv_ms"] <= close_ms]
    sq = []
    for a, b in zip(win_spot, win_spot[1:]):
        dt = (b["recv_ms"] - a["recv_ms"]) / 1000.0
        if dt <= 0 or a["price"] <= 0 or b["price"] <= 0:
            continue
        r = math.log(b["price"] / a["price"])
        sq.append(r * r / dt)
    sigma_s = math.sqrt(sum(sq) / len(sq)) if sq else 1e-4

    def phi(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    frames = []
    t = window_start
    prev_t = window_start
    end = min(settled_ms, close_ms + SETTLE_TAIL_MS)
    while t <= end:
        bk = _asof(books, t) or books[0]
        sp = _asof(spot, t)
        spot_px = sp["price"] if sp else None
        sec_to_close = max((close_ms - t) / 1000.0, 0.0)

        yb, ya = bk.get("yes_bid"), bk.get("yes_ask")
        nb, na = bk.get("no_bid"), bk.get("no_ask")
        # market-implied yes probability = book mid where both sides present
        if yb is not None and ya is not None:
            p_market = (yb + ya) / 2.0
        elif bk.get("executable_yes_buy_price") is not None:
            p_market = bk["executable_yes_buy_price"]
        elif nb is not None:
            p_market = 1.0 - nb
        else:
            p_market = None

        # zero-drift Phi(z) physics model probability
        if spot_px and start_ref and sigma_s > 0:
            if t >= close_ms:
                p_model = 1.0 if spot_px >= start_ref else 0.0
            else:
                z = math.log(spot_px / start_ref) / (sigma_s * math.sqrt(max(sec_to_close, 1.0)))
                p_model = phi(z)
        else:
            p_model = None

        # gate states (freshness / depth / spot-staleness) at this instant
        book_age_ms = t - bk["recv_ms"]
        spot_age_ms = (t - sp["recv_ms"]) if sp else None
        ask_sizes = [s for s in (bk.get("yes_ask_size"), bk.get("no_ask_size")) if s]
        min_ask_size = min(ask_sizes) if ask_sizes else 0.0
        gates = {
            "fresh": book_age_ms < 2000,
            "depth_ok": min_ask_size >= 50 and (bk.get("yes_depth_levels") or 0) > 0
                        and (bk.get("no_depth_levels") or 0) > 0,
            "spot_fresh": spot_age_ms is not None and spot_age_ms < 3000,
        }

        # trades since previous frame
        tw = [tr for tr in trades if prev_t < (tr.get("created_time_ms") or tr["recv_ms"]) <= t]
        yes_ct = sum(tr.get("count", 0) for tr in tw if tr.get("taker_side") == "yes")
        no_ct = sum(tr.get("count", 0) for tr in tw if tr.get("taker_side") == "no")

        frames.append({
            "t_ms": t,
            "sec_to_close": round(sec_to_close, 1),
            "phase": "settled" if t >= close_ms else "live",
            "book": {
                "yes_bid": yb, "yes_ask": ya, "no_bid": nb, "no_ask": na,
                "yes_bid_size": bk.get("yes_bid_size"), "yes_ask_size": bk.get("yes_ask_size"),
                "no_bid_size": bk.get("no_bid_size"), "no_ask_size": bk.get("no_ask_size"),
                "yes_depth_levels": bk.get("yes_depth_levels"), "no_depth_levels": bk.get("no_depth_levels"),
            },
            "spot": round(spot_px, 2) if spot_px else None,
            "dist_to_start": round(spot_px - start_ref, 2) if (spot_px and start_ref) else None,
            "p_market": round(p_market, 4) if p_market is not None else None,
            "p_model": round(p_model, 4) if p_model is not None else None,
            "gates": gates,
            "trades": {"n": len(tw), "yes_count": round(yes_ct, 1), "no_count": round(no_ct, 1)},
        })
        prev_t = t
        t += FRAME_MS

    os.makedirs(OUT_DIR, exist_ok=True)
    meta = {
        "market_ticker": TICKER,
        "series": "KXBTC15M",
        "day": DAY,
        "window_start_ms": window_start,
        "close_ms": close_ms,
        "settled_ms": settled_ms,
        "reference_start_price": start_ref,
        "official_result": result,
        "official_winning_side": label.get("official_winning_side"),
        "settlement_reference_source": label.get("settlement_reference_source"),
        "rules_excerpt": label.get("rules_excerpt"),
        "sigma_per_sqrt_s": sigma_s,
        "frame_ms": FRAME_MS,
        "n_frames": len(frames),
        "n_book_snapshots_recorded": len(books),
        "n_trade_prints_recorded": len(trades),
        "model_note": "p_model is a zero-drift Phi(z) physics baseline from recorded Coinbase spot vs the OFFICIAL start reference (RESEARCH_LEDGER leg 21); p_market is the recorded Kalshi book mid. Recorded data only.",
    }
    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    with open(os.path.join(OUT_DIR, "frames.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": {k: meta[k] for k in ("market_ticker", "official_result",
                   "reference_start_price", "close_ms", "n_frames")}, "frames": frames}, fh)

    # summary for curation review
    pm = [f["p_market"] for f in frames if f["p_market"] is not None and f["phase"] == "live"]
    print(f"window={TICKER} result={result} start_ref={start_ref}")
    print(f"frames={len(frames)} books={len(books)} trades={len(trades)} spot_ticks={len(win_spot)}")
    print(f"p_market live range: {min(pm):.2f}..{max(pm):.2f}  first={pm[0]:.2f} last={pm[-1]:.2f}")
    print(f"sigma_per_sqrt_s={sigma_s:.3e}")
    sz = os.path.getsize(os.path.join(OUT_DIR, "frames.json"))
    print(f"frames.json size={sz/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
