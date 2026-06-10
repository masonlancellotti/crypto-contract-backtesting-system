# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN090415-15  joined snapshots: 779
- writer mode: threaded  queue depth max/warn: 1224/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2/9/25
- recv->write ms p50/p95/max: 14/21/2679
- rotate_count: 14  compression_count: 14  flush_count: 3175  writer_errors: 0
- binance bookTicker/s: 240.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1101.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 3901 | 0 | 0 | 3964 |
| binance | 216882 | 0 | 0 | 4412 |
| kalshi | 779 | 0 | 0 | 3351 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
