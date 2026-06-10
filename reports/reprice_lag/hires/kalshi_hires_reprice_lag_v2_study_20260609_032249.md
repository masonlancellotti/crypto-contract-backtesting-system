# Kalshi KXBTC15M - repricing-lag **v2 (high-res)** study

_Generated 2026-06-09 03:22:49 UTC. HIGH-RES v2 on `kalshi_hires_joined_snapshots`. READ-ONLY research; no paper/live/orders/promotion. Settlement labels used for EVALUATION only; the underlying-implied PROXY is diagnostic, not truth._

> **Resolution note:** shock detection is sub-second (underlying returns), but the Kalshi book is REST-polled (~1.1s cadence), so +250ms/+500ms RESPONSE horizons are sparse and reported honestly.

## Findings (10 questions)
- **q1_sufficient** YES - 39153 joined rows across 54 windows, 2 day(s).
- **q2_rows_windows** 39153 joined rows; 54 distinct windows; days=['2026-06-08', '2026-06-09'].
- **q3_coverage** Kalshi response is REST-bound (~1.1s cadence): well-covered horizons (>=50%) = [1000, 2000, 5000, 10000, 15000, 30000, 60000]ms; +250/+500ms coverage = 0%/0% (too sparse to use - reported, not fabricated).
- **q4_shocks_lead** Median underlying-vs-Kalshi lag proxy = -1.26c at first resolved horizon; Kalshi moved in the expected direction in 61% of shocks.
- **q5_speed** Time-to-first Kalshi move >=2c: median 5554ms (>=1c: 4463ms) - bounded below by the ~1.1s book cadence.
- **q6_fee_surviving** 8 settled stale-quote opportunities after fees+depth+buffer (+0 pending).
- **q7_positive_negative** win_rate=0% avg_net_pnl=-0.1574/contract total=-1.259 profit_factor=0.00 -> NEGATIVE/none after costs.
- **q8_robust** see sensitivity CSV: 3bps avg_pnl=0.0756; 5bps avg_pnl=-0.1574; 8bps avg_pnl=-0.2700; 12bps avg_pnl=None
- **q9_diversified** opps across 7 windows / 2 day(s); sides YES/NO=4/4; CONCENTRATED
- **q10_worth_shadow** NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.

## Aggregate (after threshold 5.0bps, dedupe 20.0s)
- raw shock rows: 88  raw candidates: 8  deduped opportunities: **8** (settled 8, pending 0)
- distinct windows (opps): 7  days: 2  up/down shocks: 33/55
- win_rate: 0%  avg_net_pnl/contract: -0.1574  total_net_pnl: -1.259  profit_factor: 0.00

## Horizon coverage (fraction of shocks with a Kalshi row in tolerance)
| horizon | coverage |
|---|---:|
| +250ms | 0% |
| +500ms | 0% |
| +1000ms | 96% |
| +2000ms | 99% |
| +5000ms | 99% |
| +10000ms | 98% |
| +15000ms | 98% |
| +30000ms | 98% |
| +60000ms | 95% |

## Side breakdown
| side | opps | windows | win_rate | avg_pnl |
|---|---:|---:|---:|---:|
| YES | 4 | 3 | 0% | -0.1995 |
| NO | 4 | 4 | 0% | -0.1153 |

## Deribit regime
- n/a (fields: [])

## Recommendation
**NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.**

## Safety
- No paper, no live, no orders; `live_submission_allowed=false`.
- No promotion/manifest/pointer/gate/buffer change; labels = evaluation only; proxy != truth.
- Reads recorded hires data; writes only under reports/reprice_lag/hires/.
