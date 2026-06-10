# Kalshi KXBTC15M - repricing-lag **v2 (high-res)** study

_Generated 2026-06-10 14:22:38 UTC. HIGH-RES v2 on `kalshi_hires_joined_snapshots`. READ-ONLY research; no paper/live/orders/promotion. Settlement labels used for EVALUATION only; the underlying-implied PROXY is diagnostic, not truth._

> **Resolution note:** shock detection is sub-second (underlying returns), but the Kalshi book is REST-polled (~1.1s cadence), so +250ms/+500ms RESPONSE horizons are sparse and reported honestly.

## Findings (10 questions)
- **q1_sufficient** YES - 214634 joined rows across 58 windows, 1 day(s).
- **q2_rows_windows** 214634 joined rows; 58 distinct windows; days=['2026-06-10'].
- **q3_coverage** Kalshi response is REST-bound (~1.1s cadence): well-covered horizons (>=50%) = [250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000]ms; +250/+500ms coverage = 96%/96% (observable).
- **q4_shocks_lead** Median underlying-vs-Kalshi lag proxy = 0.20c at first resolved horizon; Kalshi moved in the expected direction in 59% of shocks.
- **q5_speed** Time-to-first Kalshi move >=2c: median 5103ms (>=1c: 4901ms) - bounded below by the ~1.1s book cadence.
- **q6_fee_surviving** 29 settled stale-quote opportunities after fees+depth+buffer (+0 pending).
- **q7_positive_negative** win_rate=14% avg_net_pnl=-0.0650/contract total=-1.885 profit_factor=0.60 -> NEGATIVE/none after costs.
- **q8_robust** see sensitivity CSV: 3bps avg_pnl=-0.1063; 5bps avg_pnl=-0.0650; 8bps avg_pnl=-0.2182; 12bps avg_pnl=-0.2786
- **q9_diversified** opps across 11 windows / 1 day(s); sides YES/NO=18/11; moderately spread
- **q10_worth_shadow** NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.

## Aggregate (after threshold 5.0bps, dedupe 20.0s)
- raw shock rows: 974  raw candidates: 133  deduped opportunities: **29** (settled 29, pending 0)
- distinct windows (opps): 11  days: 1  up/down shocks: 530/444
- win_rate: 14%  avg_net_pnl/contract: -0.0650  total_net_pnl: -1.885  profit_factor: 0.60

## Horizon coverage (fraction of shocks with a Kalshi row in tolerance)
| horizon | coverage |
|---|---:|
| +250ms | 96% |
| +500ms | 96% |
| +1000ms | 100% |
| +2000ms | 100% |
| +5000ms | 100% |
| +10000ms | 100% |
| +15000ms | 100% |
| +30000ms | 99% |
| +60000ms | 97% |

## Side breakdown
| side | opps | windows | win_rate | avg_pnl |
|---|---:|---:|---:|---:|
| NO | 11 | 4 | 9% | -0.1428 |
| YES | 18 | 7 | 17% | -0.0174 |

## Deribit regime
- n/a (fields: [])

## Recommendation
**NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.**

## Safety
- No paper, no live, no orders; `live_submission_allowed=false`.
- No promotion/manifest/pointer/gate/buffer change; labels = evaluation only; proxy != truth.
- Reads recorded hires data; writes only under reports/reprice_lag/hires/.
