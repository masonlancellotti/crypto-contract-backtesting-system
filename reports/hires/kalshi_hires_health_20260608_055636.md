# Kalshi KXBTC15M high-res measurement — record (60s)

_Generated 2026-06-08 05:56:36 UTC. READ-ONLY measurement; no orders, no paper, no live, no promotion. `live_submission_allowed=false`, `no_orders=true`._

- active ticker: KXBTC15M-26JUN080200-00
- joined snapshots: 52
- recv->write latency ms: median=86 p95=480
- JSONL write latency ms: median=0.013399985618889332 p95=0.03029999788850546
- Kalshi poll ms: target=500 actual_median=1107
- joined source age ms: coinbase median=225.0 max=644; binance median=20.5 max=256

| source | messages | rate/s | reconnects | errors | drops | gaps>1s | gaps>2s | gaps>5s | last_age_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| coinbase | 532 | 8.87 | 0 | 0 | 0 | 1 | 0 | 0 | 2254 |
| binance | 27219 | 453.65 | 0 | 0 | 0 | 0 | 0 | 0 | 2583 |
| kalshi | 53 | 0.88 | 0 | 0 | 0 | 52 | 0 | 0 | 2556 |

## Safety
- No orders, no paper, no live; `live_submission_allowed=false` on every row.
- Coinbase/Binance public WS (no auth); Kalshi public REST (no auth). No secrets read.
- Writes confined to hires/ paths; production normalized files untouched.
