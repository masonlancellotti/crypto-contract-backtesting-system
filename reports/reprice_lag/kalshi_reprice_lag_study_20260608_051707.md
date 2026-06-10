# Kalshi KXBTC15M — repricing-lag / stale-quote event study (READ-ONLY)

_Generated 2026-06-08 05:17:07 UTC. Event-study diagnostic — NOT a trading permission slip. No paper/live, no orders, no promotion, no pointer/manifest/gate/buffer changes. Settlement labels used for EVALUATION ONLY (never as signal). No profitability/alpha claimed._

> **DATA-RESOLUTION CEILING:** all recorded streams (Coinbase, Binance, Kalshi book) are polled on the same ~4s clock. A 1-3s repricing lag is **not directly observable** in this data; the +1s/+2s horizons do not resolve. Everything below is bounded by that ceiling.

## Data scanned
- files: 1  days: 20260607
- shock signals: spot returns 5/15/30/60s, vol-normalized, spot-perp basis jump, Binance OFI impulse (per-day p95), near-line; opportunity proxy: driftless-lognormal baseline P(YES) vs executable ask.
- study config: min_depth=1.0, min_seconds_to_close=60.0, max_book_age_ms=5000.0, conservative_buffer=3.0c (mirrors edge-policy fixed buffer; added, never removed).

## Aggregate: raw rows vs deduped opportunities vs distinct windows
- raw shock rows: **8891**  → deduped shock events: **1430**
- qualifying rows (after fees/depth/buffer): 1257  → **distinct micro-opportunities: 410**
- distinct windows (shocks): 96  | distinct windows (opps): **94**  | distinct days: 1
- up-shocks: 4529  down-shocks: 4362  near-line: 1323
- opportunity win rate (labelled): 35% (143/410)  avg net P&L/contract: -0.0179

## Core findings — does Kalshi lag BTC repricing?
1. **Shocks lead repricing?** Measurable only at the ~4s recording cadence. Median underlying-vs-Kalshi lag at first resolved post-horizon = 0.00c (proxy). Sub-4s lead/lag is NOT observable in this data.
2. **Lag seconds?** Cannot be resolved below ~4s (all streams co-sampled). Median time-to-first-Kalshi-move(>= 2.0c) = 11.7s (in cadence multiples).
3. **Executable stale quotes after fees/depth?** 410 distinct stale-quote opportunities survived fees + depth + a conservative buffer.
4. **Spread across windows?** 94 distinct windows across 1 day(s) — moderate spread; inspect concentration.
5. **Up & down both viable?** YES(up): n=134 win_rate=41%; NO(down): n=276 win_rate=32%.
6. **Persists across days/regimes?** opportunities span 1 day(s); see by_day / by_vol_regime tables.
7. **Killed by fees/spreads?** qualified opps after fees/buffer = 410 of 1257 raw qualifying rows; fees/spread remove most candidates.
8. **Worth a staged shadow strategy later?** Maybe — only as a STAGED shadow study with finer data; not paper/live.

## Regime / side breakdown (deduped opportunities)

**By side (YES=up-shock / NO=down-shock)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| NO | 276 | 78 | 88 | 188 | 32% | -0.0749 |
| YES | 134 | 51 | 55 | 79 | 41% | 0.0997 |

**By time-to-close**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| mid | 330 | 90 | 111 | 219 | 34% | -0.0399 |
| near-close | 54 | 38 | 15 | 39 | 28% | 0.0957 |
| near-open | 26 | 24 | 17 | 9 | 65% | 0.0258 |

**By line distance**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| far-line | 105 | 46 | 40 | 65 | 38% | -0.0829 |
| mid | 222 | 80 | 69 | 153 | 31% | 0.0014 |
| near-line | 83 | 41 | 34 | 49 | 41% | 0.0128 |

**By volatility regime (spot sigma terciles)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| high-vol | 143 | 31 | 45 | 98 | 31% | -0.0926 |
| low-vol | 145 | 34 | 49 | 96 | 34% | 0.0118 |
| mid-vol | 122 | 34 | 49 | 73 | 40% | 0.0345 |

**By day/session**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| 20260607 | 410 | 94 | 143 | 267 | 35% | -0.0179 |

**By Deribit regime**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| None | 410 | 94 | 143 | 267 | 35% | -0.0179 |

## Deribit regime integration
- Deribit point-in-time fields present in events: **False** (optional; missing/disabled for these days — core study unaffected)

## Polymarket reference (optional)
- classification: **skipped** — pass --include-polymarket to classify

## Recommendation
**DO LATER (staged shadow only).** A fee-surviving, multi-window effect is suggested but must be re-validated on sub-second data before any shadow strategy. No paper/live; no promotion.

## Safety status
- No paper, no live, no orders; `live_submission_allowed=false`.
- No promotion/demotion; no model/calibrator/policy pointer change; promotion manifest untouched.
- No gate weakened, no buffer removed (a conservative buffer was ADDED for opportunity qualification).
- Labels used for evaluation only; reads recorded data; writes only under reports/reprice_lag/.

## Next 3 actions
1. Add a sub-second (tick or <=500ms) collector for Coinbase/Binance AND the Kalshi book — without it the core lag hypothesis is untestable; this is the binding constraint.
2. Re-run this event study on the finer data with the +1s/+2s horizons and `time_to_move` at sub-second resolution; require opportunities across many distinct windows and both up/down regimes.
3. Keep this STAGED/report-only; do not build any shadow/paper strategy until (1)-(2) show a fee-surviving, diversified effect — current data cannot justify it.
