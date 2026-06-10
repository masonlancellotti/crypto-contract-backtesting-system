# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -7.38 | -1.46 | 8.93 | {'YES': 137} |
| identity_raw | 100 | **0** | 0 | None | -10.48 | -1.77 | 10.42 | {'NO': 115, 'YES': 22} |
| platt | 104 | **0** | 0 | None | -8.38 | -1.31 | 8.25 | {'NO': 107, 'YES': 30} |
| fresh_isotonic | 3 | **0** | 0 | None | -5.84 | -1.45 | 0.00 | {'NO': 49, 'YES': 88} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -2.95 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -2.88 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -3.81 | -2.76 | 0.00 | {'NO': 122, 'YES': 15} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -4.90 | -2.51 | 1.87 | {'NO': 124, 'YES': 13} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -6.58 | 0.13 | 8.43 | {'YES': 137} |
| identity_raw | 42 | **0** | 0 | None | -15.01 | -1.77 | 0.00 | {'YES': 94, 'NO': 43} |
| platt | 44 | **0** | 0 | None | -15.53 | 0.60 | 0.00 | {'YES': 100, 'NO': 37} |
| fresh_isotonic | 2 | **0** | 0 | None | -6.43 | -1.45 | 0.00 | {'YES': 134, 'NO': 3} |
| market_implied | 0 | **0** | 0 | None | -6.98 | -3.00 | 2.25 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -6.98 | -3.00 | 2.25 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -7.43 | -2.95 | 2.67 | {'YES': 115, 'NO': 22} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -7.29 | -2.88 | 2.02 | {'YES': 130, 'NO': 7} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -7.03 | -2.76 | 0.76 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -8.49 | -2.51 | 0.00 | {'YES': 107, 'NO': 30} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **False**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
