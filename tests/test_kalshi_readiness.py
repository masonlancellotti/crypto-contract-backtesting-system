"""Kalshi data-readiness categories + distinct-window gating (offline)."""

from btc5m.venues.kalshi.readiness import assess_kalshi_readiness


def _lrow(tk, status, yes):
    return {"market_ticker": tk, "label_source_status": status, "label_yes_resolved": yes}


def _frow(tk, *, ob, und, start, secs, book_ok=True, ref=None):
    return {"market_ticker": tk, "has_orderbook": ob, "has_underlying": und,
            "has_start_reference": start, "seconds_to_close": secs, "book_ok": book_ok,
            "reference_price": ref}


def _report():
    labels = [
        _lrow("A", "OFFICIAL", 1),                 # official, even if no numeric ref
        _lrow("B", "PROVISIONAL_REFERENCE", 1),
        _lrow("C", "UNKNOWN", None),
        _lrow("D", "MANUAL_REVIEW", 0),
    ]
    feats = [
        _frow("A", ob=True, und=True, start=True, secs=120, ref=100.0),   # usable binary+line+backtest
        _frow("B", ob=True, und=True, start=False, secs=120),             # usable binary, not line, not labeled
        _frow("Z", ob=False, und=True, start=True, secs=120),             # no book -> not usable
    ]
    return assess_kalshi_readiness(
        label_rows=labels, feature_rows=feats,
        normalized_orderbook_rows=3, raw_orderbook_rows=3, underlying_rows=10,
        markets_by_phase={"CURRENT_IN_WINDOW": 1, "UPCOMING": 2, "SETTLED": 4},
    )


def test_label_categories_and_official_survives_missing_ref():
    r = _report()
    assert r["official_binary_labels"] == 1          # A counts despite no numeric ref
    assert r["provisional_reference_rows"] == 1       # B
    assert r["unknown_label_rows"] == 1               # C
    assert r["manual_review_rows"] == 1               # D
    assert r["distinct_settled_windows"] == 1


def test_feature_and_usable_categories():
    r = _report()
    assert r["feature_rows_with_orderbook"] == 2      # A, B
    assert r["feature_rows_with_underlying"] == 3
    assert r["feature_rows_with_start_reference"] == 2  # A, Z
    assert r["usable_rows_for_binary_model"] == 2     # A, B
    assert r["usable_rows_for_line_distance_model"] == 1  # A (has start + ref)
    assert r["usable_rows_for_backtest"] == 1         # A (labeled official)
    assert r["labeled_windows"] == 1


def test_gates_block_on_distinct_windows():
    r = _report()
    # Only 1 distinct settled window -> far below 150/60 thresholds.
    assert r["training_allowed_binary_model"] is False
    assert r["backtest_allowed"] is False
    assert r["reasons_training_blocked"]
    assert any("distinct" in s for s in r["reasons_training_blocked"])
    assert r["recommended_next_command"]


def test_missing_official_blocks_official_training_but_keeps_provisional():
    r = assess_kalshi_readiness(
        label_rows=[_lrow("B", "PROVISIONAL_REFERENCE", 1)],
        feature_rows=[_frow("B", ob=True, und=True, start=True, secs=120, ref=1.0)],
        normalized_orderbook_rows=1, raw_orderbook_rows=1, underlying_rows=1,
        markets_by_phase={"SETTLED": 1},
    )
    assert r["official_binary_labels"] == 0
    assert r["provisional_reference_rows"] == 1
    assert r["training_allowed_binary_model"] is False
    assert any("OFFICIAL" in s or "official" in s for s in r["reasons_training_blocked"])
