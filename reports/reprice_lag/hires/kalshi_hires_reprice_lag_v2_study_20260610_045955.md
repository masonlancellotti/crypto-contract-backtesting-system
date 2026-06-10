# Kalshi KXBTC15M - repricing-lag **v2 (high-res)** study

_Generated 2026-06-10 04:59:55 UTC. HIGH-RES v2 on `kalshi_hires_joined_snapshots`. READ-ONLY research; no paper/live/orders/promotion. Settlement labels used for EVALUATION only; the underlying-implied PROXY is diagnostic, not truth._

> **Resolution note:** shock detection is sub-second (underlying returns), but the Kalshi book is REST-polled (~1.1s cadence), so +250ms/+500ms RESPONSE horizons are sparse and reported honestly.

## Findings (10 questions)
- **q1_sufficient** YES - 143618 joined rows across 156 windows, 3 day(s).
- **q2_rows_windows** 143618 joined rows; 156 distinct windows; days=['2026-06-08', '2026-06-09', '2026-06-10'].
- **q3_coverage** Kalshi response is REST-bound (~1.1s cadence): well-covered horizons (>=50%) = [1000, 2000, 5000, 10000, 15000, 30000, 60000]ms; +250/+500ms coverage = 11%/11% (too sparse to use - reported, not fabricated).
- **q4_shocks_lead** Median underlying-vs-Kalshi lag proxy = -0.17c at first resolved horizon; Kalshi moved in the expected direction in 60% of shocks.
- **q5_speed** Time-to-first Kalshi move >=2c: median 5532ms (>=1c: 4404ms) - bounded below by the ~1.1s book cadence.
- **q6_fee_surviving** 43 settled stale-quote opportunities after fees+depth+buffer (+0 pending).
- **q7_positive_negative** win_rate=23% avg_net_pnl=0.0233/contract total=1.004 profit_factor=1.19 -> POSITIVE.
- **q8_robust** see sensitivity CSV: 3bps avg_pnl=0.0692; 5bps avg_pnl=0.0233; 8bps avg_pnl=-0.1885; 12bps avg_pnl=-0.1753
- **q9_diversified** opps across 28 windows / 3 day(s); sides YES/NO=25/18; moderately spread
- **q10_worth_shadow** PROMISING but needs more data/regimes before any STAGED shadow study; not paper/live.

## Aggregate (after threshold 5.0bps, dedupe 20.0s)
- raw shock rows: 339  raw candidates: 44  deduped opportunities: **43** (settled 43, pending 0)
- distinct windows (opps): 28  days: 3  up/down shocks: 168/171
- win_rate: 23%  avg_net_pnl/contract: 0.0233  total_net_pnl: 1.004  profit_factor: 1.19

## Horizon coverage (fraction of shocks with a Kalshi row in tolerance)
| horizon | coverage |
|---|---:|
| +250ms | 11% |
| +500ms | 11% |
| +1000ms | 97% |
| +2000ms | 99% |
| +5000ms | 99% |
| +10000ms | 99% |
| +15000ms | 99% |
| +30000ms | 98% |
| +60000ms | 96% |

## Side breakdown
| side | opps | windows | win_rate | avg_pnl |
|---|---:|---:|---:|---:|
| YES | 25 | 14 | 36% | 0.1569 |
| NO | 18 | 16 | 6% | -0.1622 |

## Deribit regime
- Deribit is SLOW regime context (separate ~30s collector); joined point-in-time later. Not in the sub-second hot path. (fields: ['deribit_dvol', 'deribit_btc_iv_index', 'deribit_historical_vol'])

## Recommendation
**PROMISING but needs more data/regimes before any STAGED shadow study; not paper/live.**

## Safety
- No paper, no live, no orders; `live_submission_allowed=false`.
- No promotion/manifest/pointer/gate/buffer change; labels = evaluation only; proxy != truth.
- Reads recorded hires data; writes only under reports/reprice_lag/hires/.
