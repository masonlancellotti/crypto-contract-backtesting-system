# Kalshi residual edge-policy report — KXBTC15M

> STAGED / report-only. p_repaired = clip(p_market + residual_hat) through the UNCHANGED edge policy with DISTINCT-WINDOW reliability; buffers intact; +2c gate intact. No promotion; live disabled.

### market_only
- WINDOW unit: candidate_like=0 pass_final=0 distinct_pass_windows=0 best_final=-3.0002c med_calib_buf=2.6198c side={'YES': 18801, 'NO': 8854}
- ROW unit: candidate_like=0 pass_final=0 best_final=-3.0900c

### ridge
- WINDOW unit: candidate_like=553 pass_final=3 distinct_pass_windows=3 best_final=14.2200c med_calib_buf=0.5568c side={'YES': 18306, 'NO': 9349}
- ROW unit: candidate_like=877 pass_final=10 best_final=14.7575c

### elasticnet
- WINDOW unit: candidate_like=11 pass_final=0 distinct_pass_windows=0 best_final=-0.8102c med_calib_buf=1.1248c side={'YES': 17169, 'NO': 10486}
- ROW unit: candidate_like=11 pass_final=0 best_final=0.5136c

### logistic_offset
- WINDOW unit: candidate_like=2937 pass_final=5 distinct_pass_windows=2 best_final=7.0693c med_calib_buf=0.0000c side={'YES': 17634, 'NO': 10021}
- ROW unit: candidate_like=3248 pass_final=12 best_final=10.3081c

### lightgbm
- WINDOW unit: candidate_like=13316 pass_final=209 distinct_pass_windows=6 best_final=6.0758c med_calib_buf=3.1012c side={'YES': 14011, 'NO': 13644}
- ROW unit: candidate_like=14523 pass_final=216 best_final=6.0758c

## Safety
- buffers never removed; +2c gate intact; window reliability is honest/wider; no promotion; live disabled.
