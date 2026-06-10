# Kalshi trade-frequency frontier — KXBTC15M

- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**
- gate_windows: 143  candidates: 2004  distinct_windows: 31
- scenarios evaluated: 60 (bounded; not a full grid)

## ⚠️ Do NOT pick a policy by max in-sample net P&L (overfits). Evidence only.

| scenario | trades | windows | trades/win | net_pnl | hit | wf=na |
|---|---|---|---|---|---|---|
| edge1.0c_mtw3_cd0s_min120s | 84 | 28 | 3.0000 | 0.6170 | 0.4048 |  |
| edge1.0c_mtw3_cd5s_min120s | 84 | 28 | 3.0000 | 0.6170 | 0.4048 |  |
| edge1.0c_mtw3_cd0s_min60s | 92 | 31 | 2.9677 | 0.4780 | 0.3696 |  |
| edge1.0c_mtw3_cd5s_min60s | 92 | 31 | 2.9677 | 0.4780 | 0.3696 |  |
| edge1.0c_mtw3_cd0s_min5s | 93 | 31 | 3.0000 | 0.4580 | 0.3656 |  |
| edge1.0c_mtw3_cd0s_min15s | 93 | 31 | 3.0000 | 0.4580 | 0.3656 |  |
| edge1.0c_mtw3_cd0s_min30s | 93 | 31 | 3.0000 | 0.4580 | 0.3656 |  |
| edge1.0c_mtw3_cd5s_min5s | 93 | 31 | 3.0000 | 0.4580 | 0.3656 |  |

## Safety
- RESEARCH EVIDENCE ONLY: no orders, no PAPER_CANDIDATE, no live trading.
- No policy is promoted; recommendations require manual review + paper validation.
- Distinct windows matter more than raw trade count (one label per 15m window).
- Score constantly; trade only when marginal net edge (after fees/executable prices) is positive.
