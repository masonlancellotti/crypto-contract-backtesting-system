# Kalshi candidate-cohort repair audit — KXBTC15M

> STAGED / report-only. Re-runs the SAME edge policy on the edge-blocked cohort under each repaired probability. The calibration buffer for each source uses that source's OWN held-out TEST reliability — a better-calibrated source earns a smaller buffer; the buffer is NEVER removed. No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_compare_20260605_064333_decisions.jsonl`  cohort_rows: 0
- market-shrink applied: base=platt alpha=0.5

| source | n | +raw | +cost_adj | **+unc_adj** | pass_final | med_final(c) | best_final(c) | med_calib_buf(c) | reduces_YES_overpred |
|---|---|---|---|---|---|---|---|---|---|
| current_promoted_calibrator | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| raw_model | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| identity | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| staged_platt | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| staged_isotonic | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| market_implied | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |
| market_shrunk | 0 | 0 | 0 | **0** | 0 | None | None | None | 0 |

## Verdict
- any REPAIRED source passes the FULL edge policy on the cohort: **False**  (best repaired final edge = Nonec)
- any REPAIRED source yields positive UNCERTAINTY-ADJUSTED edge: **False**
- (reference: the unchanged promoted calibrator passes 0 row(s) — NOT a repair; shown for context only.)
- Honest reading: a better-calibrated source legitimately SHRINKS the buffer (lower bias) and reduces YES over-prediction, but that is only worth shadow testing if it ALSO clears the final profit gate with positive uncertainty-adjusted edge — NOT merely break-even, and NOT by removing the buffer.

## Safety
- STAGED/report-only; cohort re-evaluation only; no promotion; live disabled.
