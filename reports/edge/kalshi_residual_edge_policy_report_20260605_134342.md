# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-3.0002c med_calib_buf=0.0000c side={'YES': 10221, 'NO': 5421}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0900c

### ridge
- WINDOW unit: candidate_like=2954 pass_final=0 distinct_pass_windows=0 best_final=10.5496c med_calib_buf=0.0000c side={'NO': 8695, 'YES': 6947}
- ROW unit: candidate_like=2804 pass_final=104 best_final=7.5604c

### elasticnet
- WINDOW unit: candidate_like=1875 pass_final=0 distinct_pass_windows=0 best_final=4.4563c med_calib_buf=0.0000c side={'NO': 12953, 'YES': 2689}
- ROW unit: candidate_like=1772 pass_final=57 best_final=4.4563c

### logistic_offset
- WINDOW unit: candidate_like=4223 pass_final=0 distinct_pass_windows=0 best_final=13.5360c med_calib_buf=0.0000c side={'NO': 7239, 'YES': 8403}
- ROW unit: candidate_like=4223 pass_final=362 best_final=12.9735c

### lightgbm
- WINDOW unit: candidate_like=8337 pass_final=0 distinct_pass_windows=0 best_final=17.6214c med_calib_buf=0.0000c side={'NO': 12831, 'YES': 2811}
- ROW unit: candidate_like=8270 pass_final=191 best_final=13.0958c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
