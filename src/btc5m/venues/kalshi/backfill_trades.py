"""Historical backfill of PUBLIC Kalshi trade prints (read-only; no auth, no orders).

Kalshi's public ``GET /markets/trades`` serves the full historical tape (verified
back to at least 2026-06-01). That means real fills for every window already
collected can be fetched NOW instead of waiting for the live poller to
accumulate — the input the maker-entry study needs (RESEARCH_LEDGER legs 13/14).

Pages the global tape in time chunks (newest-first per Kalshi), filters to the
requested series, dedupes by trade_id against rows already on disk (live poller
or previous backfills), and appends rows in the SAME normalized shape/stream
(``kalshi_trades``) keyed by the TRADE's UTC date. Idempotent: re-running adds
nothing new.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from .client import KalshiClient, iso_to_ms
from .readiness import _event, _iter_jsonl


def _fnum(x) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _day_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y%m%d")


def _parse_day(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)


def existing_trade_ids(config) -> set[str]:
    """trade_ids already recorded (live poller or previous backfill)."""
    ids: set[str] = set()
    d = config.data_path() / "normalized"
    if d.exists():
        for p in sorted(d.glob("kalshi_trades-*.jsonl")):
            for row in _iter_jsonl(p):
                tid = _event(row).get("trade_id")
                if tid:
                    ids.add(tid)
    return ids


def backfill_trades(config, *, series: str = "KXBTC15M", start_date: str,
                    end_date: Optional[str] = None, chunk_hours: int = 1,
                    limit: int = 1000, max_pages_per_chunk: int = 300,
                    emit=print) -> dict:
    """Fetch + persist historical trade prints for ``series``. Idempotent."""
    client = KalshiClient(config)
    seen = existing_trade_ids(config)
    emit(f"  existing trade_ids on disk: {len(seen)}")

    start = _parse_day(start_date)
    end = (_parse_day(end_date) + timedelta(days=1)) if end_date \
        else datetime.now(timezone.utc)
    out_dir = config.data_path() / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = {"chunks": 0, "fetched": 0, "series_matched": 0, "written": 0,
              "duplicates_skipped": 0, "errors": 0, "pages_capped_chunks": 0}
    days_touched: set[str] = set()
    recv_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    t = start
    while t < end:
        t_next = min(t + timedelta(hours=chunk_hours), end)
        counts["chunks"] += 1
        try:
            trades = client.get_trades(min_ts=int(t.timestamp()),
                                       max_ts=int(t_next.timestamp()),
                                       limit=limit, max_pages=max_pages_per_chunk)
        except Exception as exc:  # noqa: BLE001
            counts["errors"] += 1
            emit(f"  chunk {t:%Y-%m-%d %H:%M} ERROR: {str(exc)[:80]}")
            t = t_next
            continue
        counts["fetched"] += len(trades)
        if len(trades) >= limit * max_pages_per_chunk:
            counts["pages_capped_chunks"] += 1
            emit(f"  WARNING chunk {t:%Y-%m-%d %H:%M} hit the page cap "
                 f"({limit}x{max_pages_per_chunk}); shrink --chunk-hours to avoid gaps")
        by_day: dict[str, list[dict]] = {}
        for tr in trades:
            tk = tr.get("ticker") or ""
            tid = tr.get("trade_id")
            if not tk.startswith(series) or not tid:
                continue
            counts["series_matched"] += 1
            if tid in seen:
                counts["duplicates_skipped"] += 1
                continue
            seen.add(tid)
            created_ms = iso_to_ms(tr.get("created_time"))
            row = {
                "venue": "kalshi", "series_ticker": series, "market_ticker": tk,
                "trade_id": tid, "created_time_ms": created_ms, "recv_ms": recv_ms,
                "yes_price": _fnum(tr.get("yes_price_dollars", tr.get("yes_price"))),
                "no_price": _fnum(tr.get("no_price_dollars", tr.get("no_price"))),
                "count": _fnum(tr.get("count_fp", tr.get("count"))),
                "taker_side": tr.get("taker_side"),
                "is_block_trade": bool(tr.get("is_block_trade")),
                "backfilled": True,
            }
            day = _day_str(created_ms) if created_ms else _day_str(recv_ms)
            by_day.setdefault(day, []).append(row)
            counts["written"] += 1
        # flush PER CHUNK so a killed run keeps everything fetched so far
        # (idempotent: the trade_id dedupe absorbs any rerun overlap)
        for day, rows in sorted(by_day.items()):
            rows.sort(key=lambda r: r.get("created_time_ms") or 0)
            path = out_dir / f"kalshi_trades-{day}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps({"stream": "kalshi_trades", "event": r}) + "\n")
            days_touched.add(day)
        if counts["chunks"] % 24 == 0:
            emit(f"  progress: through {t_next:%Y-%m-%d %H:%M} "
                 f"written={counts['written']} fetched={counts['fetched']}")
        t = t_next

    counts["days_touched"] = len(days_touched)
    counts["live_submission_allowed"] = False
    return counts


def load_trade_prints(config, *, series: str = "KXBTC15M",
                      slim: bool = True) -> dict[str, list[dict]]:
    """Per-ticker, time-sorted trade prints (deduped by trade_id).

    ``slim`` (default) keeps only the fields fill modeling needs — at the
    full tape's volume (~650k prints/day) the discarded metadata would
    multiply memory use several-fold.
    """
    by_tk: dict[str, list[dict]] = {}
    seen: set[str] = set()
    d = config.data_path() / "normalized"
    if d.exists():
        for p in sorted(d.glob("kalshi_trades-*.jsonl")):
            for row in _iter_jsonl(p):
                e = _event(row)
                tk = e.get("market_ticker") or ""
                tid = e.get("trade_id")
                if not tk.startswith(series) or not tid or tid in seen:
                    continue
                if e.get("created_time_ms") is None:
                    continue
                seen.add(tid)
                if slim:
                    e = {"created_time_ms": e["created_time_ms"],
                         "yes_price": e.get("yes_price"),
                         "no_price": e.get("no_price"),
                         "count": e.get("count"),
                         "taker_side": e.get("taker_side")}
                by_tk.setdefault(tk, []).append(e)
    for tk in by_tk:
        by_tk[tk].sort(key=lambda r: r["created_time_ms"])
    return by_tk
