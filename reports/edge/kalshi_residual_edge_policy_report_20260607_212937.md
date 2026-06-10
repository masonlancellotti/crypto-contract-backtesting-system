# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-3.0002c med_calib_buf=0.0000c side={'YES': 11946, 'NO': 11499}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0002c

### ridge
- WINDOW unit: candidate_like=10150 pass_final=0 distinct_pass_windows=0 best_final=5.7672c med_calib_buf=0.0000c side={'NO': 17017, 'YES': 6428}
- ROW unit: candidate_like=11118 pass_final=16 best_final=5.7672c

### elasticnet
- WINDOW unit: candidate_like=1494 pass_final=0 distinct_pass_windows=0 best_final=-0.4598c med_calib_buf=0.0000c side={'NO': 18458, 'YES': 4987}
- ROW unit: candidate_like=1337 pass_final=0 best_final=-1.2370c

### logistic_offset
- WINDOW unit: candidate_like=9088 pass_final=0 distinct_pass_windows=0 best_final=11.8980c med_calib_buf=0.0000c side={'NO': 16472, 'YES': 6973}
- ROW unit: candidate_like=9686 pass_final=12 best_final=5.1721c

### lightgbm
- WINDOW unit: candidate_like=6177 pass_final=0 distinct_pass_windows=0 best_final=10.0118c med_calib_buf=0.0000c side={'NO': 17125, 'YES': 6320}
- ROW unit: candidate_like=6028 pass_final=2 best_final=5.2366c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
