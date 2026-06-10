# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091645-45  joined snapshots: 782
- writer mode: threaded  queue depth max/warn: 1334/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/8/27
- recv->write ms p50/p95/max: 14.0/21/3038
- rotate_count: 11  compression_count: 11  flush_count: 3161  writer_errors: 0
- binance bookTicker/s: 203.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6039 | 0 | 0 | 3652 |
| binance | 183493 | 0 | 0 | 4486 |
| kalshi | 782 | 0 | 0 | 4764 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
