"""Kalshi venue — PRIMARY.

Kalshi BTC 15-minute Up/Down markets (series ``KXBTC15M``). Public market-data
REST works without credentials; authenticated WS / account / live trading is
optional and env-gated. Settlement is taken from Kalshi's OFFICIAL ``result``
field — never inferred from a BTC proxy or from Polymarket/Chainlink logic.

VERIFIED live (2026-06-01) against https://external-api.kalshi.com/trade-api/v2:
- series KXBTC15M exists (category Crypto, contract terms CRYPTO15M.pdf)
- markets: ticker ``KXBTC15M-<YYMONDD><HHMM>-<MM>``, 15-min window [open_time, close_time]
- title "BTC price up in next 15 mins?"; yes_sub_title carries the start "Target Price"
- rules: YES if 60s-avg CF Benchmarks BRTI at close >= at open (GTE; BRTI, not Chainlink)
- orderbook returns orderbook_fp.{yes_dollars,no_dollars} = ascending [price,size] bid arrays
- executable asks (== Kalshi's own): yes_ask = 1 - best_no_bid; no_ask = 1 - best_yes_bid
"""

SCHEMA_VERSION = 1
SERIES_TICKER = "KXBTC15M"
WINDOW_SECONDS = 15 * 60
