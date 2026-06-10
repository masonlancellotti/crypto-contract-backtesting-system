# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN081630-30  joined snapshots: 782
- writer mode: threaded  queue depth max/warn: 1630/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/9/41
- recv->write ms p50/p95/max: 14.0/21/2520
- rotate_count: 12  compression_count: 12  flush_count: 3200  writer_errors: 0
- binance bookTicker/s: 372.8  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1104

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 8320 | 0 | 0 | 5763 |
| binance | 336488 | 0 | 0 | 4958 |
| kalshi | 782 | 0 | 0 | 5050 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
