"""Kalshi fee model + settlement/labeling (offline)."""

from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.settlement import (
    build_label_row,
    comparison_from_rules,
    official_result,
    parse_target_price,
)


# ---- fees ---------------------------------------------------------------- #
def test_fee_formula_and_rounding():
    fm = KalshiFeeModel(rate=0.07, status="ASSUMED")
    # 0.07 * 10 * 0.5 * 0.5 = 0.175 -> round UP to cent -> 0.18
    assert fm.taker_fee(0.5, 10) == 0.18
    assert fm.status == "ASSUMED"
    assert fm.taker_fee(0.0, 10) == 0.0      # degenerate price
    assert fm.taker_fee(0.5, 0) == 0.0       # no contracts


def test_fee_unknown_is_conservative():
    assumed = KalshiFeeModel(rate=0.07, status="ASSUMED").taker_fee(0.5, 100)
    unknown = KalshiFeeModel(rate=0.07, status="UNKNOWN").taker_fee(0.5, 100)
    assert unknown >= assumed  # UNKNOWN must never understate cost


def test_fee_subtracted_from_edge():
    from btc5m.venues.kalshi.paper import decide_kalshi
    fm = KalshiFeeModel(rate=0.07, status="ASSUMED")
    row = {"yes_ask": 0.50, "no_ask": 0.50, "book_ok": True, "seconds_to_close": 120,
           "quote_age_ms": 100, "yes_ask_size": 500, "no_ask_size": 500, "thin_book": False}
    # model says YES prob 0.56 -> gross edge 6c, fee reduces net edge below gross
    dec = decide_kalshi(row, model_p_yes=0.56, calibrated=True, fee_model=fm,
                        min_net_edge_cents=2.0)
    assert dec["fee_estimate"] is not None and dec["fee_estimate"] > 0
    assert dec["net_edge_cents"] < 6.0  # fees subtracted


# ---- settlement ---------------------------------------------------------- #
def test_parse_target_price():
    assert parse_target_price("Target Price: $72,901.10") == 72901.10
    assert parse_target_price("Target price: TBD") is None
    assert parse_target_price(None) is None


def test_comparison_from_rules():
    assert comparison_from_rules("... is at least the simple average ...") == "GTE"
    assert comparison_from_rules("... strictly greater than ...") == "GT"
    assert comparison_from_rules("ambiguous wording") == "UNKNOWN"


def test_official_result_only_when_settled():
    assert official_result({"status": "finalized", "result": "yes"}) == "yes"
    assert official_result({"status": "active", "result": ""}) is None
    # an active market must NOT be treated as settled even with a stray result
    assert official_result({"status": "active", "result": "yes"}) is None


def _market(**kw):
    base = {"ticker": "KXBTC15M-X-45", "event_ticker": "KXBTC15M-X",
            "open_time": "2026-06-01T07:30:00Z", "close_time": "2026-06-01T07:45:00Z",
            "yes_sub_title": "Target Price: $100.00",
            "rules_primary": "... is at least the simple average ..."}
    base.update(kw)
    return base


def test_label_official_when_finalized():
    row = build_label_row(_market(status="finalized", result="yes"))
    assert row["label_source_status"] == "OFFICIAL"
    assert row["label_yes_resolved"] == 1
    assert row["reason_code"] == "OK"
    assert row["comparison_semantics"] == "GTE"


def test_label_unknown_when_active_no_refs():
    row = build_label_row(_market(status="active", result=""))
    assert row["label_source_status"] == "UNKNOWN"
    assert row["label_yes_resolved"] is None
    assert row["reason_code"] in ("MISSING_END_REFERENCE", "NO_OFFICIAL_RESULT")


def test_proxy_reference_is_provisional_not_official():
    # No official result, but a BTC end-ref allows a computed guess -> PROVISIONAL.
    row = build_label_row(_market(status="active", result=""),
                          reference_end_price=101.0, reference_source="coinbase:BTC-USD")
    assert row["label_source_status"] == "PROVISIONAL_REFERENCE"
    assert row["label_yes_resolved"] == 1  # 101 >= 100 (GTE)
    assert row["official_result"] is None


def test_official_vs_provisional_disagreement_is_manual_review():
    # Official says NO, but proxy (end 101 >= start 100) computes YES -> MANUAL_REVIEW.
    row = build_label_row(_market(status="finalized", result="no"),
                          reference_end_price=101.0, reference_source="coinbase:BTC-USD")
    assert row["label_source_status"] == "MANUAL_REVIEW"
    assert row["label_yes_resolved"] == 0  # keeps the OFFICIAL outcome
    assert row["reason_code"] == "OFFICIAL_VS_PROVISIONAL_DISAGREE"
