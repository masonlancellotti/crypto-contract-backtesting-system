# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100145-45  joined snapshots: 4058
- writer mode: threaded  queue depth max/warn: 1160/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/19/143
- recv->write ms p50/p95/max: 15.0/34/2220
- rotate_count: 11  compression_count: 11  flush_count: 3363  writer_errors: 0
- binance bookTicker/s: 349.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5440 | 0 | 0 | 8058 |
| binance | 315059 | 0 | 0 | 8061 |
| kalshi | 194361 | 1 | 0 | 8062 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
