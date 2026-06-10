# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **replay**  rows_read: 394  executable_rows: 394  iterations: 1  elapsed_s: 0.0
- split(windows): {'n_windows': 303, 'train_windows': 152, 'calib_windows': 76, 'test_windows': 73, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 394 | 171 | **0** | 1.10 | -9.33 | -11.33 | -1.22 | 0.00 | {'YES': 197, 'NO': 197} | 6.36 |
| identity_raw | 394 | 285 | **0** | 7.91 | -1.07 | -3.07 | 1.88 | 3.73 | {'NO': 339, 'YES': 55} | 8.32 |
| platt | 394 | 332 | **0** | 8.92 | -2.30 | -4.30 | 1.88 | 5.73 | {'NO': 360, 'YES': 34} | 10.36 |
| market_implied | 394 | 0 | **0** | -0.74 | -2.71 | -4.71 | -3.09 | 0.00 | {'NO': 340, 'YES': 54} | 0.00 |
| market_shrunk_a0.0 | 394 | 0 | **0** | -0.74 | -2.71 | -4.71 | -3.09 | 0.00 | {'NO': 340, 'YES': 54} | 0.00 |
| market_shrunk_a0.05 | 394 | 0 | **0** | -0.31 | -2.41 | -4.41 | -2.97 | 0.00 | {'NO': 340, 'YES': 54} | 0.42 |
| market_shrunk_a0.1 | 394 | 0 | **0** | 0.02 | -2.10 | -4.10 | -2.85 | 0.00 | {'NO': 340, 'YES': 54} | 0.83 |
| market_shrunk_a0.2 | 394 | 0 | **0** | 0.89 | -1.62 | -3.62 | -2.61 | 0.00 | {'NO': 340, 'YES': 54} | 1.66 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 390, 'RAW_EDGE_BELOW_MIN': 223, 'COST_ADJUSTED_EDGE_BELOW_MIN': 213, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.3,0.4)': 175, '[0.2,0.3)': 83, '[0.9,1.0)': 47, '[0.1,0.2)': 40, '[0.4,0.5)': 25, '[0.0,0.1)': 14, '[0.8,0.9)': 7, '[0.7,0.8)': 2, '[0.5,0.6)': 1}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 364, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 277, 'RAW_EDGE_BELOW_MIN': 109, 'COST_ADJUSTED_EDGE_BELOW_MIN': 76, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.1,0.2)': 211, '[0.0,0.1)': 91, '[0.9,1.0)': 47, '[0.2,0.3)': 30, '[0.8,0.9)': 7, '[0.3,0.4)': 6, '[0.5,0.6)': 2}
- **platt**: reasons={'EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 392, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 345, 'RAW_EDGE_BELOW_MIN': 62, 'COST_ADJUSTED_EDGE_BELOW_MIN': 30, 'MODEL_DISAGREEMENT_TOO_HIGH': 7}  buckets={'[0.1,0.2)': 251, '[0.0,0.1)': 72, '[0.9,1.0)': 40, '[0.2,0.3)': 15, '[0.8,0.9)': 14, '[0.4,0.5)': 1, '[0.5,0.6)': 1}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 394, 'COST_ADJUSTED_EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.2,0.3)': 184, '[0.1,0.2)': 74, '[0.9,1.0)': 45, '[0.3,0.4)': 34, '[0.0,0.1)': 32, '[0.4,0.5)': 14, '[0.8,0.9)': 9, '[0.5,0.6)': 1, '[0.6,0.7)': 1}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 394, 'COST_ADJUSTED_EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.2,0.3)': 184, '[0.1,0.2)': 74, '[0.9,1.0)': 45, '[0.3,0.4)': 34, '[0.0,0.1)': 32, '[0.4,0.5)': 14, '[0.8,0.9)': 9, '[0.5,0.6)': 1, '[0.6,0.7)': 1}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 394, 'COST_ADJUSTED_EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.2,0.3)': 185, '[0.1,0.2)': 74, '[0.9,1.0)': 45, '[0.3,0.4)': 34, '[0.0,0.1)': 32, '[0.4,0.5)': 13, '[0.8,0.9)': 9, '[0.5,0.6)': 1, '[0.6,0.7)': 1}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 394, 'COST_ADJUSTED_EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.2,0.3)': 180, '[0.1,0.2)': 86, '[0.9,1.0)': 45, '[0.0,0.1)': 32, '[0.3,0.4)': 27, '[0.4,0.5)': 13, '[0.8,0.9)': 9, '[0.5,0.6)': 1, '[0.6,0.7)': 1}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 394, 'COST_ADJUSTED_EDGE_BELOW_MIN': 394, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 394, 'PRICE_ABOVE_RESERVATION': 394, 'EDGE_BELOW_MIN': 394, 'STALE_QUOTE_BUFFER_APPLIED': 2}  buckets={'[0.2,0.3)': 166, '[0.1,0.2)': 102, '[0.9,1.0)': 45, '[0.0,0.1)': 34, '[0.3,0.4)': 29, '[0.8,0.9)': 9, '[0.4,0.5)': 7, '[0.5,0.6)': 1, '[0.6,0.7)': 1}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **False**  (best repaired final = 1.88c)
- promoted-isotonic reference passes 0 row(s) (not a repair).
- **recommendation: NO repaired source clears the +final edge gate. Repair improves calibration but does not manufacture tradable edge — continue DATA COLLECTION and periodic RETRAINING/RECALIBRATION only; do not lower thresholds, do not remove buffers, do not promote.**

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260605_072947.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260605_072947.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260605_072947.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260605_072947.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260605_072947.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260605_072947.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
