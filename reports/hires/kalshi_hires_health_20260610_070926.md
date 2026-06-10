# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100315-15  joined snapshots: 3981
- writer mode: threaded  queue depth max/warn: 1560/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/29/528
- recv->write ms p50/p95/max: 16/70/2306
- rotate_count: 11  compression_count: 11  flush_count: 3277  writer_errors: 0
- binance bookTicker/s: 286.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 3834 | 0 | 0 | 6545 |
| binance | 258475 | 0 | 0 | 6639 |
| kalshi | 121652 | 1 | 0 | 6644 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
