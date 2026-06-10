# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-4.0203c med_calib_buf=1.4953c side={'NO': 16868, 'YES': 9084}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0900c

### ridge
- WINDOW unit: candidate_like=1101 pass_final=3 distinct_pass_windows=2 best_final=16.5363c med_calib_buf=1.4972c side={'YES': 13298, 'NO': 12654}
- ROW unit: candidate_like=1349 pass_final=9 best_final=12.7552c

### elasticnet
- WINDOW unit: candidate_like=12 pass_final=0 distinct_pass_windows=0 best_final=-2.5956c med_calib_buf=2.2998c side={'NO': 13112, 'YES': 12840}
- ROW unit: candidate_like=12 pass_final=1 best_final=2.0916c

### logistic_offset
- WINDOW unit: candidate_like=3716 pass_final=0 distinct_pass_windows=0 best_final=9.4331c med_calib_buf=0.3189c side={'YES': 14675, 'NO': 11277}
- ROW unit: candidate_like=3908 pass_final=47 best_final=7.6577c

### lightgbm
- WINDOW unit: candidate_like=5885 pass_final=9 distinct_pass_windows=2 best_final=9.9194c med_calib_buf=1.8183c side={'YES': 13257, 'NO': 12695}
- ROW unit: candidate_like=6304 pass_final=181 best_final=9.9194c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
