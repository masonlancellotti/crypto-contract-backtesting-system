# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -4.12 | -0.23 | 5.46 | {'YES': 137} |
| identity_raw | 78 | **0** | 0 | None | -13.09 | -1.77 | 13.52 | {'NO': 89, 'YES': 48} |
| platt | 32 | **0** | 0 | None | -3.56 | 0.11 | 0.00 | {'YES': 131, 'NO': 6} |
| fresh_isotonic | 132 | **0** | 0 | None | -5.42 | -1.22 | 8.29 | {'YES': 136, 'NO': 1} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 118, 'YES': 19} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 118, 'YES': 19} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -2.95 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -2.88 | 0.00 | {'NO': 121, 'YES': 16} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -5.20 | -2.93 | 1.41 | {'NO': 114, 'YES': 23} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -7.29 | -2.64 | 4.05 | {'NO': 102, 'YES': 35} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **1** | 1 | 1.00 | -3.47 | 2.18 | 5.31 | {'YES': 137} |
| identity_raw | 28 | **0** | 0 | None | -15.01 | -1.77 | 0.00 | {'YES': 109, 'NO': 28} |
| platt | 32 | **13** | 1 | 1.00 | -2.71 | 4.08 | 0.00 | {'YES': 137} |
| fresh_isotonic | 132 | **0** | 0 | None | -2.06 | 1.98 | 4.54 | {'YES': 137} |
| market_implied | 0 | **0** | 0 | None | -5.81 | -3.00 | 1.60 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -5.81 | -3.00 | 1.60 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.78 | -2.95 | 0.00 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -5.32 | -2.88 | 0.00 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -6.37 | -2.76 | 0.00 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -8.49 | -2.51 | 0.00 | {'YES': 128, 'NO': 9} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **True**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
