# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN101045-45  joined snapshots: 497
- writer mode: threaded  queue depth max/warn: 2194/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 5/47/268
- recv->write ms p50/p95/max: 17/81/2240
- rotate_count: 7  compression_count: 3  flush_count: 2056  writer_errors: 0
- binance bookTicker/s: 859.6  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1104.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5462 | 0 | 0 | 9907 |
| binance | 487954 | 0 | 0 | 9934 |
| kalshi | 497 | 0 | 0 | 9572 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
