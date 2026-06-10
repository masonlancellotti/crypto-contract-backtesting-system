# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-3.0002c med_calib_buf=0.0000c side={'YES': 10221, 'NO': 5421}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0900c

### ridge
- WINDOW unit: candidate_like=14163 pass_final=0 distinct_pass_windows=0 best_final=46.8949c med_calib_buf=0.0000c side={'YES': 15642}
- ROW unit: candidate_like=10333 pass_final=0 best_final=-3.2000c

### elasticnet
- WINDOW unit: candidate_like=14162 pass_final=0 distinct_pass_windows=0 best_final=10.3875c med_calib_buf=0.0000c side={'YES': 15642}
- ROW unit: candidate_like=14150 pass_final=0 best_final=6.8005c

### logistic_offset
- WINDOW unit: candidate_like=3299 pass_final=0 distinct_pass_windows=0 best_final=12.1944c med_calib_buf=0.0000c side={'NO': 7887, 'YES': 7755}
- ROW unit: candidate_like=3336 pass_final=108 best_final=8.5789c

### lightgbm
- WINDOW unit: candidate_like=10879 pass_final=0 distinct_pass_windows=0 best_final=32.1515c med_calib_buf=0.0000c side={'NO': 14960, 'YES': 682}
- ROW unit: candidate_like=8599 pass_final=0 best_final=7.4692c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
