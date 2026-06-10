# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN081715-15  joined snapshots: 782
- writer mode: threaded  queue depth max/warn: 1390/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/7/36
- recv->write ms p50/p95/max: 14.0/21/2373
- rotate_count: 14  compression_count: 14  flush_count: 3230  writer_errors: 0
- binance bookTicker/s: 404.0  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1104

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 9604 | 0 | 0 | 5010 |
| binance | 364597 | 0 | 0 | 5156 |
| kalshi | 782 | 0 | 0 | 3441 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
