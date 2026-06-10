# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 621  executable_rows: 556  iterations: 6502  elapsed_s: 3600.21
- split(windows): {'n_windows': 618, 'train_windows': 309, 'calib_windows': 154, 'test_windows': 153, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MISSING_BOOK': 65, 'INSUFFICIENT_DEPTH': 65, 'MARKET_CLOSED': 11, 'TOO_CLOSE_TO_CLOSE': 10, 'FEATURE_ROW_STALE': 4}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 556 | 180 | **1** | 3.24 | -2.32 | -4.32 | 2.41 | 0.17 | {'YES': 225, 'NO': 331} | 4.22 |
| identity_raw | 556 | 267 | **0** | 4.65 | -2.32 | -4.32 | 1.40 | 3.40 | {'NO': 463, 'YES': 93} | 7.51 |
| platt | 556 | 243 | **9** | 4.44 | -1.95 | -3.95 | 3.05 | 0.73 | {'YES': 223, 'NO': 333} | 5.33 |
| market_implied | 556 | 0 | **0** | -0.47 | -1.87 | -3.87 | -3.00 | 0.00 | {'NO': 214, 'YES': 342} | 0.00 |
| market_shrunk_a0.0 | 556 | 0 | **0** | -0.47 | -1.87 | -3.87 | -3.00 | 0.00 | {'NO': 214, 'YES': 342} | 0.00 |
| market_shrunk_a0.05 | 556 | 0 | **0** | -0.26 | -1.94 | -3.94 | -2.98 | 0.00 | {'NO': 215, 'YES': 341} | 0.38 |
| market_shrunk_a0.1 | 556 | 0 | **0** | -0.00 | -1.75 | -3.75 | -2.98 | 0.00 | {'NO': 277, 'YES': 279} | 0.75 |
| market_shrunk_a0.2 | 556 | 1 | **0** | 0.44 | -1.59 | -3.59 | -2.09 | 0.00 | {'NO': 328, 'YES': 228} | 1.50 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 555, 'PRICE_ABOVE_RESERVATION': 540, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 492, 'RAW_EDGE_BELOW_MIN': 376, 'COST_ADJUSTED_EDGE_BELOW_MIN': 294, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.1,0.2)': 114, '[0.7,0.8)': 105, '[0.9,1.0)': 101, '[0.8,0.9)': 74, '[0.0,0.1)': 61, '[0.4,0.5)': 33, '[0.3,0.4)': 22, '[0.5,0.6)': 20, '[0.6,0.7)': 16, '[0.2,0.3)': 10}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 537, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 470, 'RAW_EDGE_BELOW_MIN': 289, 'COST_ADJUSTED_EDGE_BELOW_MIN': 130, 'MODEL_DISAGREEMENT_TOO_HIGH': 22}  buckets={'[0.0,0.1)': 179, '[0.9,1.0)': 106, '[0.8,0.9)': 78, '[0.3,0.4)': 35, '[0.5,0.6)': 31, '[0.7,0.8)': 30, '[0.6,0.7)': 27, '[0.4,0.5)': 25, '[0.2,0.3)': 23, '[0.1,0.2)': 22}
- **platt**: reasons={'EDGE_BELOW_MIN': 547, 'PRICE_ABOVE_RESERVATION': 510, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 461, 'RAW_EDGE_BELOW_MIN': 313, 'COST_ADJUSTED_EDGE_BELOW_MIN': 232, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.1,0.2)': 185, '[0.9,1.0)': 161, '[0.8,0.9)': 56, '[0.7,0.8)': 30, '[0.3,0.4)': 26, '[0.6,0.7)': 25, '[0.2,0.3)': 25, '[0.4,0.5)': 24, '[0.5,0.6)': 24}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 556, 'COST_ADJUSTED_EDGE_BELOW_MIN': 556, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 556, 'EDGE_BELOW_MIN': 556, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.9,1.0)': 128, '[0.0,0.1)': 101, '[0.8,0.9)': 72, '[0.1,0.2)': 61, '[0.7,0.8)': 41, '[0.6,0.7)': 41, '[0.5,0.6)': 41, '[0.4,0.5)': 32, '[0.2,0.3)': 22, '[0.3,0.4)': 17}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 556, 'COST_ADJUSTED_EDGE_BELOW_MIN': 556, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 556, 'EDGE_BELOW_MIN': 556, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.9,1.0)': 128, '[0.0,0.1)': 101, '[0.8,0.9)': 72, '[0.1,0.2)': 61, '[0.7,0.8)': 41, '[0.6,0.7)': 41, '[0.5,0.6)': 41, '[0.4,0.5)': 32, '[0.2,0.3)': 22, '[0.3,0.4)': 17}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 556, 'COST_ADJUSTED_EDGE_BELOW_MIN': 556, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 556, 'EDGE_BELOW_MIN': 556, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.9,1.0)': 125, '[0.0,0.1)': 101, '[0.8,0.9)': 72, '[0.1,0.2)': 64, '[0.7,0.8)': 43, '[0.5,0.6)': 40, '[0.6,0.7)': 39, '[0.4,0.5)': 34, '[0.2,0.3)': 20, '[0.3,0.4)': 18}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 556, 'COST_ADJUSTED_EDGE_BELOW_MIN': 556, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 556, 'EDGE_BELOW_MIN': 556, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.9,1.0)': 125, '[0.0,0.1)': 101, '[0.8,0.9)': 70, '[0.1,0.2)': 67, '[0.7,0.8)': 45, '[0.5,0.6)': 43, '[0.6,0.7)': 35, '[0.4,0.5)': 29, '[0.3,0.4)': 23, '[0.2,0.3)': 18}
- **market_shrunk_a0.2**: reasons={'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 556, 'PRICE_ABOVE_RESERVATION': 556, 'EDGE_BELOW_MIN': 556, 'RAW_EDGE_BELOW_MIN': 555, 'COST_ADJUSTED_EDGE_BELOW_MIN': 555, 'STALE_QUOTE_BUFFER_APPLIED': 12}  buckets={'[0.9,1.0)': 123, '[0.0,0.1)': 112, '[0.8,0.9)': 70, '[0.1,0.2)': 59, '[0.7,0.8)': 45, '[0.5,0.6)': 41, '[0.4,0.5)': 33, '[0.6,0.7)': 32, '[0.3,0.4)': 25, '[0.2,0.3)': 16}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **True**  (best repaired final = 3.05c)
- promoted-isotonic reference passes 1 row(s) (not a repair).
- **recommendation: ['platt'] cleared the final edge gate on real shadow rows WITHOUT weakening it — mark STAGED_SHADOW_CANDIDATE and review (calibration + concentration) before any promotion. Do NOT promote here.**
- STAGED_SHADOW_CANDIDATE: ['platt'] (marked STAGED only; NOT promoted; requires a separate review).

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260609_014939.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260609_014939.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260609_014939.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260609_014939.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260609_014939.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260609_014939.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
