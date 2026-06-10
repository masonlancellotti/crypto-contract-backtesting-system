"""Settlement backfill: label completed recorded windows.

Joins recorded Polymarket market metadata + captured line records with:
- the OFFICIAL resolved outcome from Gamma (``outcomePrices`` once closed) —
  settlement-grade for the binary YES/NO, and
- PROVISIONAL numeric prices (window-start line + final reference) derived from
  a BTC feed (Coinbase 1-min candles) — clearly marked, never settlement-grade.

Hard rules enforced here:
- Missing line or final price → explicit UNKNOWN / MISSING_* reason code.
- Never guess from title text.
- Never claim a label is settlement-grade unless the official source supports it.
- If the official outcome and the computed (provisional) label disagree, flag
  MANUAL_REVIEW and keep BOTH values — never overwrite silently.

The pure labeling logic (:func:`build_label_row`, :func:`official_outcome_from_market`)
is network-free and unit-tested with fixtures. :func:`backfill_settlements`
orchestrates the network fetches and is gated/optional.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from ..schemas import Comparison, ContractMeta
from ..timeutils import now_ms
from .settlement import ReasonCode, label_yes_resolved


class LabelSourceStatus(str, Enum):
    """Provenance/quality of a backfilled label row."""

    OFFICIAL = "OFFICIAL"                      # official outcome present (agrees if computed)
    PROVISIONAL_REFERENCE = "PROVISIONAL_REFERENCE"  # computed-from-proxy only, no official
    MANUAL_REVIEW = "MANUAL_REVIEW"            # official vs computed disagree
    UNKNOWN = "UNKNOWN"                        # no label determinable


@dataclass
class LabelRow:
    slug: Optional[str]
    condition_id: Optional[str]
    window_start_ms: Optional[int]
    expiry_ms: int
    line_price: Optional[float]
    final_reference_price: Optional[float]
    settlement_distance: Optional[float]
    label_yes_resolved: Optional[int]
    official_outcome: Optional[int]
    comparison: str
    reason_code: str
    label_source_status: str
    created_at_ms: int
    # Provenance of the NUMERIC inputs (line / final). OFFICIAL only when sourced
    # from Chainlink; otherwise PROVISIONAL_REFERENCE / UNKNOWN.
    line_source_status: str = "UNKNOWN"
    final_reference_source_status: str = "UNKNOWN"
    detail: str = ""


def official_outcome_from_market(market: dict) -> Optional[int]:
    """Return the official YES(=Up) outcome (1/0) from a RESOLVED Gamma market.

    Returns None unless the market is closed AND ``outcomePrices`` is a clean
    resolved {0,1} pair. YES corresponds to ``outcomes[0]`` (Up).
    """
    if not market.get("closed"):
        return None
    outcomes = _loads_maybe(market.get("outcomes"))
    prices = _loads_maybe(market.get("outcomePrices"))
    if not (isinstance(outcomes, list) and isinstance(prices, list)):
        return None
    if len(prices) < 2:
        return None
    try:
        p_yes, p_no = float(prices[0]), float(prices[1])
    except (TypeError, ValueError):
        return None
    # Require a clean resolved pair (one is 1, the other 0).
    if {round(p_yes), round(p_no)} != {0, 1} or abs((p_yes + p_no) - 1.0) > 1e-6:
        return None
    return 1 if round(p_yes) == 1 else 0


def build_label_row(
    meta: ContractMeta,
    *,
    line_price: Optional[float],
    final_reference_price: Optional[float],
    official_yes: Optional[int],
    created_at_ms: Optional[int] = None,
    line_source_status: str = "UNKNOWN",
    final_reference_source_status: str = "UNKNOWN",
) -> LabelRow:
    """Build a single :class:`LabelRow` from inputs. Network-free, deterministic.

    The computed (provisional) label comes from :func:`label_yes_resolved` using
    ``line_price`` + ``final_reference_price``. The official outcome (if any) is
    settlement-grade. Disagreement → MANUAL_REVIEW (both values kept).
    """
    created = created_at_ms if created_at_ms is not None else now_ms()
    meta_with_line = replace(meta, line=line_price)
    result = label_yes_resolved(meta_with_line, final_reference_price)
    computed = result.yes_resolved
    reason = result.reason
    dist = result.settlement_distance

    detail = result.detail
    if official_yes is not None and computed is not None:
        if official_yes == computed:
            status = LabelSourceStatus.OFFICIAL
            label = official_yes  # official confirms; trustworthy
            detail = f"official confirms computed ({detail})"
        else:
            status = LabelSourceStatus.MANUAL_REVIEW
            label = computed  # keep computed; do NOT silently overwrite with official
            detail = (
                f"DISAGREEMENT official={official_yes} computed={computed}; "
                f"manual review required ({detail})"
            )
    elif official_yes is not None:
        # Official binary known but provisional numeric missing/invalid.
        status = LabelSourceStatus.OFFICIAL
        label = official_yes
        detail = f"official outcome only; computed unavailable ({reason.value})"
    elif computed is not None:
        status = LabelSourceStatus.PROVISIONAL_REFERENCE
        label = computed
        detail = f"provisional (proxy) only; no official outcome ({detail})"
    else:
        status = LabelSourceStatus.UNKNOWN
        label = None
        detail = f"undeterminable ({reason.value})"

    return LabelRow(
        slug=meta.slug,
        condition_id=meta.condition_id,
        window_start_ms=meta.window_start_ms,
        expiry_ms=meta.expiry_ms,
        line_price=line_price,
        final_reference_price=final_reference_price,
        settlement_distance=dist,
        label_yes_resolved=label,
        official_outcome=official_yes,
        comparison=meta.comparison.value if isinstance(meta.comparison, Comparison) else str(meta.comparison),
        reason_code=reason.value,
        label_source_status=status.value,
        created_at_ms=created,
        line_source_status=line_source_status,
        final_reference_source_status=final_reference_source_status,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# File helpers
# --------------------------------------------------------------------------- #
def load_recorded_markets(raw_dir: Path, *, slug_prefix: str = "") -> dict[str, dict]:
    """Load the latest raw market dict per slug from polymarket_markets JSONL.

    Returns ``{slug: market_dict}``; later records override earlier (more recent
    resolution state wins).
    """
    out: dict[str, dict] = {}
    for path in sorted(Path(raw_dir).glob("polymarket_markets-*.jsonl")):
        for rec in _iter_jsonl(path):
            payload = rec.get("payload") if isinstance(rec, dict) else None
            if not isinstance(payload, dict):
                continue
            slug = payload.get("slug")
            if not slug or (slug_prefix and not slug.startswith(slug_prefix)):
                continue
            out[slug] = payload
    return out


def write_label_rows(path: Path, rows: Iterable[LabelRow]) -> int:
    """Append label rows as JSONL. Returns the number written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dataclasses.asdict(row)) + "\n")
            n += 1
    return n


def backfill_settlements(
    config,
    *,
    asset: str = "BTC",
    duration: str = "5m",
    use_network: bool = True,
    line_source: str = "coinbase",
    ref_ms: Optional[int] = None,
    write: bool = True,
) -> tuple[list[LabelRow], dict]:
    """Orchestrate a settlement backfill over recorded, completed windows.

    Network-gated: with ``use_network=False`` it runs purely on recorded data
    and emits precise UNKNOWN/MISSING_* rows. Returns (rows, summary).
    """
    from datetime import datetime, timezone

    from ..data.chainlink import ChainlinkStreamsClient
    from ..data.line_capture import load_line_records
    from ..data.polymarket_client import PolymarketClient, _slug_prefix
    from ..data.underlying import CoinbaseSpotClient

    raw_dir = config.data_path() / "raw"
    norm_dir = config.data_path() / "normalized"
    labels_dir = config.data_path() / "labels"
    now = ref_ms if ref_ms is not None else now_ms()
    prefix = _slug_prefix(asset, duration)

    markets = load_recorded_markets(raw_dir, slug_prefix=prefix)
    line_records = load_line_records(norm_dir)
    client = PolymarketClient(config)
    coinbase = CoinbaseSpotClient(config)
    chainlink = ChainlinkStreamsClient(config)  # OFFICIAL only if configured (env)

    rows: list[LabelRow] = []
    counts = {s.value: 0 for s in LabelSourceStatus}
    completed = 0
    for slug, mkt in markets.items():
        meta = client._parse_market(mkt, asset=asset)
        if meta.expiry_ms <= 0 or meta.expiry_ms >= now:
            continue  # window not completed yet
        completed += 1

        # ---- Line price + provenance --------------------------------------
        line_price = None
        line_status = "UNKNOWN"
        # 1) OFFICIAL Chainlink (only if configured).
        if use_network and chainlink.is_configured and meta.window_start_ms:
            p, _ = chainlink.price_at(meta.window_start_ms)
            if p is not None:
                line_price, line_status = p, "OFFICIAL"
        # 2) A captured line record (may be OFFICIAL or PROVISIONAL).
        if line_price is None:
            lr = line_records.get(slug)
            if lr and lr.get("line_price") is not None and lr.get("line_source_status") != "UNKNOWN":
                line_price = lr.get("line_price")
                line_status = lr.get("line_source_status", "PROVISIONAL_REFERENCE")
        # 3) PROVISIONAL Coinbase candle.
        if line_price is None and use_network and meta.window_start_ms:
            try:
                line_price, _ = coinbase.price_at(meta.window_start_ms)
                if line_price is not None:
                    line_status = "PROVISIONAL_REFERENCE"
            except Exception:  # noqa: BLE001
                line_price = None

        # ---- Final reference price + provenance ---------------------------
        final_price = None
        final_status = "UNKNOWN"
        if use_network and chainlink.is_configured:
            p, _ = chainlink.price_at(meta.expiry_ms)
            if p is not None:
                final_price, final_status = p, "OFFICIAL"
        if final_price is None and use_network:
            try:
                final_price, _ = coinbase.price_at(meta.expiry_ms)
                if final_price is not None:
                    final_status = "PROVISIONAL_REFERENCE"
            except Exception:  # noqa: BLE001
                final_price = None

        # ---- Official binary outcome --------------------------------------
        official = official_outcome_from_market(mkt)
        if official is None and use_network:
            try:
                resolved = client.get_resolved_market_raw(slug)
                if resolved:
                    official = official_outcome_from_market(resolved)
            except Exception:  # noqa: BLE001
                official = None

        row = build_label_row(
            meta,
            line_price=line_price,
            final_reference_price=final_price,
            official_yes=official,
            created_at_ms=now,
            line_source_status=line_status,
            final_reference_source_status=final_status,
        )
        rows.append(row)
        counts[row.label_source_status] = counts.get(row.label_source_status, 0) + 1

    written = 0
    labels_file = None
    if write and rows:
        day = datetime.fromtimestamp(now / 1000, tz=timezone.utc).strftime("%Y%m%d")
        labels_file = labels_dir / f"settlement_labels-{day}.jsonl"
        written = write_label_rows(labels_file, rows)

    summary = {
        "markets_loaded": len(markets),
        "completed_windows": completed,
        "rows": len(rows),
        "by_status": counts,
        "written": written,
        "labels_file": str(labels_file) if labels_file else None,
        "use_network": use_network,
    }
    return rows, summary


def load_label_rows(labels_dir: Path) -> list[dict]:
    """Load all label rows from settlement_labels JSONL files."""
    out: list[dict] = []
    for path in sorted(Path(labels_dir).glob("settlement_labels-*.jsonl")):
        out.extend(_iter_jsonl(path))
    return out


def _loads_maybe(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


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
