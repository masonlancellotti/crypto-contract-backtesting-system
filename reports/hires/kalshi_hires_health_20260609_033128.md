# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN082345-45  joined snapshots: 689
- writer mode: threaded  queue depth max/warn: 1436/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/9/32
- recv->write ms p50/p95/max: 15/21/2511
- rotate_count: 7  compression_count: 7  flush_count: 2848  writer_errors: 0
- binance bookTicker/s: 386.1  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1105.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 4318 | 0 | 0 | 4633 |
| binance | 311369 | 0 | 0 | 4946 |
| kalshi | 689 | 0 | 0 | 5180 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
