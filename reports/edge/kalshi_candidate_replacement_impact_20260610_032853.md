# Kalshi candidate replacement impact — KXBTC15M

> STAGED / report-only. Edge-blocked cohort re-scored under each calibrator with BOTH row- and window-based calibration buffers (window = honest, WIDER). No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137

## reliability_unit = row
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -4.40 | 0.19 | 5.74 | {'YES': 137} |
| identity_raw | 80 | **0** | 0 | None | -12.83 | -1.77 | 13.18 | {'NO': 91, 'YES': 46} |
| platt | 32 | **0** | 0 | None | -3.84 | 0.02 | 0.00 | {'YES': 123, 'NO': 14} |
| fresh_isotonic | 132 | **0** | 0 | None | -6.00 | -1.64 | 8.27 | {'YES': 136, 'NO': 1} |
| market_implied | 0 | **0** | 0 | None | -4.74 | -3.02 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -4.74 | -3.02 | 0.00 | {'NO': 119, 'YES': 18} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -4.51 | -3.02 | 0.00 | {'NO': 120, 'YES': 17} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -4.28 | -3.04 | 0.00 | {'NO': 125, 'YES': 12} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -4.71 | -2.82 | 0.91 | {'NO': 123, 'YES': 14} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -7.00 | -2.49 | 3.84 | {'NO': 108, 'YES': 29} |

## reliability_unit = window
| calibrator | candidate-like | **pass_final** | distinct_pass_windows | top1_win_share | med_final(c) | best_final(c) | med_calib_buf(c) | side |
|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 137 | **0** | 0 | None | -3.86 | 1.47 | 5.71 | {'YES': 137} |
| identity_raw | 30 | **0** | 0 | None | -15.01 | -1.77 | 0.00 | {'YES': 107, 'NO': 30} |
| platt | 32 | **13** | 1 | 1.00 | -2.93 | 4.08 | 0.00 | {'YES': 137} |
| fresh_isotonic | 132 | **2** | 1 | 1.00 | -1.80 | 2.46 | 3.50 | {'YES': 137} |
| market_implied | 0 | **0** | 0 | None | -6.36 | -3.00 | 2.14 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.0 | 0 | **0** | 0 | None | -6.36 | -3.00 | 2.14 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.05 | 0 | **0** | 0 | None | -5.26 | -2.95 | 0.49 | {'YES': 133, 'NO': 4} |
| market_shrunk_a0.1 | 0 | **0** | 0 | None | -5.32 | -2.88 | 0.00 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.2 | 0 | **0** | 0 | None | -6.37 | -2.76 | 0.00 | {'YES': 134, 'NO': 3} |
| market_shrunk_a0.4 | 0 | **0** | 0 | None | -8.49 | -2.51 | 0.00 | {'YES': 123, 'NO': 14} |

## Verdict
- any REPAIRED calibrator clears the final +edge gate — row unit: **False**, window unit: **True**.
- Per BUCKET (see the replacement-review report), the distinct-window Wilson interval is WIDER in the mid/high-probability buckets where YES over-prediction lives (Kish effective n ~100–150 vs thousands of rows), so window reliability only ever TIGHTENS the gate, never loosens it — confirming row-based intervals are too optimistic. (Cohort-median buffers also shift because the selected side changes under window mode.)

## Safety
- No promotion; buffers never removed; live/paper disabled.
