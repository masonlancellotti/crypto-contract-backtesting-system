# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXSOL15M-26JUN101530-30  joined snapshots: 2202
- writer mode: threaded  queue depth max/warn: 590/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/15/56
- recv->write ms p50/p95/max: 15.0/27/2925
- rotate_count: 12  compression_count: 12  flush_count: 3257  writer_errors: 0
- binance bookTicker/s: 176.4  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 1430 | 0 | 0 | 5272 |
| binance | 159308 | 0 | 0 | 4976 |
| kalshi | 21401 | 1 | 0 | 4914 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
