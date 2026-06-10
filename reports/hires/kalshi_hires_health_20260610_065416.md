# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100300-00  joined snapshots: 3900
- writer mode: threaded  queue depth max/warn: 1498/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 4.0/54/1066
- recv->write ms p50/p95/max: 17.0/297/2265
- rotate_count: 11  compression_count: 4  flush_count: 3172  writer_errors: 0
- binance bookTicker/s: 285.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 4395 | 0 | 0 | 8136 |
| binance | 257628 | 0 | 0 | 8191 |
| kalshi | 116790 | 1 | 0 | 8139 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
