"""Capture the Up/Down settlement line (window-start price) with provenance.

For Polymarket BTC 5m up/down markets the line is the underlying price at
``window_start_ms``. The official Chainlink BTC/USD value is NOT exposed by the
public Gamma/CLOB APIs before (or after) resolution, so every feed-derived line
is marked :class:`~btc5m.schemas.LineSourceStatus.PROVISIONAL_REFERENCE`. A proxy
is never silently treated as settlement-grade truth.

Two capture modes:
- live: capture the current feed price (use while the window is open).
- historical: capture a 1-minute candle price at ``window_start_ms`` (backfill).

Records are persisted as JSONL under ``data/normalized/settlement_lines-*.jsonl``
and can be reloaded by the settlement backfill.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Iterable, Optional

from ..schemas import ContractMeta, LineSourceStatus, SettlementLineRecord
from ..timeutils import now_ms
from .recorder import Recorder

LINE_STREAM = "settlement_lines"


def make_line_record(
    meta: ContractMeta,
    *,
    line_price: Optional[float],
    line_source: str,
    status: LineSourceStatus,
    captured_at_ms: Optional[int],
    detail: str = "",
    raw: Optional[dict] = None,
) -> SettlementLineRecord:
    """Construct a :class:`SettlementLineRecord` from a market + captured price."""
    return SettlementLineRecord(
        slug=meta.slug,
        condition_id=meta.condition_id,
        market_id=meta.market_id,
        window_start_ms=meta.window_start_ms,
        expiry_ms=meta.expiry_ms,
        line_price=line_price,
        line_source=line_source,
        line_source_status=status,
        line_captured_at_ms=captured_at_ms,
        comparison=meta.comparison,
        resolution_source=meta.resolution_source,
        detail=detail,
        raw=raw or {},
    )


def capture_live_line(meta: ContractMeta, client, *, ref_ms: Optional[int] = None) -> SettlementLineRecord:
    """Capture a provisional line from the CURRENT feed price (window open).

    ``client`` must expose ``reference_price_now() -> (price, source, raw)``.
    """
    captured = ref_ms if ref_ms is not None else now_ms()
    if meta.window_start_ms is None:
        return make_line_record(
            meta, line_price=None, line_source="unknown",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail="window_start_ms unknown",
        )
    try:
        price, source, raw = client.reference_price_now()
    except Exception as exc:  # noqa: BLE001 - never raise out of capture
        return make_line_record(
            meta, line_price=None, line_source=getattr(client, "source", "unknown"),
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=f"capture failed: {type(exc).__name__}: {exc}",
        )
    if price is None:
        return make_line_record(
            meta, line_price=None, line_source=source,
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail="feed returned no price",
        )
    delay = captured - meta.window_start_ms
    return make_line_record(
        meta, line_price=price, line_source=source,
        status=LineSourceStatus.PROVISIONAL_REFERENCE, captured_at_ms=captured,
        detail=f"live capture; captured_at - window_start = {delay} ms (proxy, not Chainlink)",
        raw=raw,
    )


def capture_official_line(
    meta: ContractMeta, chainlink_client, *, ref_ms: Optional[int] = None
) -> SettlementLineRecord:
    """Capture the OFFICIAL window-start line from Chainlink Data Streams.

    ``chainlink_client`` must expose ``is_configured`` and
    ``price_at(ts_ms) -> (price, detail)``. If not configured or no price is
    returned, the result is UNKNOWN (never silently downgraded to provisional —
    the caller decides whether to fall back to a proxy).
    """
    captured = ref_ms if ref_ms is not None else now_ms()
    if meta.window_start_ms is None:
        return make_line_record(
            meta, line_price=None, line_source="chainlink_streams",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail="window_start_ms unknown",
        )
    if not getattr(chainlink_client, "is_configured", False):
        return make_line_record(
            meta, line_price=None, line_source="chainlink_streams",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=chainlink_client.not_configured_reason()
            if hasattr(chainlink_client, "not_configured_reason")
            else "chainlink not configured",
        )
    try:
        price, detail = chainlink_client.price_at(meta.window_start_ms)
    except Exception as exc:  # noqa: BLE001
        return make_line_record(
            meta, line_price=None, line_source="chainlink_streams",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=f"chainlink fetch failed: {type(exc).__name__}",
        )
    if price is None:
        return make_line_record(
            meta, line_price=None, line_source="chainlink_streams",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=f"chainlink returned no price ({detail})",
        )
    return make_line_record(
        meta, line_price=price, line_source="chainlink:btc-usd",
        status=LineSourceStatus.OFFICIAL, captured_at_ms=captured,
        detail=f"OFFICIAL Chainlink Data Streams line at window_start ({detail})",
        raw={"chainlink": detail},
    )


def capture_historical_line(
    meta: ContractMeta, coinbase_client, *, ref_ms: Optional[int] = None
) -> SettlementLineRecord:
    """Capture a provisional line at ``window_start_ms`` via 1-min candles (backfill).

    ``coinbase_client`` must expose ``price_at(ts_ms) -> (price, detail)``.
    """
    captured = ref_ms if ref_ms is not None else now_ms()
    if meta.window_start_ms is None:
        return make_line_record(
            meta, line_price=None, line_source="unknown",
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail="window_start_ms unknown",
        )
    try:
        price, detail = coinbase_client.price_at(meta.window_start_ms)
    except Exception as exc:  # noqa: BLE001
        return make_line_record(
            meta, line_price=None, line_source=getattr(coinbase_client, "source", "unknown"),
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=f"candle fetch failed: {type(exc).__name__}: {exc}",
        )
    if price is None:
        return make_line_record(
            meta, line_price=None, line_source=getattr(coinbase_client, "source", "unknown"),
            status=LineSourceStatus.UNKNOWN, captured_at_ms=captured,
            detail=f"no candle at window start ({detail})",
        )
    source = f"{getattr(coinbase_client, 'source', 'coinbase')}:{getattr(coinbase_client, 'symbol', 'BTC-USD')}"
    return make_line_record(
        meta, line_price=price, line_source=source,
        status=LineSourceStatus.PROVISIONAL_REFERENCE, captured_at_ms=captured,
        detail=f"historical candle line at window_start ({detail}); proxy, not Chainlink",
        raw={"candle": detail},
    )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def write_line_record(recorder: Recorder, rec: SettlementLineRecord) -> None:
    """Persist a line record (raw + normalized) via the Recorder."""
    recorder.record_raw(LINE_STREAM, dataclasses.asdict(rec))
    recorder.record_normalized(LINE_STREAM, rec)


def load_line_records(normalized_dir: Path) -> dict[str, dict]:
    """Load the latest line record per slug from settlement_lines JSONL files.

    Returns ``{slug: line_record_dict}``; later records override earlier ones.
    """
    out: dict[str, dict] = {}
    for path in sorted(Path(normalized_dir).glob(f"{LINE_STREAM}-*.jsonl")):
        for line in _iter_jsonl(path):
            ev = line.get("event") if isinstance(line, dict) else None
            if isinstance(ev, dict) and ev.get("slug"):
                out[ev["slug"]] = ev
    return out


def _iter_jsonl(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return
