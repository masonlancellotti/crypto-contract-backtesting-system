# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN090115-15  joined snapshots: 775
- writer mode: threaded  queue depth max/warn: 1796/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 2/9/39
- recv->write ms p50/p95/max: 14/21/2251
- rotate_count: 14  compression_count: 14  flush_count: 3242  writer_errors: 0
- binance bookTicker/s: 406.5  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1106.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6124 | 0 | 0 | 5006 |
| binance | 366789 | 0 | 0 | 5034 |
| kalshi | 775 | 0 | 0 | 4923 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
