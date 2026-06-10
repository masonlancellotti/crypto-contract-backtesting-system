# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXSOL15M-26JUN101545-45  joined snapshots: 2370
- writer mode: threaded  queue depth max/warn: 674/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/16/55
- recv->write ms p50/p95/max: 15.0/29/2997
- rotate_count: 11  compression_count: 11  flush_count: 3270  writer_errors: 0
- binance bookTicker/s: 210.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 1939 | 0 | 0 | 5657 |
| binance | 189861 | 0 | 0 | 5434 |
| kalshi | 28594 | 1 | 0 | 5375 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
