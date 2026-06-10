# Kalshi shadow comparison — repaired probabilities (KXBTC15M)

> STAGED / report-only. Same executable rows scored by every probability source through the SAME edge policy; each source's calibration buffer uses its OWN reliability (never removed). No promotion; no manifest change; live/paper disabled.

- mode: **live**  rows_read: 878  executable_rows: 797  iterations: 5210  elapsed_s: 3600.17
- split(windows): {'n_windows': 305, 'train_windows': 152, 'calib_windows': 76, 'test_windows': 75, 'embargo_windows': 1}  shrink_base: identity_raw  alphas: [0.0, 0.05, 0.1, 0.2]
- rejected_before_scoring_by_reason: {'MISSING_BOOK': 80, 'INSUFFICIENT_DEPTH': 80, 'MARKET_CLOSED': 21, 'FEATURE_ROW_STALE': 15, 'TOO_CLOSE_TO_CLOSE': 11}

| source | rows | candidate-like | **pass_final** | med_raw(c) | med_unc_adj(c) | med_final(c) | best_final(c) | med_calib_buf(c) | side | mean|disagree|(c) |
|---|---|---|---|---|---|---|---|---|---|---|
| current_promoted_isotonic | 797 | 643 | **0** | 10.95 | -7.90 | -9.90 | 0.77 | 11.73 | {'NO': 123, 'YES': 674} | 10.78 |
| identity_raw | 797 | 255 | **0** | 3.16 | -1.97 | -3.97 | 1.61 | 2.14 | {'NO': 467, 'YES': 330} | 4.59 |
| platt | 797 | 495 | **0** | 5.94 | -3.30 | -5.30 | 0.75 | 4.91 | {'NO': 481, 'YES': 316} | 6.81 |
| market_implied | 797 | 0 | **0** | -0.60 | -2.41 | -4.41 | -3.09 | 0.00 | {'NO': 745, 'YES': 52} | 0.00 |
| market_shrunk_a0.0 | 797 | 0 | **0** | -0.60 | -2.41 | -4.41 | -3.09 | 0.00 | {'NO': 745, 'YES': 52} | 0.00 |
| market_shrunk_a0.05 | 797 | 0 | **0** | -0.45 | -2.41 | -4.41 | -2.99 | 0.00 | {'NO': 744, 'YES': 53} | 0.23 |
| market_shrunk_a0.1 | 797 | 0 | **0** | -0.35 | -2.26 | -4.26 | -2.89 | 0.00 | {'NO': 744, 'YES': 53} | 0.46 |
| market_shrunk_a0.2 | 797 | 0 | **0** | -0.11 | -2.06 | -4.06 | -2.69 | 0.00 | {'NO': 728, 'YES': 69} | 0.92 |

## Rejection reasons + bucket distribution (per source)
- **current_promoted_isotonic**: reasons={'EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 793, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 772, 'RAW_EDGE_BELOW_MIN': 154, 'COST_ADJUSTED_EDGE_BELOW_MIN': 145, 'MODEL_DISAGREEMENT_TOO_HIGH': 26}  buckets={'[0.7,0.8)': 180, '[0.3,0.4)': 177, '[0.1,0.2)': 132, '[0.2,0.3)': 86, '[0.4,0.5)': 79, '[0.9,1.0)': 40, '[0.0,0.1)': 40, '[0.6,0.7)': 27, '[0.5,0.6)': 22, '[0.8,0.9)': 14}
- **identity_raw**: reasons={'EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 781, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 704, 'RAW_EDGE_BELOW_MIN': 542, 'COST_ADJUSTED_EDGE_BELOW_MIN': 418}  buckets={'[0.0,0.1)': 237, '[0.1,0.2)': 163, '[0.2,0.3)': 96, '[0.5,0.6)': 62, '[0.6,0.7)': 54, '[0.4,0.5)': 48, '[0.9,1.0)': 42, '[0.7,0.8)': 38, '[0.3,0.4)': 34, '[0.8,0.9)': 23}
- **platt**: reasons={'EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 793, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 742, 'RAW_EDGE_BELOW_MIN': 302, 'COST_ADJUSTED_EDGE_BELOW_MIN': 205, 'MODEL_DISAGREEMENT_TOO_HIGH': 3}  buckets={'[0.1,0.2)': 244, '[0.0,0.1)': 215, '[0.5,0.6)': 57, '[0.2,0.3)': 56, '[0.8,0.9)': 51, '[0.6,0.7)': 48, '[0.7,0.8)': 38, '[0.3,0.4)': 35, '[0.4,0.5)': 35, '[0.9,1.0)': 18}
- **market_implied**: reasons={'RAW_EDGE_BELOW_MIN': 797, 'COST_ADJUSTED_EDGE_BELOW_MIN': 797, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 797, 'EDGE_BELOW_MIN': 797}  buckets={'[0.0,0.1)': 187, '[0.2,0.3)': 165, '[0.1,0.2)': 100, '[0.5,0.6)': 79, '[0.6,0.7)': 73, '[0.3,0.4)': 61, '[0.4,0.5)': 43, '[0.7,0.8)': 36, '[0.9,1.0)': 28, '[0.8,0.9)': 25}
- **market_shrunk_a0.0**: reasons={'RAW_EDGE_BELOW_MIN': 797, 'COST_ADJUSTED_EDGE_BELOW_MIN': 797, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 797, 'EDGE_BELOW_MIN': 797}  buckets={'[0.0,0.1)': 187, '[0.2,0.3)': 165, '[0.1,0.2)': 100, '[0.5,0.6)': 79, '[0.6,0.7)': 73, '[0.3,0.4)': 61, '[0.4,0.5)': 43, '[0.7,0.8)': 36, '[0.9,1.0)': 28, '[0.8,0.9)': 25}
- **market_shrunk_a0.05**: reasons={'RAW_EDGE_BELOW_MIN': 797, 'COST_ADJUSTED_EDGE_BELOW_MIN': 797, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 797, 'EDGE_BELOW_MIN': 797}  buckets={'[0.0,0.1)': 187, '[0.2,0.3)': 166, '[0.1,0.2)': 100, '[0.5,0.6)': 76, '[0.6,0.7)': 74, '[0.3,0.4)': 60, '[0.4,0.5)': 45, '[0.7,0.8)': 36, '[0.9,1.0)': 28, '[0.8,0.9)': 25}
- **market_shrunk_a0.1**: reasons={'RAW_EDGE_BELOW_MIN': 797, 'COST_ADJUSTED_EDGE_BELOW_MIN': 797, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 797, 'EDGE_BELOW_MIN': 797}  buckets={'[0.0,0.1)': 187, '[0.2,0.3)': 170, '[0.1,0.2)': 102, '[0.5,0.6)': 76, '[0.6,0.7)': 70, '[0.3,0.4)': 54, '[0.4,0.5)': 46, '[0.7,0.8)': 39, '[0.9,1.0)': 28, '[0.8,0.9)': 25}
- **market_shrunk_a0.2**: reasons={'RAW_EDGE_BELOW_MIN': 797, 'COST_ADJUSTED_EDGE_BELOW_MIN': 797, 'UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN': 797, 'PRICE_ABOVE_RESERVATION': 797, 'EDGE_BELOW_MIN': 797}  buckets={'[0.0,0.1)': 189, '[0.2,0.3)': 166, '[0.1,0.2)': 108, '[0.5,0.6)': 74, '[0.6,0.7)': 66, '[0.3,0.4)': 50, '[0.4,0.5)': 49, '[0.7,0.8)': 42, '[0.9,1.0)': 28, '[0.8,0.9)': 25}

## Verdict
- any REPAIRED source creates positive FINAL edge (without removing protection): **False**  (best repaired final = 1.61c)
- promoted-isotonic reference passes 0 row(s) (not a repair).
- **recommendation: NO repaired source clears the +final edge gate. Repair improves calibration but does not manufacture tradable edge — continue DATA COLLECTION and periodic RETRAINING/RECALIBRATION only; do not lower thresholds, do not remove buffers, do not promote.**

## Staged candidate artifacts (NON-PROMOTED; data/models/staged/ only)
- identity: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_identity_20260605_084559.pkl
- platt: STAGED_NON_PROMOTED -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_platt_20260605_084559.pkl
- market_shrink_a0.0: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.0_20260605_084559.pkl
- market_shrink_a0.05: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.05_20260605_084559.pkl
- market_shrink_a0.1: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.1_20260605_084559.pkl
- market_shrink_a0.2: DIAGNOSTIC_ONLY -> C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_shadow_candidate_market_shrink_a0.2_20260605_084559.pkl

## Safety
- Shadow scoring only; no fills, no orders; per-source buffer never removed.
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- No manifest/promoted/active artifact changed; live/paper disabled; live_submission_allowed=false.
