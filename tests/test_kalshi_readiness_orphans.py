"""Readiness orphan-label accounting + settlement reference provenance (offline).

Orphan official labels (no feature rows) must be surfaced and excluded from the
feature-backed gate counts; the gate must never unlock from raw label count.
Settlement rows must record the comparison rule + reference source from the rule
text (CF Benchmarks BRTI, never Chainlink/title).
"""

from btc5m.venues.kalshi.readiness import assess_kalshi_readiness
from btc5m.venues.kalshi.settlement import build_label_row, reference_source_from_rules


def _lrow(tk, status="OFFICIAL", yes=1):
    return {"market_ticker": tk, "label_source_status": status, "label_yes_resolved": yes}


def _frow(tk, *, ob=True, und=True, start=True, secs=120, book_ok=True, ref=100.0):
    return {"market_ticker": tk, "has_orderbook": ob, "has_underlying": und,
            "has_start_reference": start, "seconds_to_close": secs, "book_ok": book_ok,
            "reference_price": ref}


def test_orphan_official_labels_excluded_from_gate():
    labels = [_lrow("A"), _lrow("B")]      # both OFFICIAL
    feats = [_frow("A")]                    # only A has features -> B is orphan
    r = assess_kalshi_readiness(
        label_rows=labels, feature_rows=feats,
        normalized_orderbook_rows=1, raw_orderbook_rows=1, underlying_rows=5,
        markets_by_phase={"SETTLED": 2})
    assert r["official_binary_labels"] == 2
    assert r["feature_backed_official_windows"] == 1
    assert r["orphan_official_labels"] == 1
    assert r["orphan_labels"] == 1
    # gate counts feature-backed windows only -> blocked
    assert r["backtest_allowed"] is False
    assert r["labeled_windows"] == 1


def test_raw_label_count_does_not_unlock_gate():
    # 100 OFFICIAL labels but zero feature rows -> all orphan -> still blocked.
    labels = [_lrow(f"T{i}") for i in range(100)]
    r = assess_kalshi_readiness(
        label_rows=labels, feature_rows=[],
        normalized_orderbook_rows=0, raw_orderbook_rows=0, underlying_rows=0,
        markets_by_phase={"SETTLED": 100})
    assert r["official_binary_labels"] == 100
    assert r["feature_backed_official_windows"] == 0
    assert r["orphan_official_labels"] == 100
    assert r["backtest_allowed"] is False
    assert r["training_allowed_binary_model"] is False


def test_rejection_reason_counts():
    feats = [
        _frow("A", ob=True, und=True),               # usable
        _frow("B", ob=False, und=True),              # missing book
        _frow("C", ob=True, und=True, secs=-5),      # window closed
    ]
    r = assess_kalshi_readiness(
        label_rows=[_lrow("A")], feature_rows=feats,
        normalized_orderbook_rows=3, raw_orderbook_rows=3, underlying_rows=3,
        markets_by_phase={"SETTLED": 1})
    assert r["rows_rejected_missing_book"] == 1
    assert r["rows_rejected_window_closed_or_bad_book"] == 1


def test_settlement_reference_source_from_rules():
    assert "BRTI" in (reference_source_from_rules(
        "If the simple average of the sixty seconds of CF Benchmarks' BRTI ...") or "")
    assert reference_source_from_rules("ambiguous") is None
    row = build_label_row({
        "ticker": "KXBTC15M-X-45", "status": "finalized", "result": "yes",
        "open_time": "2026-06-01T07:30:00Z", "close_time": "2026-06-01T07:45:00Z",
        "yes_sub_title": "Target Price: $100.00",
        "rules_primary": "If the simple average ... CF Benchmarks' BRTI ... is at least ...",
    })
    assert row["comparison_semantics"] == "GTE"
    assert "BRTI" in (row["settlement_reference_source"] or "")
    assert row["rules_excerpt"]
