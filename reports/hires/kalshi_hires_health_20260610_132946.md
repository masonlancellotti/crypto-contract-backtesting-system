# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100930-30  joined snapshots: 784
- writer mode: threaded  queue depth max/warn: 1412/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 4.0/12/39
- recv->write ms p50/p95/max: 15.0/22/2397
- rotate_count: 14  compression_count: 14  flush_count: 3220  writer_errors: 0
- binance bookTicker/s: 473.1  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1102

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 8500 | 0 | 0 | 6244 |
| binance | 426895 | 0 | 0 | 6403 |
| kalshi | 784 | 0 | 0 | 6273 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
