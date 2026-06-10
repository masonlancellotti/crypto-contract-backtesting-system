# Kalshi KXBTC15M — repricing-lag / stale-quote event study (READ-ONLY)

_Generated 2026-06-09 00:42:08 UTC. Event-study diagnostic — NOT a trading permission slip. No paper/live, no orders, no promotion, no pointer/manifest/gate/buffer changes. Settlement labels used for EVALUATION ONLY (never as signal). No profitability/alpha claimed._

> **DATA-RESOLUTION CEILING:** all recorded streams (Coinbase, Binance, Kalshi book) are polled on the same ~4s clock. A 1-3s repricing lag is **not directly observable** in this data; the +1s/+2s horizons do not resolve. Everything below is bounded by that ceiling.

## Data scanned
- files: 9  days: 20260601, 20260602, 20260603, 20260604, 20260605, 20260606, 20260607, 20260608, 20260609
- shock signals: spot returns 5/15/30/60s, vol-normalized, spot-perp basis jump, Binance OFI impulse (per-day p95), near-line; opportunity proxy: driftless-lognormal baseline P(YES) vs executable ask.
- study config: min_depth=1.0, min_seconds_to_close=60.0, max_book_age_ms=5000.0, conservative_buffer=3.0c (mirrors edge-policy fixed buffer; added, never removed).

## Aggregate: raw rows vs deduped opportunities vs distinct windows
- raw shock rows: **118286**  → deduped shock events: **20666**
- qualifying rows (after fees/depth/buffer): 4351  → **distinct micro-opportunities: 1387**
- distinct windows (shocks): 609  | distinct windows (opps): **281**  | distinct days: 8
- up-shocks: 56660  down-shocks: 61626  near-line: 6378
- opportunity win rate (labelled): 30% (419/1381)  avg net P&L/contract: -0.0273

## Core findings — does Kalshi lag BTC repricing?
1. **Shocks lead repricing?** Measurable only at the ~4s recording cadence. Median underlying-vs-Kalshi lag at first resolved post-horizon = 0.00c (proxy). Sub-4s lead/lag is NOT observable in this data.
2. **Lag seconds?** Cannot be resolved below ~4s (all streams co-sampled). Median time-to-first-Kalshi-move(>= 2.0c) = 11.3s (in cadence multiples).
3. **Executable stale quotes after fees/depth?** 1387 distinct stale-quote opportunities survived fees + depth + a conservative buffer.
4. **Spread across windows?** 281 distinct windows across 8 day(s); moderate spread; inspect concentration.
5. **Up & down both viable?** YES(up): n=522 win_rate=26%; NO(down): n=865 win_rate=33%.
6. **Persists across days/regimes?** opportunities span 8 day(s); see by_day / by_vol_regime tables.
7. **Killed by fees/spreads?** qualified opps after fees/buffer = 1387 of 4351 raw qualifying rows; fees/spread remove most candidates.
8. **Worth a staged shadow strategy later?** Maybe, but only as a STAGED shadow study with finer data; not paper/live.

## Regime / side breakdown (deduped opportunities)

**By side (YES=up-shock / NO=down-shock)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| NO | 865 | 215 | 281 | 579 | 33% | -0.0364 |
| YES | 522 | 170 | 138 | 383 | 26% | -0.0124 |

**By time-to-close**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| mid | 1120 | 275 | 346 | 768 | 31% | -0.0341 |
| near-close | 185 | 137 | 31 | 154 | 17% | 0.0025 |
| near-open | 82 | 66 | 42 | 40 | 51% | -0.0031 |

**By line distance**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| far-line | 414 | 156 | 130 | 280 | 32% | -0.0228 |
| mid | 726 | 239 | 184 | 540 | 25% | -0.0446 |
| near-line | 247 | 121 | 105 | 142 | 43% | 0.0158 |

**By volatility regime (spot sigma terciles)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| high-vol | 579 | 109 | 170 | 403 | 30% | -0.0501 |
| low-vol | 422 | 92 | 103 | 319 | 24% | -0.0375 |
| mid-vol | 386 | 95 | 146 | 240 | 38% | 0.0176 |

**By day/session**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| 20260605 | 135 | 20 | 45 | 90 | 33% | -0.0069 |
| 20260606 | 378 | 75 | 81 | 297 | 21% | -0.0332 |
| 20260607 | 410 | 94 | 143 | 267 | 35% | -0.0179 |
| 20260608 | 443 | 89 | 142 | 301 | 32% | -0.0397 |
| 20260609 | 21 | 3 | 8 | 7 | 53% | 0.0431 |

## Deribit regime integration
- Deribit point-in-time fields present in events: **True** (joined per row)

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
