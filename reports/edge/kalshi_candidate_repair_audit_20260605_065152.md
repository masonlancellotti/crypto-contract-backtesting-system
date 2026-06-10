# Kalshi candidate-cohort repair audit — KXBTC15M

> STAGED / report-only. Re-runs the SAME edge policy on the edge-blocked cohort under each repaired probability. The calibration buffer for each source uses that source's OWN held-out TEST reliability — a better-calibrated source earns a smaller buffer; the buffer is NEVER removed. No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137
- market-shrink applied: base=platt alpha=0.5

| source | n | +raw | +cost_adj | **+unc_adj** | pass_final | med_final(c) | best_final(c) | med_calib_buf(c) | reduces_YES_overpred |
|---|---|---|---|---|---|---|---|---|---|
| current_promoted_calibrator | 137 | 137 | 137 | **2** | 1 | -14.70 | 2.35 | 16.55 | 0 |
| raw_model | 137 | 129 | 117 | **16** | 0 | -7.11 | 0.19 | 6.83 | 129 |
| identity | 137 | 129 | 117 | **16** | 0 | -7.11 | 0.19 | 6.83 | 129 |
| staged_platt | 137 | 118 | 117 | **0** | 0 | -8.40 | -3.03 | 8.73 | 117 |
| staged_isotonic | 137 | 91 | 42 | **4** | 0 | -5.57 | -1.46 | 1.60 | 136 |
| market_implied | 137 | 0 | 0 | **0** | 0 | -4.74 | -3.09 | 0.00 | 137 |
| market_shrunk | 137 | 122 | 41 | **0** | 0 | -4.33 | -3.06 | 1.54 | 137 |

## Verdict
- any REPAIRED source passes the FULL edge policy on the cohort: **False**  (best repaired final edge = 0.19c)
- any REPAIRED source yields positive UNCERTAINTY-ADJUSTED edge: **True**
- (reference: the unchanged promoted calibrator passes 1 row(s) — NOT a repair; shown for context only.)
- Honest reading: a better-calibrated source legitimately SHRINKS the buffer (lower bias) and reduces YES over-prediction, but that is only worth shadow testing if it ALSO clears the final profit gate with positive uncertainty-adjusted edge — NOT merely break-even, and NOT by removing the buffer.

## Safety
- STAGED/report-only; cohort re-evaluation only; no promotion; live disabled.
