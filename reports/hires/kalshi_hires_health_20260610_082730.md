# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100430-30  joined snapshots: 766
- writer mode: threaded  queue depth max/warn: 1326/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/11/29
- recv->write ms p50/p95/max: 15.0/22/2225
- rotate_count: 14  compression_count: 14  flush_count: 3208  writer_errors: 0
- binance bookTicker/s: 453.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1101

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 3421 | 0 | 0 | 5921 |
| binance | 408937 | 0 | 0 | 5921 |
| kalshi | 766 | 0 | 0 | 5386 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
