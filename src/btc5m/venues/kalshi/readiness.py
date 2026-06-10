"""Kalshi data-readiness — honest, category-split gating.

Gates require enough DISTINCT settled 15-minute windows, not just a high row
count: intraday point-in-time rows from a handful of windows are heavily
overlapping and would overstate readiness. A missing BTC reference price must
NOT erase an OFFICIAL Kalshi binary label; a missing official settlement must
block official-label training.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

# Gate on distinct settled windows (independent samples) + row counts.
MIN_TRAIN_WINDOWS = 150
MIN_BACKTEST_WINDOWS = 60
MIN_TRAIN_ROWS = 500


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


def _load_glob(d: Path, pattern: str) -> list[dict]:
    out: list[dict] = []
    if d.exists():
        for p in sorted(d.glob(pattern)):
            out.extend(_iter_jsonl(p))
    return out


def _event(row: dict) -> dict:
    """Recorder normalized rows are wrapped as {'stream':..., 'event': {...}}."""
    if isinstance(row, dict) and isinstance(row.get("event"), dict):
        return row["event"]
    return row


def feature_row_usable(r: dict) -> bool:
    """True iff a feature row is a usable, EXECUTABLE Kalshi example.

    Requires a Kalshi order book, a BTC underlying reference, a pre-close
    timestamp, and a valid (non-crossed/complete/in-range) book. **Underlying-only
    rows (a BTC reference but no Kalshi book) are NEVER usable as executable
    Kalshi examples** — this is the single predicate the gate, the audit, and the
    training dry-run all share, so the authoritative count cannot drift.
    """
    if not bool(r.get("has_orderbook")):
        return False
    if not bool(r.get("has_underlying")):
        return False
    secs = r.get("seconds_to_close")
    if not (secs is not None and secs > 0):
        return False
    return bool(r.get("book_ok", True))


def usable_feature_tickers(feature_rows: Iterable[dict]) -> set:
    """Distinct market_tickers that have >=1 usable executable feature row."""
    return {r.get("market_ticker") for r in feature_rows
            if r.get("market_ticker") and feature_row_usable(r)}


def assess_kalshi_readiness(
    *,
    label_rows: list[dict],
    feature_rows: list[dict],
    normalized_orderbook_rows: int,
    raw_orderbook_rows: int,
    underlying_rows: int,
    markets_by_phase: dict,
) -> dict:
    # ---- labels: one per market_ticker, official binary survives missing refs.
    by_ticker: dict[str, dict] = {}
    for lr in label_rows:
        tk = lr.get("market_ticker")
        if tk:
            by_ticker[tk] = lr  # later wins (append-only safe enough for counts)
    official_by_ticker = {
        tk: lr for tk, lr in by_ticker.items()
        if lr.get("label_source_status") == "OFFICIAL" and lr.get("label_yes_resolved") is not None
    }
    official_binary_labels = len(official_by_ticker)
    provisional_reference_rows = sum(
        1 for lr in by_ticker.values() if lr.get("label_source_status") == "PROVISIONAL_REFERENCE")
    unknown_label_rows = sum(
        1 for lr in by_ticker.values() if lr.get("label_source_status") == "UNKNOWN")
    manual_review_rows = sum(
        1 for lr in by_ticker.values() if lr.get("label_source_status") == "MANUAL_REVIEW")

    # ---- features: clearly separated categories (no double-counting of roles).
    feature_tickers = {r.get("market_ticker") for r in feature_rows if r.get("market_ticker")}
    with_ob = with_und = with_start = without_start = 0
    underlying_only = book_backed = 0
    usable_binary = usable_line = usable_backtest = 0
    rej_missing_book = rej_missing_underlying = rej_window_closed_or_bad_book = rej_no_official_label = 0
    labeled_binary_windows: set[str] = set()
    for r in feature_rows:
        has_ob = bool(r.get("has_orderbook"))
        has_und = bool(r.get("has_underlying"))
        has_start = bool(r.get("has_start_reference"))
        if has_ob:
            with_ob += 1
            book_backed += 1
        else:
            rej_missing_book += 1
            if has_und:
                underlying_only += 1   # BTC ref but NO Kalshi book -> not executable
        if has_und:
            with_und += 1
        else:
            rej_missing_underlying += 1
        if has_start:
            with_start += 1
        else:
            without_start += 1
        tk = r.get("market_ticker")
        usable = feature_row_usable(r)
        if usable:
            usable_binary += 1
            if has_start and r.get("reference_price") is not None:
                usable_line += 1
            if tk in official_by_ticker:
                usable_backtest += 1
                labeled_binary_windows.add(tk)
            else:
                rej_no_official_label += 1
        elif has_ob:
            rej_window_closed_or_bad_book += 1

    # Feature-backed (PRESENCE) = official labels with >=1 feature row of any kind.
    # Gate windows (USABLE) = official labels with >=1 usable executable row.
    # Orphans have an OFFICIAL result but NO feature rows at all.
    feature_backed_official_windows = sum(1 for tk in official_by_ticker if tk in feature_tickers)
    orphan_labels = len(by_ticker) - sum(1 for tk in by_ticker if tk in feature_tickers)
    orphan_official_labels = official_binary_labels - feature_backed_official_windows
    distinct_settled_windows = official_binary_labels

    labeled_windows = len(labeled_binary_windows)
    # The ONE authoritative gate count used everywhere (backtest + train).
    gate_windows = labeled_windows
    feature_backed_unusable_windows = feature_backed_official_windows - gate_windows
    training_allowed_binary_model = (
        labeled_windows >= MIN_TRAIN_WINDOWS and usable_backtest >= MIN_TRAIN_ROWS)
    training_allowed_line_model = (
        labeled_windows >= MIN_TRAIN_WINDOWS and usable_line >= MIN_TRAIN_ROWS
        and with_start > 0)
    backtest_allowed = labeled_windows >= MIN_BACKTEST_WINDOWS

    reasons_training_blocked: list[str] = []
    if labeled_windows < MIN_TRAIN_WINDOWS:
        reasons_training_blocked.append(
            f"distinct OFFICIAL-labeled windows={labeled_windows} < {MIN_TRAIN_WINDOWS} "
            f"(15m windows; overlapping rows do not count as independent samples)")
    if usable_backtest < MIN_TRAIN_ROWS:
        reasons_training_blocked.append(
            f"usable labeled feature rows={usable_backtest} < {MIN_TRAIN_ROWS}")
    if official_binary_labels == 0:
        reasons_training_blocked.append(
            "no OFFICIAL Kalshi settlements yet (run kalshi-backfill-settlements after windows finalize)")
    reasons_backtest_blocked: list[str] = []
    if labeled_windows < MIN_BACKTEST_WINDOWS:
        reasons_backtest_blocked.append(
            f"authoritative gate_windows={gate_windows} < {MIN_BACKTEST_WINDOWS}")
    if feature_backed_unusable_windows > 0:
        note_gap = (
            f"{feature_backed_unusable_windows} feature-backed window(s) have NO usable "
            f"executable row (post-close/empty/invalid book) -> counted in "
            f"feature_backed_official_windows={feature_backed_official_windows} but NOT in the "
            f"authoritative gate_windows={gate_windows}")
        reasons_backtest_blocked.append(note_gap)

    if markets_by_phase.get("CURRENT_IN_WINDOW", 0) == 0 and markets_by_phase.get("UPCOMING", 0) == 0:
        rec = "kalshi-discover (no current/upcoming markets seen yet)"
    elif official_binary_labels == 0:
        rec = "run-kalshi-paper-pipeline / kalshi-record, then kalshi-backfill-settlements"
    elif not backtest_allowed:
        rec = f"keep collecting: need {MIN_BACKTEST_WINDOWS - labeled_windows} more settled windows for backtest"
    else:
        rec = "backtest_allowed — proceed to calibrated model + paper-backtest"

    return {
        "markets_seen": sum(markets_by_phase.values()),
        "open_markets": markets_by_phase.get("CURRENT_IN_WINDOW", 0),
        "upcoming_markets": markets_by_phase.get("UPCOMING", 0),
        "closed_markets": markets_by_phase.get("CLOSED_PENDING_SETTLE", 0),
        "settled_markets": markets_by_phase.get("SETTLED", 0),
        "raw_orderbook_rows": raw_orderbook_rows,
        "normalized_orderbook_rows": normalized_orderbook_rows,
        "underlying_rows": underlying_rows,
        # ----- labels -----
        "official_binary_labels": official_binary_labels,
        "feature_backed_official_windows": feature_backed_official_windows,
        "feature_backed_unusable_windows": feature_backed_unusable_windows,
        "orphan_labels": orphan_labels,
        "orphan_official_labels": orphan_official_labels,
        "provisional_reference_rows": provisional_reference_rows,
        "unknown_label_rows": unknown_label_rows,
        "manual_review_rows": manual_review_rows,
        "distinct_settled_windows": distinct_settled_windows,
        # ----- feature-row categories (each row counted in every category it meets) -----
        "feature_rows_total": len(feature_rows),
        "feature_rows_underlying_only": underlying_only,
        "feature_rows_book_backed": book_backed,
        "feature_rows_with_orderbook": with_ob,
        "feature_rows_with_underlying": with_und,
        "feature_rows_with_start_reference": with_start,
        "feature_rows_without_start_reference": without_start,
        "rows_rejected_missing_book": rej_missing_book,
        "rows_rejected_missing_underlying": rej_missing_underlying,
        "rows_rejected_window_closed_or_bad_book": rej_window_closed_or_bad_book,
        "rows_rejected_no_official_label": rej_no_official_label,
        "usable_rows_for_binary_model": usable_binary,
        "usable_rows_for_line_distance_model": usable_line,
        "usable_rows_for_backtest": usable_backtest,
        "training_eligible_rows": usable_backtest,
        # ----- ONE authoritative gate -----
        "gate_windows": gate_windows,
        "authoritative_gate_count": gate_windows,
        "gate_basis": ("distinct OFFICIAL-labeled 15m windows with >=1 usable executable "
                       "book-backed feature row (purge/embargo on 15m windows)"),
        "labeled_windows": labeled_windows,   # == gate_windows (back-compat alias)
        "backtest_gate_threshold": MIN_BACKTEST_WINDOWS,
        "train_gate_threshold": MIN_TRAIN_WINDOWS,
        "train_gate_min_rows": MIN_TRAIN_ROWS,
        "training_allowed_binary_model": training_allowed_binary_model,
        "training_allowed_line_model": training_allowed_line_model,
        "backtest_allowed": backtest_allowed,
        "reasons_training_blocked": reasons_training_blocked,
        "reasons_backtest_blocked": reasons_backtest_blocked,
        "recommended_next_command": rec,
        "note": "Gates require DISTINCT settled 15m windows (purge/embargo on 15m windows).",
    }


def load_kalshi_readiness(config) -> dict:
    """Load Kalshi rows from disk and assess readiness."""
    data = config.data_path()
    raw = data / "raw"
    norm = data / "normalized"
    labels = data / "labels"
    feats = data / "features"

    label_rows = _load_glob(labels, "kalshi_settlement_labels-*.jsonl")
    feature_rows = [_event(r) for r in _load_glob(feats, "kalshi_feature_rows*.jsonl")]
    norm_ob = _load_glob(norm, "kalshi_orderbook-*.jsonl")
    raw_ob = _load_glob(raw, "kalshi_orderbook-*.jsonl")
    und = _load_glob(norm, "underlying_*.jsonl")

    # Markets seen, classified by phase from the latest snapshot per ticker.
    from ...timeutils import now_ms
    from .client import classify_market
    latest: dict[str, dict] = {}
    for row in _load_glob(raw, "kalshi_markets-*.jsonl"):
        payload = row.get("payload") if isinstance(row, dict) else None
        mk = payload if isinstance(payload, dict) else row
        tk = mk.get("ticker") if isinstance(mk, dict) else None
        if tk:
            latest[tk] = mk
    phases = Counter(classify_market(m, now_ms=now_ms()).value for m in latest.values())

    return assess_kalshi_readiness(
        label_rows=label_rows,
        feature_rows=feature_rows,
        normalized_orderbook_rows=len(norm_ob),
        raw_orderbook_rows=len(raw_ob),
        underlying_rows=len(und),
        markets_by_phase=dict(phases),
    )
