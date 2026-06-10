# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN081415-15  joined snapshots: 782
- writer mode: threaded  queue depth max/warn: 4387/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/12/787
- recv->write ms p50/p95/max: 15.0/22/2203
- rotate_count: 11  compression_count: 11  flush_count: 3204  writer_errors: 0
- binance bookTicker/s: 410.3  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1103

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 8370 | 0 | 0 | 5713 |
| binance | 370190 | 0 | 0 | 5610 |
| kalshi | 782 | 0 | 0 | 5976 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
