# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 764  executable_rows: 708  iterations: 5069  elapsed_s: 3600.22
- split(windows): {'n_windows': 509, 'train_windows': 254, 'calib_windows': 127, 'test_windows': 126, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MISSING_BOOK': 54, 'INSUFFICIENT_DEPTH': 54, 'MARKET_CLOSED': 18, 'FEATURE_ROW_STALE': 14, 'TOO_CLOSE_TO_CLOSE': 12}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 708 | 240 | **8** | 2.99 | -2.32 | -4.32 | 4.22 | 0.00 | {'YES': 311, 'NO': 397} | 4.79 |
| identity_raw | 708 | 359 | **4** | 5.15 | -1.69 | -3.69 | 5.98 | 2.62 | {'YES': 223, 'NO': 485} | 7.72 |
| platt | 708 | 385 | **5** | 5.55 | -1.56 | -3.56 | 2.60 | 2.74 | {'YES': 275, 'NO': 433} | 8.23 |
| market_implied | 708 | 0 | **0** | -0.56 | -2.44 | -4.44 | -3.00 | 0.00 | {'YES': 363, 'NO': 345} | 0.00 |
| market_shrunk_a0.0 | 708 | 0 | **0** | -0.56 | -2.44 | -4.44 | -3.00 | 0.00 | {'YES': 363, 'NO': 345} | 0.00 |
| market_shrunk_a0.05 | 708 | 0 | **0** | -0.17 | -2.15 | -4.15 | -2.98 | 0.00 | {'YES': 329, 'NO': 379} | 0.39 |
| market_shrunk_a0.1 | 708 | 0 | **0** | 0.07 | -1.89 | -3.89 | -2.87 | 0.00 | {'YES': 330, 'NO': 378} | 0.77 |
| market_shrunk_a0.2 | 708 | 0 | **0** | 0.63 | -1.63 | -3.63 | -1.90 | 0.00 | {'YES': 334, 'NO': 374} | 1.54 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 700, 'PRICE_ABOVE_RESERVATION': 665, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 591, 'RAW_EDGE_BELOW_MIN': 468, 'COST_ADJUSTED_EDGE_BELOW_MIN': 393, 'EDGE_OK': 8}  buckets={'[0.7,0.8)': 253, '[0.9,1.0)': 152, '[0.8,0.9)': 80, '[0.3,0.4)': 75, '[0.4,0.5)': 54, '[0.5,0.6)': 38, '[0.6,0.7)': 24, '[0.2,0.3)': 15, '[0.1,0.2)': 9, '[0.0,0.1)': 8}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 703, 'PRICE_ABOVE_RESERVATION': 662, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 563, 'RAW_EDGE_BELOW_MIN': 349, 'COST_ADJUSTED_EDGE_BELOW_MIN': 264, 'MODEL_DISAGREEMENT_TOO_HIGH': 34}  buckets={'[0.9,1.0)': 154, '[0.8,0.9)': 111, '[0.7,0.8)': 87, '[0.1,0.2)': 77, '[0.5,0.6)': 68, '[0.3,0.4)': 52, '[0.4,0.5)': 49, '[0.6,0.7)': 48, '[0.2,0.3)': 38, '[0.0,0.1)': 24}
- **platt**: reasons={'EDGE_BELOW_MIN': 703, 'PRICE_ABOVE_RESERVATION': 648, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 524, 'RAW_EDGE_BELOW_MIN': 323, 'COST_ADJUSTED_EDGE_BELOW_MIN': 212, 'MODEL_DISAGREEMENT_TOO_HIGH': 45}  buckets={'[0.9,1.0)': 221, '[0.8,0.9)': 130, '[0.1,0.2)': 89, '[0.6,0.7)': 52, '[0.3,0.4)': 49, '[0.7,0.8)': 44, '[0.5,0.6)': 43, '[0.2,0.3)': 35, '[0.4,0.5)': 29, '[0.0,0.1)': 16}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 708, 'COST_ADJUSTED_EDGE_BELOW_MIN': 708, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 708, 'PRICE_ABOVE_RESERVATION': 708, 'EDGE_BELOW_MIN': 708}  buckets={'[0.9,1.0)': 154, '[0.8,0.9)': 119, '[0.7,0.8)': 100, '[0.6,0.7)': 96, '[0.5,0.6)': 94, '[0.3,0.4)': 55, '[0.4,0.5)': 40, '[0.2,0.3)': 32, '[0.1,0.2)': 10, '[0.0,0.1)': 8}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 708, 'COST_ADJUSTED_EDGE_BELOW_MIN': 708, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 708, 'PRICE_ABOVE_RESERVATION': 708, 'EDGE_BELOW_MIN': 708}  buckets={'[0.9,1.0)': 154, '[0.8,0.9)': 119, '[0.7,0.8)': 100, '[0.6,0.7)': 96, '[0.5,0.6)': 94, '[0.3,0.4)': 55, '[0.4,0.5)': 40, '[0.2,0.3)': 32, '[0.1,0.2)': 10, '[0.0,0.1)': 8}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 708, 'COST_ADJUSTED_EDGE_BELOW_MIN': 708, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 708, 'PRICE_ABOVE_RESERVATION': 708, 'EDGE_BELOW_MIN': 708}  buckets={'[0.9,1.0)': 152, '[0.8,0.9)': 119, '[0.7,0.8)': 102, '[0.5,0.6)': 93, '[0.6,0.7)': 92, '[0.3,0.4)': 55, '[0.4,0.5)': 42, '[0.2,0.3)': 35, '[0.1,0.2)': 10, '[0.0,0.1)': 8}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 708, 'COST_ADJUSTED_EDGE_BELOW_MIN': 708, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 708, 'PRICE_ABOVE_RESERVATION': 708, 'EDGE_BELOW_MIN': 708}  buckets={'[0.9,1.0)': 150, '[0.8,0.9)': 124, '[0.7,0.8)': 95, '[0.6,0.7)': 92, '[0.5,0.6)': 86, '[0.3,0.4)': 57, '[0.4,0.5)': 49, '[0.2,0.3)': 35, '[0.1,0.2)': 12, '[0.0,0.1)': 8}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 708, 'PRICE_ABOVE_RESERVATION': 708, 'EDGE_BELOW_MIN': 708, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 707, 'COST_ADJUSTED_EDGE_BELOW_MIN': 705}  buckets={'[0.9,1.0)': 150, '[0.8,0.9)': 121, '[0.7,0.8)': 96, '[0.6,0.7)': 87, '[0.5,0.6)': 77, '[0.4,0.5)': 62, '[0.3,0.4)': 47, '[0.2,0.3)': 47, '[0.1,0.2)': 13, '[0.0,0.1)': 8}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **True**  (best repaired final = 5.98c)
- promoted-isotonic reference passes 8 row(s) (not a repair).
- **recommendation: ['identity_raw', 'platt'] cleared the final edge gate on real shadow rows WITHOUT weakening it — mark STAGED_SHADOW_CANDIDATE and review (calibration + concentration) before any promotion. Do NOT promote here.**
- STAGED_SHADOW_CANDIDATE: ['identity_raw', 'platt'] (marked STAGED only; NOT promoted; requires a separate review).

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260607_224356.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260607_224356.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260607_224356.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260607_224356.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260607_224356.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260607_224356.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
