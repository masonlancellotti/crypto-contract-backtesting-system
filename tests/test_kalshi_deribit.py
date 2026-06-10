"""Deribit OPTIONAL auxiliary source — offline parser + config tests.

No network. Verifies the pure parsers/normalizer handle fixtures, that Deribit is
DISABLED by default, and that a disabled record-deribit command does not crash.
"""

from btc5m.config import load_config
from btc5m.data.deribit_client import (
    DeribitClient, normalize, parse_dvol, parse_historical_vol,
    parse_index_price, summarize_options,
)


def test_parsers_on_fixtures():
    assert parse_index_price({"result": {"index_price": 72012.5}}) == 72012.5
    dvol = {"result": {"data": [[1, 50, 51, 49, 55.5], [2, 55, 60, 54, 58.0]]}}
    assert parse_dvol(dvol) == 58.0
    hv = {"result": [[1, 40.0], [2, 42.5]]}
    assert parse_historical_vol(hv) == 42.5


def test_summarize_options_skew_and_oi():
    book = {"result": [
        {"instrument_name": "BTC-27JUN25-60000-C", "mark_iv": 50.0, "open_interest": 10, "volume": 5},
        {"instrument_name": "BTC-27JUN25-60000-P", "mark_iv": 60.0, "open_interest": 20, "volume": 7},
    ]}
    s = summarize_options(book)
    assert s["open_interest_total"] == 30
    assert s["volume_total"] == 12
    # put-call skew = mean put iv - mean call iv = 60 - 50 = 10
    assert abs(s["skew_proxy"] - 10.0) < 1e-9
    assert s["near_expiry_iv"] is not None


def test_normalize_combines_subpayloads():
    raw = {
        "currency": "BTC",
        "index": {"result": {"index_price": 72000.0}},
        "dvol": {"result": {"data": [[1, 50, 51, 49, 57.0]]}},
        "historical_vol": {"result": [[1, 41.0]]},
        "book_summary": {"result": [
            {"instrument_name": "BTC-27JUN25-60000-C", "mark_iv": 50.0, "open_interest": 10, "volume": 5},
            {"instrument_name": "BTC-27JUN25-60000-P", "mark_iv": 60.0, "open_interest": 20, "volume": 7},
        ]},
    }
    n = normalize(raw, recv_ms=1_000_000)
    assert n["source"] == "deribit"
    assert n["deribit_index_price"] == 72000.0
    assert n["deribit_btc_iv_index"] == 57.0
    assert n["deribit_historical_vol"] == 41.0
    assert n["deribit_options_open_interest_total"] == 30
    assert n["deribit_skew_proxy"] is not None


def test_empty_payloads_are_none_not_invented():
    n = normalize({"currency": "BTC"}, recv_ms=1)
    assert n["deribit_index_price"] is None
    assert n["deribit_btc_iv_index"] is None
    assert n["deribit_options_open_interest_total"] is None


def test_disabled_by_default():
    cfg = load_config(mode="paper")
    assert cfg.deribit.enabled is False
    client = DeribitClient(cfg)
    assert client.enabled is False
    # api_url normalized to the v2 base
    assert client.base.endswith("/api/v2")


def test_record_deribit_disabled_does_not_crash():
    from btc5m.cli import main
    # disabled -> prints blocker, returns 0, no exception
    assert main(["record-deribit", "--currency", "BTC", "--seconds", "0"]) == 0
