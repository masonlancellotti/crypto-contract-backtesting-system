# Kalshi KXBTC15M high-res measurement — record (12s)

_Generated 2026-06-08 05:50:47 UTC. READ-ONLY measurement; no orders, no paper, no live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN080200-00
- joined snapshots: 9
- recv->write latency ms: median=252.0 p95=873
- JSONL write latency ms: median=0.012999982573091984 p95=0.026399997295811772
- Kalshi poll ms: target=500 actual_median=1097.0
- joined source age ms: coinbase median=441 max=920; binance median=24 max=444

| source | messages | rate/s | reconnects | errors | drops | gaps>1s | gaps>2s | gaps>5s | last_age_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| coinbase | 93 | 7.75 | 0 | 0 | 0 | 2 | 0 | 0 | 2213 |
| binance | 8968 | 747.33 | 0 | 0 | 0 | 0 | 0 | 0 | 2315 |
| kalshi | 10 | 0.83 | 0 | 0 | 0 | 9 | 0 | 0 | 2161 |

## Safety
- No orders, no paper, no live; `live_submission_allowed=false` on every row.
- Coinbase/Binance public WS (no auth); Kalshi public REST (no auth). No secrets read.
- Writes confined to hires/ paths; production normalized files untouched.
