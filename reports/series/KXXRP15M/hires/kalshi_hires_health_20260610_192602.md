# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXXRP15M-26JUN101530-30  joined snapshots: 2374
- writer mode: threaded  queue depth max/warn: 410/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/18/132
- recv->write ms p50/p95/max: 14.0/32/3189
- rotate_count: 11  compression_count: 11  flush_count: 3234  writer_errors: 0
- binance bookTicker/s: 124.4  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 3625 | 0 | 0 | 4922 |
| binance | 112398 | 0 | 0 | 4875 |
| kalshi | 26699 | 1 | 0 | 4889 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
