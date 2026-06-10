# Kalshi residual replay — KXBTC15M

> STAGED / report-only. Latest shadow ledger rows re-scored with the market baseline + residual models through the unchanged edge policy. No fills; no promotion; live disabled.

- ledger: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\paper\experiments\shadow_clean_30min_20260605_041831_decisions.jsonl`  rows_scored: 394

| method | candidate_like | pass_final | distinct_pass_windows | best_final(c) | sides |
|---|---|---|---|---|---|
| market_only | 0 | 0 | 0 | -3.0002 | {'YES': 341, 'NO': 53} |
| ridge | 0 | 0 | 0 | -1.4062 | {'NO': 394} |
| logistic_offset | 115 | 0 | 0 | -1.0841 | {'NO': 340, 'YES': 54} |

## Safety
- replay only; buffers intact; no promotion; live disabled.
