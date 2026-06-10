# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 31  executable_rows: 17  iterations: 87  elapsed_s: 60.26
- split(windows): {'n_windows': 300, 'train_windows': 150, 'calib_windows': 75, 'test_windows': 73, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MARKET_CLOSED': 14, 'MISSING_BOOK': 14, 'INSUFFICIENT_DEPTH': 14, 'FEATURE_ROW_STALE': 14}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 17 | 7 | **0** | 3.70 | -0.45 | -2.45 | 1.87 | 1.20 | {'YES': 17} | 5.80 |
| identity_raw | 17 | 1 | **0** | 0.70 | -0.88 | -2.88 | 0.62 | 0.00 | {'YES': 17} | 2.25 |
| platt | 17 | 9 | **0** | 5.34 | -7.05 | -9.05 | -1.34 | 9.43 | {'YES': 6, 'NO': 11} | 4.75 |
| market_implied | 17 | 0 | **0** | -0.28 | -1.29 | -3.29 | -3.09 | 0.00 | {'YES': 16, 'NO': 1} | 0.00 |
| market_shrunk_a0.0 | 17 | 0 | **0** | -0.28 | -1.29 | -3.29 | -3.09 | 0.00 | {'YES': 16, 'NO': 1} | 0.00 |
| market_shrunk_a0.05 | 17 | 0 | **0** | -0.32 | -1.34 | -3.34 | -3.04 | 0.00 | {'YES': 17} | 0.11 |
| market_shrunk_a0.1 | 17 | 0 | **0** | -0.14 | -1.33 | -3.33 | -2.98 | 0.00 | {'YES': 17} | 0.23 |
| market_shrunk_a0.2 | 17 | 0 | **0** | -0.09 | -1.27 | -3.27 | -2.87 | 0.00 | {'YES': 17} | 0.45 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 14, 'RAW_EDGE_BELOW_MIN': 10, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 9, 'COST_ADJUSTED_EDGE_BELOW_MIN': 1}  buckets={'[0.9,1.0)': 17}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 17, 'RAW_EDGE_BELOW_MIN': 16, 'PRICE_ABOVE_RESERVATION': 16, 'COST_ADJUSTED_EDGE_BELOW_MIN': 11, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 11}  buckets={'[0.9,1.0)': 17}
- **platt**: reasons={'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 16, 'RAW_EDGE_BELOW_MIN': 8, 'COST_ADJUSTED_EDGE_BELOW_MIN': 5}  buckets={'[0.9,1.0)': 12, '[0.8,0.9)': 5}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 17, 'COST_ADJUSTED_EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17}  buckets={'[0.9,1.0)': 14, '[0.8,0.9)': 3}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 17, 'COST_ADJUSTED_EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17}  buckets={'[0.9,1.0)': 14, '[0.8,0.9)': 3}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 17, 'COST_ADJUSTED_EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17}  buckets={'[0.9,1.0)': 14, '[0.8,0.9)': 3}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 17, 'COST_ADJUSTED_EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17}  buckets={'[0.9,1.0)': 14, '[0.8,0.9)': 3}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 17, 'COST_ADJUSTED_EDGE_BELOW_MIN': 17, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 17, 'PRICE_ABOVE_RESERVATION': 17, 'EDGE_BELOW_MIN': 17}  buckets={'[0.9,1.0)': 14, '[0.8,0.9)': 3}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **False**  (best repaired final = 0.62c)
- promoted-isotonic reference passes 0 row(s) (not a repair).
- **recommendation: NO repaired source clears the +final edge gate. Repair improves calibration but does not manufacture tradable edge — continue DATA COLLECTION and periodic RETRAINING/RECALIBRATION only; do not lower thresholds, do not remove buffers, do not promote.**

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260605_064333.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260605_064333.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260605_064333.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260605_064333.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260605_064333.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260605_064333.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
