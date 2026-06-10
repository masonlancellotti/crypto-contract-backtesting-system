# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100945-45  joined snapshots: 781
- writer mode: threaded  queue depth max/warn: 1524/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/11/74
- recv->write ms p50/p95/max: 15/22/2380
- rotate_count: 14  compression_count: 3  flush_count: 3361  writer_errors: 0
- binance bookTicker/s: 1481.4  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1104.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 14989 | 0 | 0 | 10209 |
| binance | 1336806 | 0 | 0 | 10348 |
| kalshi | 781 | 0 | 0 | 9482 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
