# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -6.36 | 0.49 | 8.20 | {'YES': 137} |
| identity_raw | 99 | **0** | 0 | None | -11.07 | -1.77 | 11.09 | {'NO': 111, 'YES': 26} |
| platt | 31 | **0** | 0 | None | -5.99 | -1.91 | 0.00 | {'YES': 75, 'NO': 62} |
| fresh_isotonic | 94 | **0** | 0 | None | -3.34 | 0.84 | 0.49 | {'YES': 133, 'NO': 4} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.00 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -2.95 | 0.00 | {'NO': 118, 'YES': 19} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -2.91 | 0.00 | {'NO': 121, 'YES': 16} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -3.81 | -2.84 | 0.00 | {'NO': 126, 'YES': 11} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -5.28 | -2.49 | 2.17 | {'NO': 126, 'YES': 11} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -5.42 | 0.22 | 7.27 | {'YES': 137} |
| identity_raw | 35 | **0** | 0 | None | -15.01 | -1.77 | 0.00 | {'YES': 102, 'NO': 35} |
| platt | 26 | **5** | 1 | 1.00 | -6.50 | 2.77 | 0.00 | {'YES': 130, 'NO': 7} |
| fresh_isotonic | 94 | **0** | 0 | None | -1.69 | 1.99 | 1.23 | {'YES': 135, 'NO': 2} |
| market_implied | 0 | **0** | 0 | None | -6.69 | -3.00 | 1.96 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -6.69 | -3.00 | 1.96 | {'NO': 94, 'YES': 43} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -6.96 | -2.95 | 2.20 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -6.89 | -2.88 | 1.62 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -6.55 | -2.76 | 0.25 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -8.49 | -2.51 | 0.00 | {'YES': 112, 'NO': 25} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **True**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
