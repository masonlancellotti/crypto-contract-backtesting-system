# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091030-30  joined snapshots: 775
- writer mode: threaded  queue depth max/warn: 1794/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/9/80
- recv->write ms p50/p95/max: 15/21/2620
- rotate_count: 14  compression_count: 0  flush_count: 3355  writer_errors: 0
- binance bookTicker/s: 1513.6  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1101.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 16255 | 0 | 0 | 4628 |
| binance | 1366193 | 0 | 0 | 5024 |
| kalshi | 775 | 0 | 0 | 4869 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
