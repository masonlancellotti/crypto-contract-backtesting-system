# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN090030-30  joined snapshots: 774
- writer mode: threaded  queue depth max/warn: 1344/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/12/94
- recv->write ms p50/p95/max: 15.0/23/2434
- rotate_count: 9  compression_count: 9  flush_count: 3199  writer_errors: 0
- binance bookTicker/s: 373.6  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1105

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5072 | 0 | 0 | 6298 |
| binance | 337178 | 0 | 0 | 5513 |
| kalshi | 774 | 0 | 0 | 5594 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
