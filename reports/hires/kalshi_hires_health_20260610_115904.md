# Kalshi KXBTC15M high-res measurement — record (900s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN100800-00  joined snapshots: 780
- writer mode: threaded  queue depth max/warn: 1242/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/12/33
- recv->write ms p50/p95/max: 15.0/22/2242
- rotate_count: 14  compression_count: 14  flush_count: 3214  writer_errors: 0
- binance bookTicker/s: 424.8  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1099

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 5073 | 0 | 0 | 5785 |
| binance | 383326 | 0 | 0 | 5806 |
| kalshi | 780 | 0 | 0 | 5734 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
