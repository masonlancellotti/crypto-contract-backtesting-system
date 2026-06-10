# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 601  executable_rows: 553  iterations: 5444  elapsed_s: 3600.29
- split(windows): {'n_windows': 725, 'train_windows': 362, 'calib_windows': 181, 'test_windows': 180, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MISSING_BOOK': 48, 'INSUFFICIENT_DEPTH': 48, 'MARKET_CLOSED': 22, 'FEATURE_ROW_STALE': 15, 'TOO_CLOSE_TO_CLOSE': 11}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 553 | 187 | **0** | 3.65 | -2.42 | -4.42 | 1.18 | 0.00 | {'NO': 351, 'YES': 202} | 4.76 |
| identity_raw | 553 | 408 | **0** | 13.04 | -2.59 | -4.59 | 1.75 | 5.76 | {'NO': 447, 'YES': 106} | 11.99 |
| platt | 553 | 319 | **1** | 6.57 | -2.06 | -4.06 | 2.25 | 0.83 | {'NO': 390, 'YES': 163} | 7.14 |
| market_implied | 553 | 0 | **0** | -0.49 | -2.50 | -4.50 | -3.02 | 0.00 | {'NO': 343, 'YES': 210} | 0.00 |
| market_shrunk_a0.0 | 553 | 0 | **0** | -0.49 | -2.50 | -4.50 | -3.02 | 0.00 | {'NO': 343, 'YES': 210} | 0.00 |
| market_shrunk_a0.05 | 553 | 0 | **0** | 0.04 | -2.11 | -4.11 | -3.04 | 0.00 | {'NO': 414, 'YES': 139} | 0.60 |
| market_shrunk_a0.1 | 553 | 0 | **0** | 0.70 | -1.74 | -3.74 | -2.99 | 0.00 | {'NO': 427, 'YES': 126} | 1.20 |
| market_shrunk_a0.2 | 553 | 0 | **0** | 2.05 | -1.51 | -3.51 | -2.03 | 0.00 | {'NO': 478, 'YES': 75} | 2.40 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 547, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 472, 'RAW_EDGE_BELOW_MIN': 366, 'COST_ADJUSTED_EDGE_BELOW_MIN': 291}  buckets={'[0.0,0.1)': 121, '[0.4,0.5)': 104, '[0.3,0.4)': 82, '[0.1,0.2)': 63, '[0.5,0.6)': 42, '[0.7,0.8)': 41, '[0.6,0.7)': 41, '[0.2,0.3)': 39, '[0.9,1.0)': 12, '[0.8,0.9)': 8}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 545, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 514, 'RAW_EDGE_BELOW_MIN': 145, 'COST_ADJUSTED_EDGE_BELOW_MIN': 117, 'MODEL_DISAGREEMENT_TOO_HIGH': 72}  buckets={'[0.0,0.1)': 203, '[0.2,0.3)': 84, '[0.3,0.4)': 82, '[0.1,0.2)': 74, '[0.4,0.5)': 55, '[0.5,0.6)': 26, '[0.9,1.0)': 12, '[0.8,0.9)': 10, '[0.7,0.8)': 4, '[0.6,0.7)': 3}
- **platt**: reasons={'EDGE_BELOW_MIN': 552, 'PRICE_ABOVE_RESERVATION': 526, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 421, 'RAW_EDGE_BELOW_MIN': 234, 'COST_ADJUSTED_EDGE_BELOW_MIN': 211, 'EDGE_OK': 1}  buckets={'[0.1,0.2)': 200, '[0.2,0.3)': 78, '[0.3,0.4)': 78, '[0.4,0.5)': 65, '[0.5,0.6)': 64, '[0.6,0.7)': 27, '[0.9,1.0)': 22, '[0.7,0.8)': 15, '[0.8,0.9)': 4}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 553, 'COST_ADJUSTED_EDGE_BELOW_MIN': 553, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 553, 'EDGE_BELOW_MIN': 553}  buckets={'[0.0,0.1)': 120, '[0.4,0.5)': 109, '[0.5,0.6)': 106, '[0.3,0.4)': 63, '[0.1,0.2)': 50, '[0.2,0.3)': 50, '[0.6,0.7)': 29, '[0.9,1.0)': 14, '[0.8,0.9)': 6, '[0.7,0.8)': 6}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 553, 'COST_ADJUSTED_EDGE_BELOW_MIN': 553, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 553, 'EDGE_BELOW_MIN': 553}  buckets={'[0.0,0.1)': 120, '[0.4,0.5)': 109, '[0.5,0.6)': 106, '[0.3,0.4)': 63, '[0.1,0.2)': 50, '[0.2,0.3)': 50, '[0.6,0.7)': 29, '[0.9,1.0)': 14, '[0.8,0.9)': 6, '[0.7,0.8)': 6}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 553, 'COST_ADJUSTED_EDGE_BELOW_MIN': 553, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 553, 'EDGE_BELOW_MIN': 553}  buckets={'[0.0,0.1)': 120, '[0.4,0.5)': 115, '[0.5,0.6)': 97, '[0.3,0.4)': 68, '[0.2,0.3)': 55, '[0.1,0.2)': 50, '[0.6,0.7)': 22, '[0.9,1.0)': 14, '[0.8,0.9)': 6, '[0.7,0.8)': 6}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 553, 'COST_ADJUSTED_EDGE_BELOW_MIN': 553, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 553, 'EDGE_BELOW_MIN': 553}  buckets={'[0.4,0.5)': 122, '[0.0,0.1)': 120, '[0.5,0.6)': 88, '[0.3,0.4)': 68, '[0.1,0.2)': 55, '[0.2,0.3)': 54, '[0.6,0.7)': 20, '[0.9,1.0)': 14, '[0.8,0.9)': 6, '[0.7,0.8)': 6}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 553, 'COST_ADJUSTED_EDGE_BELOW_MIN': 553, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 553, 'PRICE_ABOVE_RESERVATION': 553, 'EDGE_BELOW_MIN': 553}  buckets={'[0.0,0.1)': 122, '[0.4,0.5)': 110, '[0.3,0.4)': 82, '[0.5,0.6)': 79, '[0.1,0.2)': 64, '[0.2,0.3)': 52, '[0.6,0.7)': 18, '[0.9,1.0)': 14, '[0.8,0.9)': 6, '[0.7,0.8)': 6}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **True**  (best repaired final = 2.25c)
- promoted-isotonic reference passes 0 row(s) (not a repair).
- **recommendation: ['platt'] cleared the final edge gate on real shadow rows WITHOUT weakening it — mark STAGED_SHADOW_CANDIDATE and review (calibration + concentration) before any promotion. Do NOT promote here.**
- STAGED_SHADOW_CANDIDATE: ['platt'] (marked STAGED only; NOT promoted; requires a separate review).

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260610_043512.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260610_043513.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260610_043513.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260610_043513.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260610_043513.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260610_043513.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
