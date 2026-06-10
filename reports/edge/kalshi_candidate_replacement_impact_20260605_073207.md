# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -14.59 | -5.21 | 16.43 | {'YES': 137} |
| identity_raw | 100 | **0** | 0 | None | -4.05 | 0.19 | 3.73 | {'NO': 127, 'YES': 10} |
| platt | 108 | **0** | 0 | None | -5.26 | -0.33 | 5.73 | {'NO': 125, 'YES': 12} |
| fresh_isotonic | 97 | **0** | 0 | None | -3.24 | -0.21 | 2.73 | {'NO': 126, 'YES': 11} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.09 | 0.00 | {'NO': 137} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.09 | 0.00 | {'NO': 137} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -3.02 | 0.00 | {'NO': 137} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -2.95 | 0.00 | {'NO': 137} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -3.83 | -2.82 | 0.00 | {'NO': 137} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -3.02 | -2.18 | 0.00 | {'NO': 136, 'YES': 1} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 136 | **0** | 0 | None | -11.15 | -1.92 | 12.99 | {'YES': 136, 'NO': 1} |
| identity_raw | 68 | **0** | 0 | None | -13.59 | -1.77 | 1.93 | {'NO': 70, 'YES': 67} |
| platt | 71 | **0** | 0 | None | -16.43 | 0.38 | 0.00 | {'NO': 68, 'YES': 69} |
| fresh_isotonic | 87 | **0** | 0 | None | -13.06 | -0.09 | 14.07 | {'NO': 84, 'YES': 53} |
| market_implied | 0 | **0** | 0 | None | -6.13 | -3.00 | 1.39 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -6.13 | -3.00 | 1.39 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -6.12 | -2.95 | 1.60 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -6.53 | -2.88 | 2.28 | {'NO': 92, 'YES': 45} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -6.66 | -2.76 | 2.88 | {'NO': 85, 'YES': 52} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -7.40 | -2.51 | 0.00 | {'YES': 78, 'NO': 59} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **False**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
