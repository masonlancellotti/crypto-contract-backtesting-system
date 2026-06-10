# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN082300-00  joined snapshots: 765
- writer mode: threaded  queue depth max/warn: 1722/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 4/12/34
- recv->write ms p50/p95/max: 15/22/2274
- rotate_count: 11  compression_count: 11  flush_count: 3215  writer_errors: 0
- binance bookTicker/s: 520.4  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1106.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5737 | 0 | 0 | 6375 |
| binance | 469554 | 0 | 0 | 6441 |
| kalshi | 765 | 0 | 0 | 6892 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
