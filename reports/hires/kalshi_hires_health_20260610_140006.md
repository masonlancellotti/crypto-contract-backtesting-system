# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN101000-00  joined snapshots: 784
- writer mode: threaded  queue depth max/warn: 1486/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/12/70
- recv->write ms p50/p95/max: 15.0/23/2305
- rotate_count: 14  compression_count: 3  flush_count: 3342  writer_errors: 0
- binance bookTicker/s: 1157.3  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1102

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 11233 | 0 | 0 | 9730 |
| binance | 1044264 | 0 | 0 | 9790 |
| kalshi | 784 | 0 | 0 | 8307 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
