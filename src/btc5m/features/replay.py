"""Event-replay assembly of point-in-time feature rows from recorded data.

Reads normalized JSONL (Polymarket book events + Coinbase/Binance underlying +
settlement lines) and replays them in timestamp order, emitting one feature row
per Polymarket book update. Underlying windows are advanced by a merge so a row
at ``as_of_ms`` only sees underlying events with ts <= as_of_ms (no look-ahead).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from .feature_builder import build_feature_row
from .window import UnderlyingWindow


def _iter_jsonl(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return


def _load_events(norm_dir: Path, stream_glob: str, key: str = "event") -> list[dict]:
    out: list[dict] = []
    for path in sorted(Path(norm_dir).glob(stream_glob)):
        for rec in _iter_jsonl(path):
            ev = rec.get(key)
            if isinstance(ev, dict):
                out.append(ev)
    return out


def _ev_ts(ev: dict) -> int:
    return int(ev.get("recv_ms") or ev.get("exchange_ts_ms") or ev.get("ts_ms") or 0)


def build_feature_rows_from_recorded(
    config,
    *,
    asset: str = "BTC",
    duration: str = "5m",
    max_rows: Optional[int] = None,
) -> list[dict]:
    """Replay recorded normalized data into point-in-time feature rows."""
    from ..data.line_capture import load_line_records
    from ..data.polymarket_client import PolymarketClient, _slug_prefix

    norm_dir = config.data_path() / "normalized"
    raw_dir = config.data_path() / "raw"
    prefix = _slug_prefix(asset, duration)

    from ..labels.settlement_backfill import load_recorded_markets

    markets = load_recorded_markets(raw_dir, slug_prefix=prefix)
    line_records = load_line_records(norm_dir)
    client = PolymarketClient(config)
    metas = {slug: client._parse_market(m, asset=asset) for slug, m in markets.items()}

    book_events = [
        ev for ev in _load_events(norm_dir, "polymarket_book-*.jsonl")
        if (ev.get("slug") or "").startswith(prefix)
    ]
    book_events.sort(key=_ev_ts)

    underlying = sorted(
        _load_events(norm_dir, "underlying_coinbase-*.jsonl")
        + _load_events(norm_dir, "underlying_binance_futures-*.jsonl"),
        key=_ev_ts,
    )

    spot = UnderlyingWindow("coinbase")
    perp = UnderlyingWindow("binance_futures")
    u_idx = 0

    latest_yes: dict[str, dict] = {}
    latest_no: dict[str, dict] = {}
    rows: list[dict] = []

    for be in book_events:
        as_of = _ev_ts(be)
        # advance underlying windows up to as_of (no look-ahead)
        while u_idx < len(underlying) and _ev_ts(underlying[u_idx]) <= as_of:
            ue = underlying[u_idx]
            (spot if ue.get("source") == "coinbase" else perp).add_event(ue)
            u_idx += 1

        slug = be.get("slug")
        if be.get("outcome") == "YES":
            latest_yes[slug] = be
        elif be.get("outcome") == "NO":
            latest_no[slug] = be

        meta = metas.get(slug)
        lr = line_records.get(slug)
        row = build_feature_row(
            as_of_ms=as_of,
            slug=slug,
            condition_id=be.get("condition_id"),
            window_start_ms=(meta.window_start_ms if meta else be.get("window_start_ms")),
            expiry_ms=(meta.expiry_ms if meta else be.get("expiry_ms")),
            comparison=(meta.comparison.value if meta else "GTE"),
            yes_event=latest_yes.get(slug),
            no_event=latest_no.get(slug),
            line_record=lr,
            spot_window=spot,
            perp_window=perp,
            yes_token_id=(meta.yes_token_id if meta else None),
            no_token_id=(meta.no_token_id if meta else None),
        )
        rows.append(row)
        if max_rows is not None and len(rows) >= max_rows:
            break
    return rows
