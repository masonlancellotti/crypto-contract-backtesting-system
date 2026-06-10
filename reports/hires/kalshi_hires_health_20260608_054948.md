# Kalshi KXBTC15M high-res measurement — smoke (12s)

_Generated 2026-06-08 05:49:48 UTC. READ-ONLY measurement; no orders, no paper, no live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN080200-00
- joined snapshots: 4
- recv->write latency ms: median=28 p95=187
- JSONL write latency ms: median=0.013899989426136017 p95=0.030300026992335916
- Kalshi poll ms: target=500 actual_median=2714
- joined source age ms: coinbase median=168.5 max=208; binance median=48.0 max=127

| source | messages | rate/s | reconnects | errors | drops | gaps>1s | gaps>2s | gaps>5s | last_age_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| coinbase | 61 | 5.08 | 0 | 0 | 0 | 0 | 0 | 0 | 2199 |
| binance | 2002 | 166.83 | 0 | 0 | 0 | 0 | 0 | 0 | 2401 |
| kalshi | 5 | 0.42 | 0 | 0 | 0 | 0 | 4 | 0 | 1297 |

## Safety
- No orders, no paper, no live; `live_submission_allowed=false` on every row.
- Coinbase/Binance public WS (no auth); Kalshi public REST (no auth). No secrets read.
- Writes confined to hires/ paths; production normalized files untouched.
