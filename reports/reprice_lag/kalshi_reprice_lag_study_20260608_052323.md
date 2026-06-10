# Kalshi KXBTC15M — repricing-lag / stale-quote event study (READ-ONLY)

_Generated 2026-06-08 05:23:25 UTC. Event-study diagnostic — NOT a trading permission slip. No paper/live, no orders, no promotion, no pointer/manifest/gate/buffer changes. Settlement labels used for EVALUATION ONLY (never as signal). No profitability/alpha claimed._

> **DATA-RESOLUTION CEILING:** all recorded streams (Coinbase, Binance, Kalshi book) are polled on the same ~4s clock. A 1-3s repricing lag is **not directly observable** in this data; the +1s/+2s horizons do not resolve. Everything below is bounded by that ceiling.

## Data scanned
- files: 8  days: 20260601, 20260602, 20260603, 20260604, 20260605, 20260606, 20260607, 20260608
- shock signals: spot returns 5/15/30/60s, vol-normalized, spot-perp basis jump, Binance OFI impulse (per-day p95), near-line; opportunity proxy: driftless-lognormal baseline P(YES) vs executable ask.
- study config: min_depth=1.0, min_seconds_to_close=60.0, max_book_age_ms=5000.0, conservative_buffer=3.0c (mirrors edge-policy fixed buffer; added, never removed).

## Aggregate: raw rows vs deduped opportunities vs distinct windows
- raw shock rows: **111320**  → deduped shock events: **19573**
- qualifying rows (after fees/depth/buffer): 3291  → **distinct micro-opportunities: 1030**
- distinct windows (shocks): 532  | distinct windows (opps): **211**  | distinct days: 7
- up-shocks: 53161  down-shocks: 58159  near-line: 5522
- opportunity win rate (labelled): 32% (328/1026)  avg net P&L/contract: -0.0148

## Core findings — does Kalshi lag BTC repricing?
1. **Shocks lead repricing?** Measurable only at the ~4s recording cadence. Median underlying-vs-Kalshi lag at first resolved post-horizon = 0.00c (proxy). Sub-4s lead/lag is NOT observable in this data.
2. **Lag seconds?** Cannot be resolved below ~4s (all streams co-sampled). Median time-to-first-Kalshi-move(>= 2.0c) = 11.2s (in cadence multiples).
3. **Executable stale quotes after fees/depth?** 1030 distinct stale-quote opportunities survived fees + depth + a conservative buffer.
4. **Spread across windows?** 211 distinct windows across 7 day(s); moderate spread; inspect concentration.
5. **Up & down both viable?** YES(up): n=388 win_rate=30%; NO(down): n=642 win_rate=33%.
6. **Persists across days/regimes?** opportunities span 7 day(s); see by_day / by_vol_regime tables.
7. **Killed by fees/spreads?** qualified opps after fees/buffer = 1030 of 3291 raw qualifying rows; fees/spread remove most candidates.
8. **Worth a staged shadow strategy later?** Maybe, but only as a STAGED shadow study with finer data; not paper/live.

## Regime / side breakdown (deduped opportunities)

**By side (YES=up-shock / NO=down-shock)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| NO | 642 | 162 | 213 | 426 | 33% | -0.0324 |
| YES | 388 | 127 | 115 | 272 | 30% | 0.0142 |

**By time-to-close**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| mid | 811 | 206 | 260 | 547 | 32% | -0.0218 |
| near-close | 137 | 101 | 26 | 111 | 19% | 0.0194 |
| near-open | 82 | 66 | 42 | 40 | 51% | -0.0031 |

**By line distance**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| far-line | 329 | 120 | 103 | 226 | 31% | -0.0323 |
| mid | 521 | 179 | 150 | 367 | 29% | -0.0123 |
| near-line | 180 | 93 | 75 | 105 | 42% | 0.0098 |

**By volatility regime (spot sigma terciles)**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| high-vol | 446 | 84 | 135 | 311 | 30% | -0.0470 |
| low-vol | 303 | 69 | 87 | 212 | 29% | -0.0167 |
| mid-vol | 281 | 70 | 106 | 175 | 38% | 0.0384 |

**By day/session**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| 20260605 | 135 | 20 | 45 | 90 | 33% | -0.0069 |
| 20260606 | 378 | 75 | 81 | 297 | 21% | -0.0332 |
| 20260607 | 410 | 94 | 143 | 267 | 35% | -0.0179 |
| 20260608 | 107 | 22 | 59 | 44 | 57% | 0.0543 |

**By Deribit regime**

| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |
|---|---:|---:|---:|---:|---:|---:|
| None | 1030 | 211 | 328 | 698 | 32% | -0.0148 |

## Deribit regime integration
- Deribit point-in-time fields present in events: **True** (joined per row)

## Polymarket reference (optional)
- classification: **not_comparable** — Polymarket book exists but is a different instrument; usable only as a loose reference for whether a venue reprices around BTC moves, NOT for cross-venue trading. No cross-venue logic implemented (out of scope).
  - window length differs: Kalshi KXBTC15M = 15-minute vs Polymarket btc-updown-5m = 5-minute
  - settlement source differs: Kalshi BRTI 60s-average (GTE) vs Polymarket Chainlink stream
  - start-reference/line capture differs (kalshi_target_price vs coinbase provisional)
  - different venue book microstructure and tick/fee model

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
