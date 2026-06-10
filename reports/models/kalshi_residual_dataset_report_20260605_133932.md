# Kalshi residual-alpha dataset report — KXBTC15M

> STAGED / report-only. Target = residual = y - p_market (executable asks; no midpoint). No promotion; live/paper disabled.

- dataset_file: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_residual_dataset_20260605_133930.parquet`
- rows: 47124  distinct_windows: 328  base_rate(YES): 0.4273
- label_balance: {'YES': 20135, 'NO': 26989}
- residual mean/std: -0.0201 / 0.3530
- market-implied calibration (the BASELINE to beat): brier=0.1250 log_loss=0.3874 ECE_row=0.0325 ECE_window=0.0473
- realized edge means (after fees): YES=-0.0390 NO=0.0007  best_edge_mean=0.2423
- candidate_pnl_positive_rows (a side had +realized P&L): 42339 / 47124
- rows_by_time_to_close: {'300-600s': 17750, '600-900s': 15089, '180-300s': 7324, '60-180s': 6103, '<60s': 858}
- rows_by_price_bucket: {'[0.0,0.1)': 10467, '[0.1,0.2)': 4552, '[0.2,0.3)': 4221, '[0.3,0.4)': 3756, '[0.4,0.5)': 3653, '[0.5,0.6)': 3682, '[0.6,0.7)': 3606, '[0.7,0.8)': 3332, '[0.8,0.9)': 3199, '[0.9,1.0)': 6656}

## Leakage
- see feature_schema.LEAKAGE_EXCLUDED; label/result/levels never enter features; p_market uses executable asks (no midpoint).

## Safety
- STAGED dataset; no promotion; no paper/live; live_submission_allowed=false.
