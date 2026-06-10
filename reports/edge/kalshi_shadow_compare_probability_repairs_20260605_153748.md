# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 454  executable_rows: 421  iterations: 2520  elapsed_s: 1800.11
- split(windows): {'n_windows': 332, 'train_windows': 166, 'calib_windows': 83, 'test_windows': 81, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MISSING_BOOK': 30, 'INSUFFICIENT_DEPTH': 30, 'MARKET_CLOSED': 17, 'FEATURE_ROW_STALE': 14, 'TOO_CLOSE_TO_CLOSE': 6}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 421 | 247 | **0** | 13.17 | -2.75 | -4.75 | 2.32 | 8.57 | {'YES': 322, 'NO': 99} | 11.99 |
| identity_raw | 421 | 164 | **17** | 4.05 | -1.21 | -3.21 | 7.32 | 0.46 | {'YES': 310, 'NO': 111} | 4.78 |
| platt | 421 | 215 | **3** | 5.08 | -1.64 | -3.64 | 4.30 | 2.00 | {'YES': 248, 'NO': 173} | 6.63 |
| market_implied | 421 | 0 | **0** | -0.55 | -2.35 | -4.35 | -3.09 | 0.00 | {'NO': 207, 'YES': 214} | 0.00 |
| market_shrunk_a0.0 | 421 | 0 | **0** | -0.55 | -2.35 | -4.35 | -3.09 | 0.00 | {'NO': 207, 'YES': 214} | 0.00 |
| market_shrunk_a0.05 | 421 | 0 | **0** | -0.56 | -2.52 | -4.52 | -2.95 | 0.00 | {'NO': 177, 'YES': 244} | 0.24 |
| market_shrunk_a0.1 | 421 | 0 | **0** | -0.60 | -2.51 | -4.51 | -2.62 | 0.00 | {'NO': 176, 'YES': 245} | 0.48 |
| market_shrunk_a0.2 | 421 | 0 | **0** | -0.63 | -2.62 | -4.62 | -1.93 | 0.00 | {'NO': 162, 'YES': 259} | 0.96 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 419, 'PRICE_ABOVE_RESERVATION': 412, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 379, 'RAW_EDGE_BELOW_MIN': 174, 'COST_ADJUSTED_EDGE_BELOW_MIN': 151, 'MODEL_DISAGREEMENT_TOO_HIGH': 104}  buckets={'[0.7,0.8)': 99, '[0.9,1.0)': 90, '[0.4,0.5)': 59, '[0.8,0.9)': 46, '[0.3,0.4)': 45, '[0.2,0.3)': 33, '[0.1,0.2)': 21, '[0.5,0.6)': 12, '[0.6,0.7)': 10, '[0.0,0.1)': 6}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 403, 'PRICE_ABOVE_RESERVATION': 360, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 297, 'RAW_EDGE_BELOW_MIN': 257, 'COST_ADJUSTED_EDGE_BELOW_MIN': 178, 'EDGE_OK': 17}  buckets={'[0.9,1.0)': 91, '[0.8,0.9)': 71, '[0.1,0.2)': 50, '[0.2,0.3)': 49, '[0.0,0.1)': 43, '[0.3,0.4)': 32, '[0.7,0.8)': 26, '[0.5,0.6)': 22, '[0.4,0.5)': 21, '[0.6,0.7)': 16}
- **platt**: reasons={'EDGE_BELOW_MIN': 418, 'PRICE_ABOVE_RESERVATION': 391, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 316, 'RAW_EDGE_BELOW_MIN': 206, 'COST_ADJUSTED_EDGE_BELOW_MIN': 93, 'EDGE_OK': 3}  buckets={'[0.9,1.0)': 121, '[0.0,0.1)': 78, '[0.1,0.2)': 69, '[0.8,0.9)': 63, '[0.2,0.3)': 25, '[0.5,0.6)': 17, '[0.4,0.5)': 14, '[0.6,0.7)': 13, '[0.3,0.4)': 11, '[0.7,0.8)': 10}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 421, 'COST_ADJUSTED_EDGE_BELOW_MIN': 421, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 421, 'PRICE_ABOVE_RESERVATION': 421, 'EDGE_BELOW_MIN': 421, 'STALE_QUOTE_BUFFER_APPLIED': 1}  buckets={'[0.9,1.0)': 89, '[0.0,0.1)': 75, '[0.2,0.3)': 65, '[0.8,0.9)': 50, '[0.7,0.8)': 38, '[0.4,0.5)': 28, '[0.5,0.6)': 22, '[0.1,0.2)': 22, '[0.6,0.7)': 17, '[0.3,0.4)': 15}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 421, 'COST_ADJUSTED_EDGE_BELOW_MIN': 421, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 421, 'PRICE_ABOVE_RESERVATION': 421, 'EDGE_BELOW_MIN': 421, 'STALE_QUOTE_BUFFER_APPLIED': 1}  buckets={'[0.9,1.0)': 89, '[0.0,0.1)': 75, '[0.2,0.3)': 65, '[0.8,0.9)': 50, '[0.7,0.8)': 38, '[0.4,0.5)': 28, '[0.5,0.6)': 22, '[0.1,0.2)': 22, '[0.6,0.7)': 17, '[0.3,0.4)': 15}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 421, 'COST_ADJUSTED_EDGE_BELOW_MIN': 421, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 421, 'PRICE_ABOVE_RESERVATION': 421, 'EDGE_BELOW_MIN': 421, 'STALE_QUOTE_BUFFER_APPLIED': 1}  buckets={'[0.9,1.0)': 89, '[0.0,0.1)': 75, '[0.2,0.3)': 66, '[0.8,0.9)': 50, '[0.7,0.8)': 38, '[0.4,0.5)': 28, '[0.5,0.6)': 22, '[0.1,0.2)': 21, '[0.6,0.7)': 17, '[0.3,0.4)': 15}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 421, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 421, 'PRICE_ABOVE_RESERVATION': 421, 'EDGE_BELOW_MIN': 421, 'COST_ADJUSTED_EDGE_BELOW_MIN': 420, 'STALE_QUOTE_BUFFER_APPLIED': 1}  buckets={'[0.9,1.0)': 89, '[0.0,0.1)': 74, '[0.2,0.3)': 66, '[0.8,0.9)': 50, '[0.7,0.8)': 40, '[0.4,0.5)': 27, '[0.1,0.2)': 22, '[0.5,0.6)': 21, '[0.6,0.7)': 16, '[0.3,0.4)': 16}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 421, 'PRICE_ABOVE_RESERVATION': 421, 'EDGE_BELOW_MIN': 421, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 420, 'COST_ADJUSTED_EDGE_BELOW_MIN': 406, 'STALE_QUOTE_BUFFER_APPLIED': 1}  buckets={'[0.9,1.0)': 89, '[0.0,0.1)': 70, '[0.2,0.3)': 66, '[0.8,0.9)': 50, '[0.7,0.8)': 41, '[0.1,0.2)': 26, '[0.4,0.5)': 25, '[0.5,0.6)': 22, '[0.6,0.7)': 16, '[0.3,0.4)': 16}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **True**  (best repaired final = 7.32c)
- promoted-isotonic reference passes 0 row(s) (not a repair).
- **recommendation: ['identity_raw', 'platt'] cleared the final edge gate on real shadow rows WITHOUT weakening it — mark STAGED_SHADOW_CANDIDATE and review (calibration + concentration) before any promotion. Do NOT promote here.**
- STAGED_SHADOW_CANDIDATE: ['identity_raw', 'platt'] (marked STAGED only; NOT promoted; requires a separate review).

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260605_153748.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260605_153748.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260605_153748.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260605_153748.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260605_153748.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260605_153748.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
