# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXETH15M-26JUN101545-45  joined snapshots: 3534
- writer mode: threaded  queue depth max/warn: 1074/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/22/109
- recv->write ms p50/p95/max: 16.0/34/2464
- rotate_count: 13  compression_count: 5  flush_count: 3344  writer_errors: 0
- binance bookTicker/s: 606.0  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6007 | 0 | 0 | 8778 |
| binance | 546905 | 0 | 0 | 9035 |
| kalshi | 84067 | 1 | 0 | 9010 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
