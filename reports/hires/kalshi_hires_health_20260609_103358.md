# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN090645-45  joined snapshots: 762
- writer mode: threaded  queue depth max/warn: 1400/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2.0/9/20
- recv->write ms p50/p95/max: 14.0/21/2302
- rotate_count: 11  compression_count: 11  flush_count: 3180  writer_errors: 0
- binance bookTicker/s: 249.2  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1101

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 4466 | 0 | 0 | 3955 |
| binance | 224848 | 0 | 0 | 4056 |
| kalshi | 762 | 0 | 0 | 4137 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
