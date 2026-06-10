# Kalshi shadow compare — residual models (KXBTC15M)

> STAGED / report-only. Same live executable rows scored by the market baseline + residual models through the unchanged edge policy. No fills; no promotion; live disabled.

- mode: live  rows_read: 31  executable_rows: 16

| method | candidate_like | pass_final | distinct_pass_windows | best_final(c) | sides |
|---|---|---|---|---|---|
| market_only | 0 | 0 | 0 | -4.4257 | {'NO': 13, 'YES': 3} |
| ridge | 3 | 0 | 0 | -1.2884 | {'NO': 16} |
| logistic_offset | 5 | 0 | 0 | 1.4891 | {'NO': 7, 'YES': 9} |

## Safety
- shadow only; buffers intact; no promotion; live/paper disabled.
