# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091000-00  joined snapshots: 776
- writer mode: threaded  queue depth max/warn: 1934/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/9/66
- recv->write ms p50/p95/max: 15.0/21/2300
- rotate_count: 11  compression_count: 3  flush_count: 3317  writer_errors: 0
- binance bookTicker/s: 1139.7  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 13596 | 0 | 0 | 9093 |
| binance | 1028467 | 0 | 0 | 9162 |
| kalshi | 776 | 0 | 0 | 8955 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
