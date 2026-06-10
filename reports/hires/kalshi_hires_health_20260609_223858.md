# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091845-45  joined snapshots: 779
- writer mode: threaded  queue depth max/warn: 1494/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2/9/31
- recv->write ms p50/p95/max: 14/21/2472
- rotate_count: 14  compression_count: 14  flush_count: 3222  writer_errors: 0
- binance bookTicker/s: 346.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6035 | 0 | 0 | 4623 |
| binance | 312440 | 0 | 0 | 4882 |
| kalshi | 779 | 0 | 0 | 4843 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
