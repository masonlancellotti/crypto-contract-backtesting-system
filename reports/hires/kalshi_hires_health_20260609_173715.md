# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091345-45  joined snapshots: 781
- writer mode: threaded  queue depth max/warn: 1794/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/9/48
- recv->write ms p50/p95/max: 14/21/2254
- rotate_count: 11  compression_count: 11  flush_count: 3289  writer_errors: 0
- binance bookTicker/s: 766.8  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 9204 | 0 | 0 | 7147 |
| binance | 691925 | 0 | 0 | 7190 |
| kalshi | 781 | 0 | 0 | 7320 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
