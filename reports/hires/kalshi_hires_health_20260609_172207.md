# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091330-30  joined snapshots: 782
- writer mode: threaded  queue depth max/warn: 1694/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/9/51
- recv->write ms p50/p95/max: 14.0/21/2502
- rotate_count: 11  compression_count: 3  flush_count: 3321  writer_errors: 0
- binance bookTicker/s: 1083.1  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1099

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 10509 | 0 | 0 | 8963 |
| binance | 977553 | 0 | 0 | 9259 |
| kalshi | 782 | 0 | 0 | 9405 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
