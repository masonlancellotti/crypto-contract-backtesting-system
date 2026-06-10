# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN090215-15  joined snapshots: 774
- writer mode: threaded  queue depth max/warn: 1638/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/9/28
- recv->write ms p50/p95/max: 14.0/21/2632
- rotate_count: 11  compression_count: 11  flush_count: 3220  writer_errors: 0
- binance bookTicker/s: 440.4  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1107

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5012 | 0 | 0 | 5128 |
| binance | 397494 | 0 | 0 | 5533 |
| kalshi | 774 | 0 | 0 | 5176 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
