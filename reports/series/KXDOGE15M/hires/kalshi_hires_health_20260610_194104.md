# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXDOGE15M-26JUN101545-45  joined snapshots: 2208
- writer mode: threaded  queue depth max/warn: 256/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/13/38
- recv->write ms p50/p95/max: 14.0/26/2491
- rotate_count: 14  compression_count: 14  flush_count: 3192  writer_errors: 0
- binance bookTicker/s: 107.7  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/2

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 479 | 0 | 0 | 3719 |
| binance | 97170 | 0 | 0 | 3987 |
| kalshi | 21510 | 1 | 0 | 3987 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
