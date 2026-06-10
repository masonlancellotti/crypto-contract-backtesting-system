# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -13.66 | -2.73 | 15.51 | {'YES': 137} |
| identity_raw | 100 | **0** | 0 | None | -4.59 | -0.18 | 4.30 | {'NO': 125, 'YES': 12} |
| platt | 117 | **0** | 0 | None | -1.46 | 1.81 | 3.42 | {'NO': 125, 'YES': 12} |
| fresh_isotonic | 117 | **0** | 0 | None | -1.27 | 2.17 | 4.84 | {'NO': 124, 'YES': 13} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.23 | 0.00 | {'NO': 130, 'YES': 7} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.23 | 0.00 | {'NO': 130, 'YES': 7} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -3.02 | 0.00 | {'NO': 134, 'YES': 3} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -2.95 | 0.00 | {'NO': 135, 'YES': 2} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -3.82 | -2.82 | 0.00 | {'NO': 135, 'YES': 2} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -3.02 | -2.18 | 0.00 | {'NO': 133, 'YES': 4} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 136 | **0** | 0 | None | -10.85 | -1.52 | 12.70 | {'YES': 136, 'NO': 1} |
| identity_raw | 68 | **0** | 0 | None | -13.49 | -1.77 | 2.45 | {'NO': 70, 'YES': 67} |
| platt | 99 | **0** | 0 | None | -18.07 | -1.32 | 21.24 | {'NO': 101, 'YES': 36} |
| fresh_isotonic | 97 | **0** | 0 | None | -18.36 | -1.51 | 22.94 | {'NO': 99, 'YES': 38} |
| market_implied | 0 | **0** | 0 | None | -6.50 | -3.00 | 1.77 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -6.50 | -3.00 | 1.77 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -6.48 | -2.95 | 1.99 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -6.82 | -2.88 | 2.59 | {'NO': 92, 'YES': 45} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -6.84 | -2.76 | 3.15 | {'NO': 85, 'YES': 52} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -7.83 | -2.51 | 0.00 | {'YES': 78, 'NO': 59} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **False**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
