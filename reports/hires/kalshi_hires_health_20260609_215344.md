# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091800-00  joined snapshots: 786
- writer mode: threaded  queue depth max/warn: 1042/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 1.0/7/32
- recv->write ms p50/p95/max: 13.0/21/2221
- rotate_count: 14  compression_count: 14  flush_count: 3182  writer_errors: 0
- binance bookTicker/s: 236.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 8054 | 0 | 0 | 3938 |
| binance | 213387 | 0 | 0 | 3916 |
| kalshi | 786 | 0 | 0 | 3790 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
