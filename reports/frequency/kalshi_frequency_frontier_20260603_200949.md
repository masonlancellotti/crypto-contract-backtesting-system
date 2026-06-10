# Kalshi trade-frequency report — KXBTC15M

**Score constantly; trade selectively. Frequency is earned from marginal net edge, not guessed. Distinct windows matter more than raw trade count.**

## 1. Data / gate status
- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**
- gate_windows: 187  input: model_dataset_held_out_val

## 2. Candidate / trade counts
- candidates: 3135  distinct_windows: 45

## 3-4. Marginal trade curve
- cumulative net P&L peaks at rank 1095/3135 (peak 83.985).
| bucket | trades | windows | cum_net_pnl | incr | hit |
|---|---|---|---|---|---|
| top_5_by_edge | 5 | 2 | 2.4700 | 2.4700 | 1.0000 |
| top_10_by_edge | 10 | 4 | 4.3700 | 1.9000 | 1.0000 |
| top_20_by_edge | 20 | 4 | 8.6700 | 4.3000 | 1.0000 |
| top_50_by_edge | 50 | 6 | 21.2400 | 12.5700 | 1.0000 |
| top_100_by_edge | 100 | 9 | 32.0900 | 10.8500 | 0.9200 |
| >=10c_edge | 313 | 20 | 48.3400 | None | 0.7796 |
| >=7c_edge | 573 | 27 | 54.5800 | None | 0.7400 |
| >=5c_edge | 803 | 34 | 68.4530 | None | 0.7335 |
| >=3c_edge | 1218 | 40 | 77.8890 | None | 0.6773 |
| >=2c_edge | 1558 | 44 | 78.1630 | None | 0.6130 |
| >=1c_edge | 2051 | 45 | 73.7890 | None | 0.5246 |
- ⚠️ cumulative net P&L peaks at rank 1095/3135 — trades beyond that reduced net P&L (marginal value turned negative).
- ⚠️ 3135 candidates across only 45 distinct windows (trades/window > 2) — raw trade count overstates independent evidence.

## 5. Time-to-close
| bucket | cand | exec | windows | net_pnl | hit |
|---|---|---|---|---|---|
| 15m-10m | 301 | 207 | 14 | 40.9500 | 0.6957 |
| 10m-5m | 959 | 507 | 26 | 24.4300 | 0.7298 |
| 5m-2m | 892 | 356 | 38 | -2.4190 | 0.5758 |
| 2m-60s | 289 | 127 | 33 | 6.8490 | 0.3543 |
| 60s-30s | 77 | 40 | 18 | 0.5120 | 0.2750 |
| 30s-10s | 38 | 19 | 9 | 0.5000 | 0.1579 |
| 10s-5s | 2 | 2 | 2 | 0.0880 | 0.5000 |
| <5s | 0 | 0 | 0 | 0.0000 | None |

## 6-7. Within-window concentration / overtrading
- eligible candidates: 1558  distinct_windows: 44
  - max_1_entries_per_window: trades=44 windows=44 net_pnl=1.9090 hit=0.5455
  - max_2_entries_per_window: trades=87 windows=44 net_pnl=2.9980 hit=0.5402
  - max_3_entries_per_window: trades=100 windows=34 net_pnl=3.4080 hit=0.5100
  - unlimited_entries_per_window: trades=100 windows=7 net_pnl=-3.1150 hit=0.2500
- ⚠️ [CONCENTRATION] 1558 eligible candidates across 44 windows (=35.4/window); same-window trades are correlated (one label per window) — not independent samples.
- ⚠️ [EXTRA_TRADES_NO_GAIN] unlimited entries/window net P&L (-3.115) did not beat max-1/window (1.909); extra within-window trades add risk without net benefit.

## (G) Frequency vs calibration
| prob | cand | mean_p | realized_yes | gap | net_pnl |
|---|---|---|---|---|---|
| 50-55% | 50 | 0.5242 | 0.42 | 0.1042 | 10.7600 |
| 55-60% | 78 | 0.5783 | 0.5385 | 0.0399 | 9.0600 |
| 60-65% | 107 | 0.626 | 0.5981 | 0.0279 | -1.5000 |
| 65-70% | 76 | 0.6735 | 0.5263 | 0.1472 | -0.1600 |
| 70-80% | 193 | 0.7491 | 0.6269 | 0.1222 | -4.4100 |
| 80-90% | 317 | 0.8565 | 0.7855 | 0.071 | -20.8000 |
| 90-100% | 689 | 0.947 | 0.9884 | -0.0414 | -11.6590 |

## 8. Conservative recommended paper-policy settings (NOT promoted)
- {"min_net_edge_cents": 5, "max_trades_per_window": 1, "cooldown_after_entry_seconds": 30, "min_seconds_to_close": 30, "max_book_age_ms": 1000, "min_depth": 1, "max_spread_cents": 5, "max_daily_trades": 10}
- rationale: Trade selectively: one entry per window (same-window trades are correlated), a high net-edge floor, a post-entry cooldown, and a daily cap. Frequency must be earned by marginal net edge, not maximized.

## 9. Aggressive settings (EXPERIMENTAL — paper validation required, not promoted)
- e.g. min_net_edge_cents=2, max_trades_per_window=2, cooldown=5s — test in paper only.

## 10. Explicit statement
- No settings are promoted. No live trading enabled. Recommendations require paper validation.

## Safety
- RESEARCH EVIDENCE ONLY: no orders, no PAPER_CANDIDATE, no live trading.
- No policy is promoted; recommendations require manual review + paper validation.
- Distinct windows matter more than raw trade count (one label per 15m window).
- Score constantly; trade only when marginal net edge (after fees/executable prices) is positive.
