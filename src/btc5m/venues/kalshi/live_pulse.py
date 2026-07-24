"""btc5m live-pulse — keyless public read of currently-listed 15-minute crypto series.

Read-only. No API keys, no orders (this module cannot submit — it only calls public
market-data GETs). Degrades gracefully: if no live 15-minute crypto series is listed,
or the network is unreachable, it says so and (unless --fixture forced a hermetic run)
falls back to the committed recorded fixture, clearly labeled NOT LIVE.

The fixture path (`--fixture`) is also the hermetic-test path: it never touches the
network.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CRYPTO_15M_SERIES = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"]
_REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = _REPO_ROOT / "sample_data" / "live_pulse_fixture.json"


def _to_dollars(v):
    """Kalshi REST returns cents (0-100); recorded data is dollars (0-1). Normalize."""
    if v is None:
        return None
    v = float(v)
    return v / 100.0 if v > 1.5 else v


def _implied_yes(row: dict):
    yb, ya = row.get("yes_bid"), row.get("yes_ask")
    if yb is not None and ya is not None:
        return (yb + ya) / 2.0
    if ya is not None:
        return ya
    nb = row.get("no_bid")
    return (1.0 - nb) if nb is not None else None


def _fmt_ttc(ms):
    if ms is None:
        return "  ?  "
    secs = max(0, int(ms / 1000))
    return f"{secs // 60:>2}:{secs % 60:02d}"


def _render(rows: list[dict], *, live: bool, now_ms: int) -> None:
    banner = "LIVE" if live else "FIXTURE (recorded - NOT live)"
    print()
    print(f"  Kalshi 15-minute crypto pulse  |  {banner}  |  read-only, keyless")
    print("  " + "-" * 74)
    print(f"  {'series':<11} {'implied':>8} {'yes bid/ask':>13} {'no bid/ask':>13} {'to close':>9} {'ask sz':>8}")
    print("  " + "-" * 74)
    for r in rows:
        imp = _implied_yes(r)
        ttc = _fmt_ttc((r.get("close_ms") or 0) - now_ms) if r.get("close_ms") else "  ?  "
        yb, ya = r.get("yes_bid"), r.get("yes_ask")
        nb, na = r.get("no_bid"), r.get("no_ask")
        ask_sz = r.get("yes_ask_size")
        imp_s = f"{imp*100:>6.1f}%" if imp is not None else "   ?  "
        ba = f"{int((yb or 0)*100):>3}/{int((ya or 0)*100):<3}" if yb is not None else "   -   "
        na_s = f"{int((nb or 0)*100):>3}/{int((na or 0)*100):<3}" if nb is not None else "   -   "
        print(f"  {r.get('series_ticker',''):<11} {imp_s:>8} {ba:>13} {na_s:>13} {ttc:>9} {int(ask_sz) if ask_sz else '-':>8}")
    print("  " + "-" * 74)
    print(f"  {len(rows)} series | implied = book mid | prices in cents | no orders (read-only by design)")
    print()


def _load_fixture() -> list[dict]:
    try:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return data.get("series", [])
    except Exception:
        return []


def _fetch_live(cfg) -> list[dict]:
    """Best-effort keyless pull of the current in-window market per crypto series."""
    from .client import KalshiClient

    client = KalshiClient(cfg)
    now_s = int(time.time())
    rows: list[dict] = []
    for st in CRYPTO_15M_SERIES:
        try:
            markets = client.list_markets(series_ticker=st, status="open",
                                          min_close_ts=now_s, limit=100, max_pages=2)
        except Exception:  # noqa: BLE001
            continue
        if not markets:
            continue
        # the current window = smallest close in the future
        markets.sort(key=lambda m: m.get("close_ts") or m.get("close_time") or 0)
        m = markets[0]
        row = {
            "series_ticker": st,
            "market_ticker": m.get("ticker"),
            "yes_bid": _to_dollars(m.get("yes_bid")),
            "yes_ask": _to_dollars(m.get("yes_ask")),
            "no_bid": _to_dollars(m.get("no_bid")),
            "no_ask": _to_dollars(m.get("no_ask")),
            "close_ms": (m.get("close_ts") or 0) * 1000 if m.get("close_ts") else None,
        }
        try:
            ob = client.get_orderbook(m.get("ticker"))
            fp = ob.get("orderbook") or ob.get("orderbook_fp") or {}
            yes = fp.get("yes") or fp.get("yes_dollars") or []
            if yes:
                row["yes_ask_size"] = yes[-1][1] if yes[-1] else None
        except Exception:  # noqa: BLE001
            pass
        rows.append(row)
    return rows


def run_live_pulse(cfg, args) -> int:
    now_ms = int(time.time() * 1000)
    force_fixture = bool(getattr(args, "fixture", False))

    if force_fixture:
        rows = _load_fixture()
        if not rows:
            print("No fixture found at sample_data/live_pulse_fixture.json")
            return 1
        # use the fixture's own as_of so 'to close' reads sensibly
        base = max((r.get("as_of_ms") or 0) for r in rows) or now_ms
        _render(rows, live=False, now_ms=base)
        return 0

    print("Polling Kalshi public market data (read-only, keyless)…")
    try:
        rows = _fetch_live(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"Live pull failed ({exc}). Falling back to the committed fixture.")
        rows = []

    if not rows:
        print("No live 15-minute crypto series currently listed (or venue unreachable).")
        print("Showing the committed recorded fixture instead (NOT live):")
        rows = _load_fixture()
        if not rows:
            print("No fixture available either.")
            return 1
        base = max((r.get("as_of_ms") or 0) for r in rows) or now_ms
        _render(rows, live=False, now_ms=base)
        return 0

    _render(rows, live=True, now_ms=now_ms)
    return 0
