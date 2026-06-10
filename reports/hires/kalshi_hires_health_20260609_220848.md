# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091815-15  joined snapshots: 786
- writer mode: threaded  queue depth max/warn: 1488/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/6/36
- recv->write ms p50/p95/max: 12.0/20/2569
- rotate_count: 14  compression_count: 14  flush_count: 3205  writer_errors: 0
- binance bookTicker/s: 218.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 8290 | 0 | 0 | 3865 |
| binance | 197237 | 0 | 0 | 4201 |
| kalshi | 786 | 0 | 0 | 3901 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
