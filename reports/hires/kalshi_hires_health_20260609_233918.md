# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091945-45  joined snapshots: 774
- writer mode: threaded  queue depth max/warn: 1806/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/9/34
- recv->write ms p50/p95/max: 14.0/21/2305
- rotate_count: 14  compression_count: 14  flush_count: 3226  writer_errors: 0
- binance bookTicker/s: 407.7  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1102

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6905 | 0 | 0 | 5024 |
| binance | 367855 | 0 | 0 | 5105 |
| kalshi | 774 | 0 | 0 | 4751 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
