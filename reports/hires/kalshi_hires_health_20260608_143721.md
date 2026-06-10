# Kalshi KXBTC15M high-res measurement — record (60s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN081045-45  joined snapshots: 53
- writer mode: threaded  queue depth max/warn: 1422/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/10/37
- recv->write ms p50/p95/max: 15/22/2309
- rotate_count: 7  compression_count: 7  flush_count: 227  writer_errors: 0
- binance bookTicker/s: 767.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1106.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 1111 | 0 | 0 | 2703 |
| binance | 47838 | 0 | 0 | 2806 |
| kalshi | 53 | 0 | 0 | 2906 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
