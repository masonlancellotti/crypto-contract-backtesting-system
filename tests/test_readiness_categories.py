"""Readiness category breakdown (pure assess_readiness).

Locks in the Phase-6 guarantees: official binary labels survive a missing
numeric line; official vs provisional numeric lines are counted separately;
model-specific usable-row counts are distinct (line / non-line / microstructure).
"""

from btc5m.paper.readiness import assess_readiness


def _frow(slug, *, line, ref, healthy, secs, bid, crossed=False):
    return {
        "slug": slug,
        "line_known": line,
        "reference_price": ref,
        "feed_health_ok": healthy,
        "seconds_to_expiry": secs,
        "yes_bid": bid,
        "crossed_yes_book": crossed,
    }


def _lrow(slug, *, official, status, line_status="UNKNOWN", final_status="UNKNOWN"):
    return {
        "slug": slug,
        "official_outcome": official,
        "label_source_status": status,
        "line_source_status": line_status,
        "final_reference_source_status": final_status,
    }


def _report():
    feature_rows = [
        _frow("s1", line=True, ref=100.0, healthy=True, secs=100, bid=0.5),    # A: usable everywhere
        _frow("s1", line=False, ref=100.0, healthy=True, secs=100, bid=0.5),   # B: non-line + micro
        _frow("s9", line=True, ref=None, healthy=True, secs=100, bid=None),    # C: no ref/book
        _frow("s9", line=False, ref=100.0, healthy=False, secs=100, bid=0.5),  # D: unhealthy
    ]
    label_rows = [
        # Official binary outcome but NO numeric line -> must still count.
        _lrow("s1", official=1, status="OFFICIAL", line_status="UNKNOWN"),
        # Disagreement -> MANUAL_REVIEW, provisional numeric line + final price.
        _lrow("s2", official=0, status="MANUAL_REVIEW",
              line_status="PROVISIONAL_REFERENCE", final_status="PROVISIONAL_REFERENCE"),
        # Provisional-only (no official outcome).
        _lrow("s3", official=None, status="PROVISIONAL_REFERENCE",
              line_status="PROVISIONAL_REFERENCE"),
        # Official outcome AND official numeric line.
        _lrow("s4", official=1, status="OFFICIAL", line_status="OFFICIAL"),
    ]
    return assess_readiness(feature_rows, label_rows, min_train_rows=1, min_backtest_rows=1)


def test_official_binary_label_survives_missing_line():
    r = _report()
    # s1 has an OFFICIAL binary outcome with NO numeric line, and s4 has both.
    assert r["official_binary_labels"] == 2
    assert r["official_labels"] == 2  # legacy alias unchanged


def test_numeric_line_provenance_counts():
    r = _report()
    assert r["official_numeric_lines"] == 1          # s4
    assert r["provisional_numeric_lines"] == 2        # s2, s3
    assert r["provisional_final_prices"] == 1         # s2
    assert r["manual_review_rows"] == 1               # s2


def test_feature_row_breakdown():
    r = _report()
    assert r["feature_rows_total"] == 4
    assert r["feature_rows_with_line"] == 2           # A, C
    assert r["feature_rows_without_line"] == 2        # B, D
    assert r["feature_rows_with_polymarket_book"] == 3  # A, B, D
    assert r["feature_rows_with_underlying"] == 3       # A, B, D


def test_model_specific_usable_rows_are_distinct():
    r = _report()
    assert r["usable_rows_for_baseline_line_model"] == 1   # A only (needs line)
    assert r["usable_rows_for_non_line_model"] == 2        # A, B (no line needed)
    assert r["usable_rows_for_microstructure_model"] == 2  # A, B
    assert r["usable_labeled_rows"] == 1                   # A (s1 official)
    assert r["usable_labeled_rows_non_line"] == 2          # A, B (s1 official)


def test_gates_and_reasons():
    r = _report()
    assert r["training_allowed_line_model"] is True
    assert r["training_allowed_binary_only"] is True
    assert r["backtest_allowed"] is True
    # With higher thresholds everything blocks with explicit reasons.
    blocked = assess_readiness(
        [_frow("s1", line=True, ref=100.0, healthy=True, secs=100, bid=0.5)],
        [_lrow("s1", official=1, status="OFFICIAL")],
        min_train_rows=500, min_backtest_rows=200,
    )
    assert blocked["training_allowed_line_model"] is False
    assert blocked["reasons_training_blocked"]
    assert blocked["reasons_backtest_blocked"]
