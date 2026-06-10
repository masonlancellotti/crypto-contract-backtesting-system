# Kalshi KXBTC15M - repricing-lag **v2 (high-res)** study

_Generated 2026-06-10 05:05:32 UTC. HIGH-RES v2 on `kalshi_hires_joined_snapshots`. READ-ONLY research; no paper/live/orders/promotion. Settlement labels used for EVALUATION only; the underlying-implied PROXY is diagnostic, not truth._

> **Resolution note:** shock detection is sub-second (underlying returns), but the Kalshi book is REST-polled (~1.1s cadence), so +250ms/+500ms RESPONSE horizons are sparse and reported honestly.

## Findings (10 questions)
- **q1_sufficient** YES - 42644 joined rows across 21 windows, 1 day(s).
- **q2_rows_windows** 42644 joined rows; 21 distinct windows; days=['2026-06-10'].
- **q3_coverage** Kalshi response is REST-bound (~1.1s cadence): well-covered horizons (>=50%) = [250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000]ms; +250/+500ms coverage = 63%/63% (observable).
- **q4_shocks_lead** Median underlying-vs-Kalshi lag proxy = -1.00c at first resolved horizon; Kalshi moved in the expected direction in 63% of shocks.
- **q5_speed** Time-to-first Kalshi move >=2c: median 5536ms (>=1c: 4895ms) - bounded below by the ~1.1s book cadence.
- **q6_fee_surviving** 2 settled stale-quote opportunities after fees+depth+buffer (+0 pending).
- **q7_positive_negative** win_rate=50% avg_net_pnl=0.0050/contract total=0.010 profit_factor=1.11 -> POSITIVE.
- **q8_robust** see sensitivity CSV: 3bps avg_pnl=-0.0336; 5bps avg_pnl=0.0050; 8bps avg_pnl=None; 12bps avg_pnl=None
- **q9_diversified** opps across 2 windows / 1 day(s); sides YES/NO=0/2; CONCENTRATED
- **q10_worth_shadow** NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.

## Aggregate (after threshold 5.0bps, dedupe 20.0s)
- raw shock rows: 33  raw candidates: 2  deduped opportunities: **2** (settled 2, pending 0)
- distinct windows (opps): 2  days: 1  up/down shocks: 18/15
- win_rate: 50%  avg_net_pnl/contract: 0.0050  total_net_pnl: 0.010  profit_factor: 1.11

## Horizon coverage (fraction of shocks with a Kalshi row in tolerance)
| horizon | coverage |
|---|---:|
| +250ms | 63% |
| +500ms | 63% |
| +1000ms | 99% |
| +2000ms | 99% |
| +5000ms | 99% |
| +10000ms | 99% |
| +15000ms | 100% |
| +30000ms | 99% |
| +60000ms | 97% |

## Side breakdown
| side | opps | windows | win_rate | avg_pnl |
|---|---:|---:|---:|---:|
| NO | 2 | 2 | 50% | 0.0050 |

## Deribit regime
- n/a (fields: [])

## Recommendation
**NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; not worth a shadow strategy. Continue research only.**

## Safety
- No paper, no live, no orders; `live_submission_allowed=false`.
- No promotion/manifest/pointer/gate/buffer change; labels = evaluation only; proxy != truth.
- Reads recorded hires data; writes only under reports/reprice_lag/hires/.
