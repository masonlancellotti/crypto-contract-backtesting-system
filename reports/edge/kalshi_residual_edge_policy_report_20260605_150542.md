# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-3.0002c med_calib_buf=0.0000c side={'YES': 10402, 'NO': 5510}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0900c

### ridge
- WINDOW unit: candidate_like=4370 pass_final=0 distinct_pass_windows=0 best_final=12.0678c med_calib_buf=0.0000c side={'NO': 10383, 'YES': 5529}
- ROW unit: candidate_like=4088 pass_final=124 best_final=8.7574c

### elasticnet
- WINDOW unit: candidate_like=2386 pass_final=0 distinct_pass_windows=0 best_final=5.4936c med_calib_buf=0.0000c side={'NO': 12972, 'YES': 2940}
- ROW unit: candidate_like=2391 pass_final=58 best_final=5.4936c

### logistic_offset
- WINDOW unit: candidate_like=5602 pass_final=0 distinct_pass_windows=0 best_final=16.3507c med_calib_buf=0.0000c side={'NO': 9275, 'YES': 6637}
- ROW unit: candidate_like=5602 pass_final=475 best_final=16.3507c

### lightgbm
- WINDOW unit: candidate_like=9235 pass_final=0 distinct_pass_windows=0 best_final=17.6013c med_calib_buf=0.0000c side={'NO': 11355, 'YES': 4557}
- ROW unit: candidate_like=8811 pass_final=342 best_final=12.8435c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
