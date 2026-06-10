# Kalshi trade-frequency report — KXBTC15M

**Score constantly; trade selectively. Frequency is earned from marginal net edge, not guessed. Distinct windows matter more than raw trade count.**

## 1. Data / gate status
- prob_source: microstructure  diagnostic/NON_TRADABLE: **True**
- gate_windows: 143  input: model_dataset_held_out_val

## 2. Candidate / trade counts
- candidates: 2004  distinct_windows: 31

## 3-4. Marginal trade curve
- cumulative net P&L peaks at rank 0/2004 (peak 0.0).
| bucket | trades | windows | cum_net_pnl | incr | hit |
|---|---|---|---|---|---|
| top_5_by_edge | 5 | 2 | -2.7300 | -2.7300 | 0.0000 |
| top_10_by_edge | 10 | 2 | -5.4400 | -2.7100 | 0.0000 |
| top_20_by_edge | 20 | 3 | -10.8500 | -5.4100 | 0.0000 |
| top_50_by_edge | 50 | 6 | -23.0100 | -12.1600 | 0.0600 |
| top_100_by_edge | 100 | 8 | -35.3200 | -12.3100 | 0.2000 |
| >=10c_edge | 312 | 13 | -42.5410 | None | 0.4744 |
| >=7c_edge | 452 | 15 | -27.5220 | None | 0.5487 |
| >=5c_edge | 605 | 19 | -21.9830 | None | 0.5620 |
| >=3c_edge | 843 | 25 | -33.7180 | None | 0.4887 |
| >=2c_edge | 1086 | 29 | -44.1920 | None | 0.4199 |
| >=1c_edge | 1433 | 31 | -60.7050 | None | 0.3552 |
- ⚠️ cumulative net P&L peaks at rank 0/2004 — trades beyond that reduced net P&L (marginal value turned negative).
- ⚠️ 2004 candidates across only 31 distinct windows (trades/window > 2) — raw trade count overstates independent evidence.

## 5. Time-to-close
| bucket | cand | exec | windows | net_pnl | hit |
|---|---|---|---|---|---|
| 15m-10m | 190 | 167 | 9 | -13.4400 | 0.4551 |
| 10m-5m | 651 | 409 | 20 | -18.2400 | 0.5061 |
| 5m-2m | 590 | 204 | 24 | -6.1060 | 0.3725 |
| 2m-60s | 141 | 75 | 19 | 0.6010 | 0.1600 |
| 60s-30s | 31 | 18 | 11 | 0.3970 | 0.1667 |
| 30s-10s | 13 | 7 | 4 | -0.1170 | 0.0000 |
| 10s-5s | 2 | 0 | 0 | 0.0000 | None |
| <5s | 0 | 0 | 0 | 0.0000 | None |

## 6-7. Within-window concentration / overtrading
- eligible candidates: 1086  distinct_windows: 29
  - max_1_entries_per_window: trades=29 windows=29 net_pnl=-0.9710 hit=0.3448
  - max_2_entries_per_window: trades=57 windows=29 net_pnl=-0.4580 hit=0.3509
  - max_3_entries_per_window: trades=85 windows=29 net_pnl=0.2950 hit=0.3529
  - unlimited_entries_per_window: trades=200 windows=6 net_pnl=-34.5880 hit=0.1700
- ⚠️ [CONCENTRATION] 1086 eligible candidates across 29 windows (=37.4/window); same-window trades are correlated (one label per window) — not independent samples.
- ⚠️ [EXTRA_TRADES_NO_GAIN] unlimited entries/window net P&L (-34.588) did not beat max-1/window (-0.971); extra within-window trades add risk without net benefit.

## (G) Frequency vs calibration
| prob | cand | mean_p | realized_yes | gap | net_pnl |
|---|---|---|---|---|---|
| 50-55% | 43 | 0.5233 | 0.5581 | -0.0348 | -0.5100 |
| 55-60% | 55 | 0.5717 | 0.7091 | -0.1374 | -14.6900 |
| 60-65% | 57 | 0.6225 | 0.7018 | -0.0792 | -2.8700 |
| 65-70% | 37 | 0.6741 | 0.7297 | -0.0556 | -3.9100 |
| 70-80% | 90 | 0.7525 | 0.5889 | 0.1636 | -13.1410 |
| 80-90% | 158 | 0.8608 | 0.5886 | 0.2722 | -12.4200 |
| 90-100% | 603 | 0.95 | 0.9436 | 0.0064 | -31.5420 |

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
