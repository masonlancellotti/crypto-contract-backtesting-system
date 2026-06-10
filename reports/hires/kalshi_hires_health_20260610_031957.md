# Kalshi KXBTC15M high-res measurement — record (120s)

_READ-ONLY measurement; no orders, no paper/live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN092330-30  joined snapshots: 540
- writer mode: threaded  queue depth max/warn: 1020/50000  warned: False  high-priority overflow: 0
- dropped by stream: none
- writer lag ms p50/p95/max: 3.0/16/43
- recv->write ms p50/p95/max: 15.0/29/2249
- rotate_count: 7  compression_count: 7  flush_count: 461  writer_errors: 0
- binance bookTicker/s: 420.8  aggTrade/s: 0.0  aggTrade_enabled: False  sampled/dropped: 0  rate_capped: 0
- Kalshi poll target/actual ms: 500/1

| source | messages | reconnects | errors | last_age_ms |
|---|---:|---:|---:|---:|
| coinbase | 919 | 0 | 0 | 3042 |
| binance | 51457 | 0 | 0 | 3034 |
| kalshi | 24084 | 0 | 0 | 3084 |

## Notes / fallbacks
- binance aggTrade disabled (default; bookTicker only - lighter)
- kalshi: using READ-ONLY market-data WebSocket book source (orderbook_delta)

## Safety
- No orders, no paper/live; `live_submission_allowed=false` on every row.
- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.
- Writes confined to hires/ paths; production files untouched.
