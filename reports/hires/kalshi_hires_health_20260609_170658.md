# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091315-15  joined snapshots: 783
- writer mode: threaded  queue depth max/warn: 1752/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/9/54
- recv->write ms p50/p95/max: 15/21/2297
- rotate_count: 11  compression_count: 3  flush_count: 3321  writer_errors: 0
- binance bookTicker/s: 1111.3  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1099.5

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 11250 | 0 | 0 | 8991 |
| binance | 1002742 | 0 | 0 | 9065 |
| kalshi | 783 | 0 | 0 | 8518 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
