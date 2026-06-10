# Kalshi KXBTC15M high-res measurement — smoke (20s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN101200-00  joined snapshots: 85
- writer mode: threaded  queue depth max/warn: 878/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/10/23
- recv->write ms p50/p95/max: 14/23/2169
- rotate_count: 7  compression_count: 7  flush_count: 84  writer_errors: 0
- binance bookTicker/s: 1463.9  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 348 | 0 | 0 | 2471 |
| binance | 32496 | 0 | 0 | 2496 |
| kalshi | 7460 | 0 | 0 | 2536 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
