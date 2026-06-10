"""Multi-asset (ETH/SOL/DOGE/XRP) expansion checks.

All five Kalshi crypto 15m series verified live 2026-06-10: KXBTC15M, KXETH15M,
KXSOL15M, KXDOGE15M, KXXRP15M — same Target Price sub-title, GTE comparison,
and per-asset CF Benchmarks RTI reference. These tests pin the series→underlying
symbol mapping and the settlement parsing on representative non-BTC payloads.
Offline.
"""

from btc5m.data.underlying import (
    SERIES_UNDERLYING_SYMBOLS, build_underlying_client, underlying_symbols_for_series,
)
from btc5m.venues.kalshi.settlement import comparison_from_rules, parse_target_price


def test_series_symbol_map_covers_all_five():
    assert set(SERIES_UNDERLYING_SYMBOLS) == {
        "KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"}
    assert underlying_symbols_for_series("KXSOL15M") == {
        "coinbase": "SOL-USD", "binance": "SOLUSDT"}
    # unknown/legacy defaults to BTC (never crashes)
    assert underlying_symbols_for_series(None)["coinbase"] == "BTC-USD"
    assert underlying_symbols_for_series("KXWHAT")["coinbase"] == "BTC-USD"


def test_build_underlying_client_uses_series_symbols():
    cb = build_underlying_client("coinbase", None, series="KXDOGE15M")
    bn = build_underlying_client("binance", None, series="KXXRP15M")
    assert cb.symbol == "DOGE-USD"
    assert bn.symbol == "XRPUSDT"
    # default stays BTC
    assert build_underlying_client("coinbase", None).symbol == "BTC-USD"


def test_target_price_parses_subdollar_and_thousands():
    # live shapes observed 2026-06-10 for ETH / SOL / DOGE / XRP
    assert parse_target_price("Target Price: $1,655.99") == 1655.99
    assert parse_target_price("Target Price: $65.3523") == 65.3523
    assert parse_target_price("Target Price: $0.0850325") == 0.0850325
    assert parse_target_price("Target Price: $1.1273") == 1.1273


def test_comparison_parses_for_non_btc_rti_rules():
    rules = ("If the simple average of the sixty seconds of CF Benchmarks' DOGEUSDRTI "
             "before 12:15 PM EDT on Jun 10, 2026 is at least the simple average of the "
             "sixty seconds of CF Benchmarks' DOGEUSDRTI before 12:00 PM EDT on June 10, "
             "2026, then the market resolves to Yes.")
    assert comparison_from_rules(rules) is not None
