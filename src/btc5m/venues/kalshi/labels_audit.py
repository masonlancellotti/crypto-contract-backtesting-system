"""Kalshi label auditing, dedup, and safe orphan compaction.

The settlement backfill labels every settled market the API returns — including
windows for which we recorded NO orderbook/feature data. Those are **orphan
labels**: a true OFFICIAL Kalshi result with no point-in-time features to learn
from. They must never inflate the training/backtest gate (which counts only
DISTINCT feature-backed official 15m windows).

This module:
- dedups raw label rows (latest row wins; OFFICIAL beats PROVISIONAL beats
  MANUAL_REVIEW beats UNKNOWN on equal recency),
- separates feature-backed official windows from orphans,
- never deletes raw labels: ``--write`` compaction writes a SEPARATE
  ``*_compacted-*.jsonl`` file and leaves the raw files untouched.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .readiness import (
    MIN_BACKTEST_WINDOWS, MIN_TRAIN_ROWS, MIN_TRAIN_WINDOWS,
    feature_row_usable,
)

# Higher = preferred when deduping rows for the same market_ticker.
_STATUS_PRIORITY = {
    "OFFICIAL": 4,
    "MANUAL_REVIEW": 3,        # keep, but never a clean training label
    "PROVISIONAL_REFERENCE": 2,
    "UNKNOWN": 1,
}


def _iter_jsonl(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return


def load_label_rows(config) -> list[dict]:
    d = config.data_path() / "labels"
    out: list[dict] = []
    if d.exists():
        for p in sorted(d.glob("kalshi_settlement_labels-*.jsonl")):
            out.extend(_iter_jsonl(p))
    return out


def _feature_rows(config, *, source=None) -> list[dict]:
    from .feature_source import load_feature_rows
    return load_feature_rows(config, source=source)


def load_feature_tickers(config, *, source=None) -> set[str]:
    """Distinct market_tickers that have at least one recorded feature row (presence)."""
    return {r.get("market_ticker") for r in _feature_rows(config, source=source)
            if r.get("market_ticker")}


def load_usable_feature_tickers(config, *, source=None) -> set[str]:
    """Distinct market_tickers with >=1 USABLE executable feature row (gate basis)."""
    return {r.get("market_ticker") for r in _feature_rows(config, source=source)
            if r.get("market_ticker") and feature_row_usable(r)}


def _better(a: dict, b: dict) -> dict:
    """Pick the preferred of two label rows for the same ticker."""
    pa = _STATUS_PRIORITY.get(a.get("label_source_status"), 0)
    pb = _STATUS_PRIORITY.get(b.get("label_source_status"), 0)
    if pa != pb:
        return a if pa > pb else b
    # equal status: latest created_at_ms wins
    return a if (a.get("created_at_ms") or 0) >= (b.get("created_at_ms") or 0) else b


def dedup_labels(label_rows: list[dict]) -> dict[str, dict]:
    """Collapse to one preferred row per market_ticker."""
    by_ticker: dict[str, dict] = {}
    for r in label_rows:
        tk = r.get("market_ticker")
        if not tk:
            continue
        by_ticker[tk] = _better(by_ticker[tk], r) if tk in by_ticker else r
    return by_ticker


def audit_labels(
    label_rows: list[dict],
    feature_tickers: set[str],
    usable_feature_tickers: Optional[set[str]] = None,
) -> dict:
    """Full label audit. Orphan = official label with NO feature rows.

    The AUTHORITATIVE gate count (``gate_windows``) uses ``usable_feature_tickers``
    — official windows with >=1 *usable executable* feature row — matching
    ``readiness.gate_windows`` exactly. When ``usable_feature_tickers`` is not
    supplied it falls back to presence (``feature_tickers``) so the function stays
    usable standalone; the CLI always supplies the usable set.
    """
    total = len(label_rows)
    deduped = dedup_labels(label_rows)
    by_status = Counter(r.get("label_source_status") for r in deduped.values())
    usable = usable_feature_tickers if usable_feature_tickers is not None else feature_tickers

    official = {tk: r for tk, r in deduped.items()
                if r.get("label_source_status") == "OFFICIAL" and r.get("label_yes_resolved") is not None}
    feature_backed_official = {tk for tk in official if tk in feature_tickers}     # presence
    gate_official = {tk for tk in official if tk in usable}                        # AUTHORITATIVE
    orphan_official = {tk for tk in official if tk not in feature_tickers}
    orphan_any = {tk for tk in deduped if tk not in feature_tickers}

    # Distinct 15m windows do not overlap, so window-level purge/embargo leaves
    # each gate-eligible window as an independent sample.
    gate_count = len(gate_official)
    return {
        "total_label_rows": total,
        "deduped_labels": len(deduped),
        "duplicate_label_rows": total - len(deduped),
        "official_labels": len(official),
        "provisional_labels": by_status.get("PROVISIONAL_REFERENCE", 0),
        "manual_review_labels": by_status.get("MANUAL_REVIEW", 0),
        "unknown_labels": by_status.get("UNKNOWN", 0),
        "labels_with_feature_rows": sum(1 for tk in deduped if tk in feature_tickers),
        "orphan_labels": len(orphan_any),
        "orphan_official_labels": len(orphan_official),
        "official_feature_backed_labels": len(feature_backed_official),   # presence (e.g. 38)
        "feature_backed_unusable_windows": len(feature_backed_official) - gate_count,
        "gate_windows": gate_count,                                       # AUTHORITATIVE (e.g. 35)
        "feature_backed_eligible_after_purge_embargo": gate_count,
        "labels_rejected_no_feature_rows": len(orphan_official),
        "labels_rejected_unusable_features": len(feature_backed_official) - gate_count,
        "backtest_gate_count": gate_count,
        "backtest_gate_threshold": MIN_BACKTEST_WINDOWS,
        "train_gate_count": gate_count,
        "train_gate_threshold": MIN_TRAIN_WINDOWS,
        "train_gate_min_rows": MIN_TRAIN_ROWS,
        "backtest_allowed": gate_count >= MIN_BACKTEST_WINDOWS,
        "train_allowed": gate_count >= MIN_TRAIN_WINDOWS,
        "gate_official_tickers": sorted(gate_official),
        "feature_backed_official_tickers": sorted(feature_backed_official),
    }


def compact_labels(
    config,
    *,
    write: bool = False,
    ref_ms: Optional[int] = None,
) -> dict:
    """Audit + (optionally) write compacted label files. Raw files are NEVER
    modified or deleted.

    With ``write=True`` two SEPARATE files are written:
    - ``kalshi_settlement_labels_compacted-YYYYMMDD.jsonl`` — one preferred row per
      ticker, every row tagged ``is_orphan`` / ``has_feature_rows`` / ``gate_eligible``.
    - ``kalshi_training_labels-YYYYMMDD.jsonl`` — ONLY gate-eligible official labels
      (usable executable feature rows present). **Orphans are excluded**, so this
      is the clean training label set; it cannot inflate the gate.
    """
    rows = load_label_rows(config)
    feature_tickers = load_feature_tickers(config)
    usable = load_usable_feature_tickers(config)
    report = audit_labels(rows, feature_tickers, usable)
    deduped = dedup_labels(rows)
    compacted_path = training_path = None
    if write and deduped:
        d = config.data_path() / "labels"
        d.mkdir(parents=True, exist_ok=True)
        ts = ref_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
        day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
        compacted_path = d / f"kalshi_settlement_labels_compacted-{day}.jsonl"
        training_rows = []
        with compacted_path.open("w", encoding="utf-8") as fh:
            for tk, r in sorted(deduped.items()):
                out = dict(r)
                is_official = (r.get("label_source_status") == "OFFICIAL"
                               and r.get("label_yes_resolved") is not None)
                out["is_orphan"] = tk not in feature_tickers
                out["has_feature_rows"] = tk in feature_tickers
                out["gate_eligible"] = bool(is_official and tk in usable)
                fh.write(json.dumps(out) + "\n")
                if out["gate_eligible"]:
                    training_rows.append(out)
        if training_rows:
            training_path = d / f"kalshi_training_labels-{day}.jsonl"
            with training_path.open("w", encoding="utf-8") as fh:
                for out in training_rows:
                    fh.write(json.dumps(out) + "\n")
    report["compacted_file"] = str(compacted_path) if compacted_path else None
    report["training_labels_file"] = str(training_path) if training_path else None
    report["raw_label_files_preserved"] = True
    return report
