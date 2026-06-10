# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN092345-45  joined snapshots: 777
- writer mode: threaded  queue depth max/warn: 1520/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/12/60
- recv->write ms p50/p95/max: 15/23/2272
- rotate_count: 14  compression_count: 14  flush_count: 3208  writer_errors: 0
- binance bookTicker/s: 382.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1104.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6687 | 0 | 0 | 5465 |
| binance | 345104 | 0 | 0 | 5488 |
| kalshi | 777 | 0 | 0 | 5198 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
