"""Data-readiness assessment — gates training and backtesting.

Training and backtesting stay BLOCKED until there are enough non-leaky, usable,
OFFICIALLY-labeled rows. This avoids fitting/evaluating on a handful of sparse,
provisional, or look-ahead-prone samples.

A *usable* feature row is point-in-time and quality-passing: it has a known line,
a reference price, healthy feeds, and is not past expiry. A *usable labeled* row
additionally has an OFFICIAL settlement label for its window (a settlement-grade
target). Even when counts are high, the backtester must apply purge/embargo
because overlapping 5-minute windows share information.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

# Conservative defaults — kept high so training stays blocked on sparse data.
DEFAULT_MIN_TRAIN_ROWS = 500
DEFAULT_MIN_BACKTEST_ROWS = 200


_STATUS_RANK = {"OFFICIAL": 3, "MANUAL_REVIEW": 2, "PROVISIONAL_REFERENCE": 1, "UNKNOWN": 0}


def dedupe_label_rows(label_rows: list[dict]) -> list[dict]:
    """One label row per slug. Labels are append-only, so prefer the highest-
    grade status (OFFICIAL > MANUAL_REVIEW > PROVISIONAL > UNKNOWN), then latest.
    """
    best: dict[str, dict] = {}
    for lr in label_rows:
        slug = lr.get("slug")
        if slug is None:
            continue
        cur = best.get(slug)
        if cur is None:
            best[slug] = lr
            continue
        rank_new = _STATUS_RANK.get(lr.get("label_source_status"), 0)
        rank_cur = _STATUS_RANK.get(cur.get("label_source_status"), 0)
        if rank_new > rank_cur or (
            rank_new == rank_cur
            and (lr.get("created_at_ms") or 0) >= (cur.get("created_at_ms") or 0)
        ):
            best[slug] = lr
    return list(best.values())


def _is_usable(row: dict) -> tuple[bool, Optional[str]]:
    if not row.get("line_known"):
        return False, "no_line"
    if row.get("reference_price") is None:
        return False, "no_reference_price"
    if not row.get("feed_health_ok"):
        return False, "stale_or_bad_feed"
    secs = row.get("seconds_to_expiry")
    if secs is None or secs <= 0:
        return False, "expired_or_no_expiry"
    return True, None


def _has_polymarket_book(row: dict) -> bool:
    return row.get("yes_bid") is not None or row.get("yes_ask") is not None


def _has_underlying(row: dict) -> bool:
    return row.get("reference_price") is not None


def _not_expired(row: dict) -> bool:
    secs = row.get("seconds_to_expiry")
    return secs is not None and secs > 0


def _usable_non_line(row: dict) -> bool:
    """Row usable for a model that does NOT need the numeric line (binary-only):
    a live Polymarket book + an underlying reference + healthy feeds, not expired."""
    return (
        _has_polymarket_book(row)
        and _has_underlying(row)
        and bool(row.get("feed_health_ok"))
        and _not_expired(row)
    )


def _usable_microstructure(row: dict) -> bool:
    """Row usable for a microstructure model: a non-crossed Polymarket book with
    healthy feeds, not expired (line optional)."""
    return (
        _has_polymarket_book(row)
        and not bool(row.get("crossed_yes_book"))
        and bool(row.get("feed_health_ok"))
        and _not_expired(row)
    )


def assess_readiness(
    feature_rows: list[dict],
    label_rows: list[dict],
    *,
    min_train_rows: int = DEFAULT_MIN_TRAIN_ROWS,
    min_backtest_rows: int = DEFAULT_MIN_BACKTEST_ROWS,
) -> dict:
    """Compute a readiness report from feature + label rows (pure)."""
    label_rows = dedupe_label_rows(label_rows)  # one per slug (append-only safe)
    # A market has a usable OFFICIAL binary label whenever the binary outcome is
    # known — even if the numeric line is missing (line-free models can train on
    # it). MANUAL_REVIEW keeps a computed label too but is held out of training.
    official_by_slug: dict[str, int] = {}
    completed = len(label_rows)
    official_labels = provisional_labels = manual_review = 0
    official_numeric_lines = provisional_numeric_lines = provisional_final_prices = 0
    for lr in label_rows:
        status = lr.get("label_source_status")
        if lr.get("official_outcome") is not None and status in ("OFFICIAL", "MANUAL_REVIEW"):
            # Binary outcome is settlement-grade regardless of numeric line state.
            if status == "OFFICIAL":
                official_labels += 1
                if lr.get("slug") is not None:
                    official_by_slug[lr["slug"]] = lr["official_outcome"]
        if status == "PROVISIONAL_REFERENCE":
            provisional_labels += 1
        elif status == "MANUAL_REVIEW":
            manual_review += 1
        # Numeric line / final-price provenance (independent of the binary label).
        if lr.get("line_source_status") == "OFFICIAL":
            official_numeric_lines += 1
        elif lr.get("line_source_status") == "PROVISIONAL_REFERENCE":
            provisional_numeric_lines += 1
        if lr.get("final_reference_source_status") == "PROVISIONAL_REFERENCE":
            provisional_final_prices += 1

    missing = Counter()
    usable = 0          # usable for a LINE-dependent model (needs the numeric line)
    usable_labeled = 0  # + OFFICIAL binary label
    rows_with_line = rows_without_line = 0
    rows_with_book = rows_with_underlying = 0
    usable_non_line = usable_micro = 0
    usable_labeled_non_line = 0
    for row in feature_rows:
        if row.get("line_known"):
            rows_with_line += 1
        else:
            rows_without_line += 1
        if _has_polymarket_book(row):
            rows_with_book += 1
        if _has_underlying(row):
            rows_with_underlying += 1

        ok, why = _is_usable(row)
        if ok:
            usable += 1
            if row.get("slug") in official_by_slug:
                usable_labeled += 1
        else:
            missing[why] += 1

        if _usable_non_line(row):
            usable_non_line += 1
            if row.get("slug") in official_by_slug:
                usable_labeled_non_line += 1
        if _usable_microstructure(row):
            usable_micro += 1

    training_allowed = usable_labeled >= min_train_rows               # line model
    training_allowed_binary_only = usable_labeled_non_line >= min_train_rows
    backtest_allowed = usable_labeled >= min_backtest_rows

    reasons_training_blocked: list[str] = []
    if not training_allowed:
        reasons_training_blocked.append(
            f"line model: usable_labeled_rows(with line)={usable_labeled} < {min_train_rows}"
        )
    if not training_allowed_binary_only:
        reasons_training_blocked.append(
            f"binary-only model: usable_labeled_non_line_rows={usable_labeled_non_line} < {min_train_rows}"
        )
    if official_labels == 0:
        reasons_training_blocked.append("no OFFICIAL settlement labels yet (run backfill-settlements)")
    reasons_backtest_blocked: list[str] = []
    if not backtest_allowed:
        reasons_backtest_blocked.append(
            f"usable_labeled_rows(with line)={usable_labeled} < {min_backtest_rows}"
        )

    blockers = []
    if not training_allowed:
        blockers.append(f"training blocked: usable_labeled_rows={usable_labeled} < {min_train_rows}")
    if not backtest_allowed:
        blockers.append(f"backtest blocked: usable_labeled_rows={usable_labeled} < {min_backtest_rows}")
    if official_labels == 0:
        blockers.append("no OFFICIAL settlement labels yet (run backfill-settlements)")

    return {
        # ---- existing keys (kept stable for CLI/pipeline/backtest) ----
        "completed_windows": completed,
        "official_labels": official_labels,
        "provisional_labels": provisional_labels,
        "manual_review": manual_review,
        "feature_rows": len(feature_rows),
        "usable_rows": usable,
        "usable_labeled_rows": usable_labeled,
        "missing_fields": dict(missing),
        "min_train_rows": min_train_rows,
        "min_backtest_rows": min_backtest_rows,
        "training_allowed": training_allowed,
        "backtest_allowed": backtest_allowed,
        "note": "Overlapping 5m windows require purge/embargo even when allowed.",
        "blockers": blockers,
        # ---- richer breakdown (provenance + model-specific usability) ----
        "total_markets_seen": completed,
        "official_binary_labels": official_labels,
        "official_numeric_lines": official_numeric_lines,
        "provisional_numeric_lines": provisional_numeric_lines,
        "provisional_final_prices": provisional_final_prices,
        "manual_review_rows": manual_review,
        "feature_rows_total": len(feature_rows),
        "feature_rows_with_line": rows_with_line,
        "feature_rows_without_line": rows_without_line,
        "feature_rows_with_polymarket_book": rows_with_book,
        "feature_rows_with_underlying": rows_with_underlying,
        "usable_rows_for_baseline_line_model": usable,
        "usable_rows_for_non_line_model": usable_non_line,
        "usable_rows_for_microstructure_model": usable_micro,
        "usable_labeled_rows_non_line": usable_labeled_non_line,
        "training_allowed_binary_only": training_allowed_binary_only,
        "training_allowed_line_model": training_allowed,
        "reasons_training_blocked": reasons_training_blocked,
        "reasons_backtest_blocked": reasons_backtest_blocked,
    }


def load_readiness(config, *, asset: str = "BTC", duration: str = "5m") -> dict:
    """Load feature + label rows from disk and assess readiness."""
    from ..features.feature_store import FeatureStore
    from ..labels.settlement_backfill import load_label_rows

    feature_rows = FeatureStore(config).load()
    label_rows = load_label_rows(config.data_path() / "labels")
    prefix = f"{asset.strip().lower()}-updown-{duration.strip().lower()}-"
    feature_rows = [r for r in feature_rows if (r.get("slug") or "").startswith(prefix)]
    label_rows = [r for r in label_rows if (r.get("slug") or "").startswith(prefix)]
    return assess_readiness(feature_rows, label_rows)
