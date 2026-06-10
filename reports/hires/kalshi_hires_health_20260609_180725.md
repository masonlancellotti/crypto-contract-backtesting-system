# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN091415-15  joined snapshots: 781
- writer mode: threaded  queue depth max/warn: 1678/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3/9/37
- recv->write ms p50/p95/max: 15/21/2752
- rotate_count: 11  compression_count: 11  flush_count: 3262  writer_errors: 0
- binance bookTicker/s: 693.1  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1100.0

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 7445 | 0 | 0 | 6559 |
| binance | 625677 | 0 | 0 | 7118 |
| kalshi | 781 | 0 | 0 | 7381 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
