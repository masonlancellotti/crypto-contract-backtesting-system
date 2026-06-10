# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN101045-45  joined snapshots: 5
- writer mode: threaded  queue depth max/warn: 1262/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 8/32/38
- recv->write ms p50/p95/max: 21/67/2481
- rotate_count: 7  compression_count: 7  flush_count: 33  writer_errors: 0
- binance bookTicker/s: 770.1  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1113.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 60 | 0 | 0 | 2367 |
| binance | 7458 | 0 | 0 | 2642 |
| kalshi | 5 | 0 | 0 | 2995 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
