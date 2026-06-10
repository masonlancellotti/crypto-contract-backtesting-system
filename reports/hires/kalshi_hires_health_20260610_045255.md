# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100100-00  joined snapshots: 3761
- writer mode: threaded  queue depth max/warn: 1110/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2/18/462
- recv->write ms p50/p95/max: 15/31/2659
- rotate_count: 11  compression_count: 11  flush_count: 3348  writer_errors: 0
- binance bookTicker/s: 404.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5909 | 0 | 0 | 7562 |
| binance | 364835 | 0 | 0 | 8004 |
| kalshi | 139841 | 1 | 0 | 8003 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
