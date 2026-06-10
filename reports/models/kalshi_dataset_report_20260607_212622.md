# Kalshi model dataset report — KXBTC15M

- status: **TRAINING_READY**
- dataset_file: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_dataset_20260607_212622.parquet`
- final_model_rows: 81614
- distinct_windows: 508
- gate_windows: 508 / train 150 (backtest 60)
- windows_remaining_to_backtest: 0
- windows_remaining_to_train: 0
- feature_set_version_counts: {'None': 2315, '2': 3442, '3': 75857}
- deribit_included (selected for model): True  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 194885
- feature_rows_with_orderbook: 88983
- feature_rows_with_underlying: 194873
- feature_rows_with_start_reference: 93339
- feature_rows_joined_to_official: 81614
- rows_rejected_missing_book: 105902
- rows_rejected_missing_underlying: 3
- rows_rejected_missing_label: 685
- rows_rejected_window_closed_or_bad_book: 6681
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 81614

## Deribit (OPTIONAL; column presence != candidate-feature selection)
- candidate_feature_group_status: **INCLUDED**
- columns_present: True
- enabled_in_config: True
- include_in_model_features: True
- selected_for_model_features: True
- rows_with_deribit_used: 22584/81614 (stale 34614, fraction_used 0.2767)
- selected_candidate_feature_count: 11
- Column presence != candidate-feature selection. Disabled/leftover Deribit columns are never silently fed to the model; selection requires DERIBIT_INCLUDE_IN_MODEL_FEATURES (and an enabled source, or an explicit allow-historical opt-in).

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.2004
- distance_to_line_vol_normalized: 0.2196
- yes_bid: 0.0
- yes_ask: 0.0
- no_bid: 0.0
- no_ask: 0.0
- executable_yes_buy_price: 0.0
- executable_no_buy_price: 0.0
- yes_spread: 0.0284
- no_spread: 0.0284
- top_depth: 0.0284
- depth_imbalance: 0.0284
- quote_age_ms: 1.0  <-- always missing
- spot_return_5s: 0.0285
- spot_return_15s: 0.0289
- spot_return_30s: 0.0293
- spot_return_60s: 0.0302
- spot_return_180s: 0.0338
- spot_return_since_window_start: 0.0284
- spot_sigma_per_sqrt_s: 0.0015
- realized_vol_30s: 0.0454
- realized_vol_60s: 0.0434
- realized_vol_180s: 0.0288
- realized_vol_window_to_date: 0.0435
- spot_perp_basis: 0.0284
- spot_perp_basis_change_60s: 0.0302
- binance_queue_imbalance: 0.0284
- binance_ofi_best: 0.0285
- spot_cvd_60s: 0.0284
- perp_cvd_60s: 0.0284
- spot_signed_trade_imbalance_60s: 0.0284
- perp_signed_trade_imbalance_60s: 0.0284
- spot_trade_intensity_60s: 0.0284
- perp_trade_intensity_60s: 0.0284
- coinbase_spread: 0.0284
- binance_spread: 0.0284
- deribit_available: 0.0705
- deribit_stale: 0.0705
- deribit_dvol: 0.7233  <-- often missing
- deribit_historical_vol: 0.7233  <-- often missing
- deribit_near_expiry_iv: 0.7233  <-- often missing
- deribit_atm_iv: 0.7233  <-- often missing
- deribit_options_open_interest_total: 0.7233  <-- often missing
- deribit_put_call_oi_ratio: 0.7233  <-- often missing
- deribit_put_call_volume_ratio: 0.7233  <-- often missing
- deribit_skew_proxy: 0.7233  <-- often missing
- deribit_iv_minus_realized_vol_60s: 0.7278  <-- often missing
- coinbase_stale: 0.0284
- binance_stale: 0.0284
- has_spot_feed: 0.0284
- has_perp_feed: 0.0284

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
