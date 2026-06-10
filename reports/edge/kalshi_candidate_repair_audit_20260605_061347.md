# Kalshi candidate-cohort repair audit — KXBTC15M

> STAGED / report-only. Re-runs the SAME edge policy on the edge-blocked cohort under each repaired probability. The calibration buffer for each source uses that source's OWN held-out TEST reliability — a better-calibrated source earns a smaller buffer; the buffer is NEVER removed. No promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  cohort_rows: 137
- market-shrink applied: base=platt alpha=0.4

| source | n | +raw | +cost_adj | **+unc_adj** | pass_final | med_final(c) | best_final(c) | med_calib_buf(c) | reduces_YES_overpred |
|---|---|---|---|---|---|---|---|---|---|
| current_promoted_calibrator | 137 | 137 | 137 | **2** | 1 | -13.94 | 3.97 | 15.79 | 0 |
| raw_model | 137 | 127 | 117 | **16** | 0 | -6.34 | 0.19 | 6.03 | 128 |
| identity | 137 | 127 | 117 | **16** | 0 | -6.34 | 0.19 | 6.03 | 128 |
| staged_platt | 137 | 125 | 121 | **7** | 0 | -8.92 | -0.30 | 10.00 | 109 |
| staged_isotonic | 137 | 77 | 35 | **2** | 0 | -6.47 | -1.68 | 0.00 | 49 |
| market_implied | 137 | 0 | 0 | **0** | 0 | -4.74 | -3.09 | 0.00 | 136 |
| market_shrunk | 137 | 123 | 22 | **0** | 0 | -4.02 | -2.96 | 0.96 | 136 |

## Verdict
- any source passes the FULL edge policy on the cohort: **True**
- any source yields positive UNCERTAINTY-ADJUSTED edge: **True**
- A source is only worth shadow testing if it (a) improves held-out calibration AND (b) earns positive uncertainty-adjusted edge via genuinely lower bias — NOT by buffer removal.

## Safety
- STAGED/report-only; cohort re-evaluation only; no promotion; live disabled.
