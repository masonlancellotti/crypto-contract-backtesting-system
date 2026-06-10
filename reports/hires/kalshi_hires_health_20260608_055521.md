# Kalshi KXBTC15M high-res measurement — smoke (30s)

_Generated 2026-06-08 05:55:21 UTC. READ-ONLY measurement; no orders, no paper, no live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN080200-00
- joined snapshots: 25
- recv->write latency ms: median=204.0 p95=610
- JSONL write latency ms: median=0.013300013961270452 p95=0.02850001328624785
- Kalshi poll ms: target=500 actual_median=1110.0
- joined source age ms: coinbase median=121 max=507; binance median=27 max=218

| source | messages | rate/s | reconnects | errors | drops | gaps>1s | gaps>2s | gaps>5s | last_age_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| coinbase | 365 | 12.17 | 0 | 0 | 0 | 1 | 0 | 0 | 2229 |
| binance | 23488 | 782.93 | 0 | 0 | 0 | 0 | 0 | 0 | 2333 |
| kalshi | 26 | 0.87 | 0 | 0 | 0 | 25 | 0 | 0 | 1904 |

## Safety
- No orders, no paper, no live; `live_submission_allowed=false` on every row.
- Coinbase/Binance public WS (no auth); Kalshi public REST (no auth). No secrets read.
- Writes confined to hires/ paths; production normalized files untouched.
