"""One authoritative gate: readiness and label-audit must agree (offline).

Reproduces the 38-vs-35 class of inconsistency: a window with feature rows but
NO usable executable row must count in feature_backed_official_windows (presence)
yet be EXCLUDED from the authoritative gate_windows (usable). Both readiness and
audit must report the same gate_windows.
"""

from btc5m.venues.kalshi.labels_audit import audit_labels
from btc5m.venues.kalshi.readiness import (
    assess_kalshi_readiness, feature_row_usable, usable_feature_tickers,
)


def _lrow(tk, status="OFFICIAL", yes=1):
    return {"market_ticker": tk, "label_source_status": status, "label_yes_resolved": yes}


def _usable(tk):
    return {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
            "has_start_reference": True, "seconds_to_close": 120, "book_ok": True,
            "reference_price": 100.0}


def _post_close(tk):  # feature row exists but window already closed -> NOT usable
    return {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
            "has_start_reference": False, "seconds_to_close": -5, "book_ok": True}


def _underlying_only(tk):  # BTC ref but no Kalshi book -> never executable
    return {"market_ticker": tk, "has_orderbook": False, "has_underlying": True,
            "has_start_reference": True, "seconds_to_close": 120, "book_ok": True,
            "reference_price": 100.0}


def test_feature_row_usable_predicate():
    assert feature_row_usable(_usable("A")) is True
    assert feature_row_usable(_post_close("A")) is False
    assert feature_row_usable(_underlying_only("A")) is False


def test_readiness_gate_excludes_unusable_feature_backed_window():
    labels = [_lrow("A"), _lrow("B")]
    feats = [_usable("A"), _post_close("B")]   # B has a feature row but none usable
    r = assess_kalshi_readiness(
        label_rows=labels, feature_rows=feats,
        normalized_orderbook_rows=2, raw_orderbook_rows=2, underlying_rows=10,
        markets_by_phase={"SETTLED": 2})
    assert r["feature_backed_official_windows"] == 2   # presence: A and B
    assert r["gate_windows"] == 1                       # usable: only A
    assert r["labeled_windows"] == r["gate_windows"]    # alias is consistent
    assert r["feature_backed_unusable_windows"] == 1    # B
    assert r["authoritative_gate_count"] == 1
    assert r["backtest_allowed"] is False


def test_audit_gate_matches_readiness_gate():
    labels = [_lrow("A"), _lrow("B")]
    feats = [_usable("A"), _post_close("B")]
    ftk = {r["market_ticker"] for r in feats}
    utk = usable_feature_tickers(feats)
    r = assess_kalshi_readiness(
        label_rows=labels, feature_rows=feats, normalized_orderbook_rows=2,
        raw_orderbook_rows=2, underlying_rows=10, markets_by_phase={"SETTLED": 2})
    a = audit_labels(labels, ftk, utk)
    assert a["gate_windows"] == r["gate_windows"] == 1
    assert a["backtest_gate_count"] == a["train_gate_count"] == 1
    assert a["official_feature_backed_labels"] == 2       # presence
    assert a["feature_backed_unusable_windows"] == 1


def test_orphan_official_label_excluded_from_gate():
    labels = [_lrow("A"), _lrow("C")]                  # C has no feature rows at all
    feats = [_usable("A")]
    ftk = {"A"}
    utk = usable_feature_tickers(feats)
    a = audit_labels(labels, ftk, utk)
    assert a["orphan_official_labels"] == 1            # C
    assert a["gate_windows"] == 1                       # only A
    r = assess_kalshi_readiness(
        label_rows=labels, feature_rows=feats, normalized_orderbook_rows=1,
        raw_orderbook_rows=1, underlying_rows=1, markets_by_phase={"SETTLED": 2})
    assert r["orphan_official_labels"] == 1
    assert r["gate_windows"] == 1


def test_underlying_only_rows_never_usable():
    feats = [_underlying_only("A"), _underlying_only("B")]
    r = assess_kalshi_readiness(
        label_rows=[_lrow("A"), _lrow("B")], feature_rows=feats,
        normalized_orderbook_rows=0, raw_orderbook_rows=0, underlying_rows=2,
        markets_by_phase={"SETTLED": 2})
    assert r["feature_rows_underlying_only"] == 2
    assert r["gate_windows"] == 0                       # no executable examples
    assert r["usable_rows_for_backtest"] == 0
