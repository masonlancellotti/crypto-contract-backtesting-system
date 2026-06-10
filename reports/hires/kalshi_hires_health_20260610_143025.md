# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN101045-45  joined snapshots: 780
- writer mode: threaded  queue depth max/warn: 1286/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 4.0/12/90
- recv->write ms p50/p95/max: 16.0/23/2598
- rotate_count: 9  compression_count: 1  flush_count: 3304  writer_errors: 0
- binance bookTicker/s: 922.7  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1103

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 10432 | 0 | 0 | 10265 |
| binance | 832828 | 0 | 0 | 9650 |
| kalshi | 780 | 0 | 0 | 9818 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
