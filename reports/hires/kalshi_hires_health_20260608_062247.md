# Kalshi KXBTC15M high-res measurement — record (60s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN080230-30  joined snapshots: 53
- writer mode: threaded  queue depth max/warn: 1044/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2/7/12
- recv->write ms p50/p95/max: 13/20/2419
- rotate_count: 7  compression_count: 7  flush_count: 227  writer_errors: 0
- binance bookTicker/s: 573.7  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1101.5

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 476 | 0 | 0 | 2508 |
| binance | 35813 | 0 | 0 | 2735 |
| kalshi | 53 | 0 | 0 | 2858 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
