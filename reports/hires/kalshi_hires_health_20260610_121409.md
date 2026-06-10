# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100815-15  joined snapshots: 786
- writer mode: threaded  queue depth max/warn: 1222/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 4.0/12/88
- recv->write ms p50/p95/max: 16.0/22/532
- rotate_count: 7  compression_count: 7  flush_count: 3228  writer_errors: 0
- binance bookTicker/s: 556.3  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1097

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 6546 | 0 | 0 | 4829 |
| binance | 500981 | 0 | 0 | 5023 |
| kalshi | 786 | 0 | 0 | 5403 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
