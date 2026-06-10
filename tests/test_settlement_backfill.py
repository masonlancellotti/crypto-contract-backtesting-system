"""Offline tests for the settlement backfill (pure logic + file helpers)."""

import json

from btc5m.labels.settlement_backfill import (
    LabelSourceStatus,
    build_label_row,
    load_recorded_markets,
    official_outcome_from_market,
    write_label_rows,
)
from btc5m.schemas import Comparison, ContractMeta, MarketType


def _meta():
    return ContractMeta(
        contract_id="cond1",
        title="Bitcoin Up or Down",
        asset="BTC",
        line=None,
        expiry_ms=1_300_000,
        market_id="mid1",
        condition_id="cond1",
        slug="btc-updown-5m-1000",
        market_type=MarketType.UP_DOWN,
        comparison=Comparison.GTE,
        window_start_ms=1_000_000,
    )


# ----- official outcome extraction -----------------------------------------
def test_official_outcome_up_resolved():
    m = {"closed": True, "outcomes": '["Up","Down"]', "outcomePrices": '["1","0"]'}
    assert official_outcome_from_market(m) == 1


def test_official_outcome_down_resolved():
    m = {"closed": True, "outcomes": '["Up","Down"]', "outcomePrices": '["0","1"]'}
    assert official_outcome_from_market(m) == 0


def test_official_outcome_none_when_not_closed():
    m = {"closed": False, "outcomes": '["Up","Down"]', "outcomePrices": '["0.4","0.6"]'}
    assert official_outcome_from_market(m) is None


def test_official_outcome_none_when_ambiguous():
    m = {"closed": True, "outcomes": '["Up","Down"]', "outcomePrices": '["0.5","0.5"]'}
    assert official_outcome_from_market(m) is None


# ----- build_label_row matrix ----------------------------------------------
def test_official_and_computed_agree():
    row = build_label_row(_meta(), line_price=60000.0, final_reference_price=60010.0, official_yes=1)
    assert row.label_source_status == LabelSourceStatus.OFFICIAL.value
    assert row.label_yes_resolved == 1
    assert row.official_outcome == 1
    assert row.reason_code == "OK"
    assert row.settlement_distance == 10.0


def test_official_and_computed_disagree_is_manual_review():
    # GTE: final < line -> computed 0; official says 1 -> disagreement
    row = build_label_row(_meta(), line_price=60000.0, final_reference_price=59990.0, official_yes=1)
    assert row.label_source_status == LabelSourceStatus.MANUAL_REVIEW.value
    assert row.label_yes_resolved == 0       # computed kept
    assert row.official_outcome == 1         # official kept, not silently overwritten
    assert "DISAGREEMENT" in row.detail


def test_official_only_when_line_missing():
    row = build_label_row(_meta(), line_price=None, final_reference_price=60010.0, official_yes=1)
    assert row.label_source_status == LabelSourceStatus.OFFICIAL.value
    assert row.label_yes_resolved == 1
    assert row.reason_code == "MISSING_LINE"


def test_provisional_only_when_no_official():
    row = build_label_row(_meta(), line_price=60000.0, final_reference_price=60010.0, official_yes=None)
    assert row.label_source_status == LabelSourceStatus.PROVISIONAL_REFERENCE.value
    assert row.label_yes_resolved == 1
    assert row.official_outcome is None


def test_unknown_when_nothing_available():
    row = build_label_row(_meta(), line_price=None, final_reference_price=None, official_yes=None)
    assert row.label_source_status == LabelSourceStatus.UNKNOWN.value
    assert row.label_yes_resolved is None
    assert row.reason_code in ("MISSING_LINE", "MISSING_SETTLEMENT_PRICE")


def test_missing_final_price_with_official():
    row = build_label_row(_meta(), line_price=60000.0, final_reference_price=None, official_yes=0)
    assert row.label_source_status == LabelSourceStatus.OFFICIAL.value
    assert row.label_yes_resolved == 0
    assert row.reason_code == "MISSING_SETTLEMENT_PRICE"


# ----- file helpers ---------------------------------------------------------
def test_load_recorded_markets(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    f = raw / "polymarket_markets-20260531.jsonl"
    rows = [
        {"stream": "polymarket_markets", "payload": {"slug": "btc-updown-5m-1", "closed": False}},
        {"stream": "polymarket_markets", "payload": {"slug": "eth-updown-5m-1", "closed": False}},
        {"stream": "polymarket_markets", "payload": {"slug": "btc-updown-5m-1", "closed": True}},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded = load_recorded_markets(raw, slug_prefix="btc-updown-5m-")
    assert set(loaded) == {"btc-updown-5m-1"}
    assert loaded["btc-updown-5m-1"]["closed"] is True  # latest wins


def test_write_label_rows(tmp_path):
    row = build_label_row(_meta(), line_price=60000.0, final_reference_price=60010.0, official_yes=1)
    path = tmp_path / "labels" / "settlement_labels-20260531.jsonl"
    n = write_label_rows(path, [row])
    assert n == 1
    data = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert data[0]["slug"] == "btc-updown-5m-1000"
    assert data[0]["label_source_status"] == "OFFICIAL"
