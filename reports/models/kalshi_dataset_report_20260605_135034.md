# Kalshi model dataset report — KXBTC15M

- status: **NOT_TRAINING_READY**
- dataset_file: `C:\Users\mason\AppData\Local\Temp\pytest-of-mason\pytest-1038\test_dataset_parquet_staged_le0\models\staged\kalshi_dataset_20260605_135034.parquet`
- final_model_rows: 48
- distinct_windows: 8
- gate_windows: 8 / train 150 (backtest 60)
- windows_remaining_to_backtest: 52
- windows_remaining_to_train: 142
- feature_set_version_counts: {'3': 48}
- deribit_included (selected for model): False  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 48
- feature_rows_with_orderbook: 48
- feature_rows_with_underlying: 48
- feature_rows_with_start_reference: 48
- feature_rows_joined_to_official: 48
- rows_rejected_missing_book: 0
- rows_rejected_missing_underlying: 0
- rows_rejected_missing_label: 0
- rows_rejected_window_closed_or_bad_book: 0
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 48

## Deribit (OPTIONAL; column presence != candidate-feature selection)
- candidate_feature_group_status: **EXCLUDED_BY_CONFIG**
- columns_present: True
- enabled_in_config: False
- include_in_model_features: False
- selected_for_model_features: False
- rows_with_deribit_used: 0/48 (stale 0, fraction_used 0.0)
- selected_candidate_feature_count: 0
- Column presence != candidate-feature selection. Disabled/leftover Deribit columns are never silently fed to the model; selection requires DERIBIT_INCLUDE_IN_MODEL_FEATURES (and an enabled source, or an explicit allow-historical opt-in).

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.0
- distance_to_line_vol_normalized: 0.0
- yes_bid: 1.0  <-- always missing
- yes_ask: 0.0
- no_bid: 1.0  <-- always missing
- no_ask: 0.0
- executable_yes_buy_price: 1.0  <-- always missing
- executable_no_buy_price: 1.0  <-- always missing
- yes_spread: 0.0
- no_spread: 0.0
- top_depth: 0.0
- depth_imbalance: 1.0  <-- always missing
- quote_age_ms: 0.0
- spot_return_5s: 1.0  <-- always missing
- spot_return_15s: 1.0  <-- always missing
- spot_return_30s: 1.0  <-- always missing
- spot_return_60s: 0.0
- spot_return_180s: 1.0  <-- always missing
- spot_return_since_window_start: 1.0  <-- always missing
- spot_sigma_per_sqrt_s: 0.0
- realized_vol_30s: 1.0  <-- always missing
- realized_vol_60s: 0.0
- realized_vol_180s: 0.0
- realized_vol_window_to_date: 1.0  <-- always missing
- spot_perp_basis: 1.0  <-- always missing
- spot_perp_basis_change_60s: 1.0  <-- always missing
- binance_queue_imbalance: 1.0  <-- always missing
- binance_ofi_best: 1.0  <-- always missing
- spot_cvd_60s: 1.0  <-- always missing
- perp_cvd_60s: 1.0  <-- always missing
- spot_signed_trade_imbalance_60s: 1.0  <-- always missing
- perp_signed_trade_imbalance_60s: 1.0  <-- always missing
- spot_trade_intensity_60s: 1.0  <-- always missing
- perp_trade_intensity_60s: 1.0  <-- always missing
- coinbase_spread: 1.0  <-- always missing
- binance_spread: 1.0  <-- always missing
- deribit_available: 1.0  <-- always missing
- deribit_stale: 1.0  <-- always missing
- deribit_dvol: 1.0  <-- always missing
- deribit_historical_vol: 1.0  <-- always missing
- deribit_near_expiry_iv: 1.0  <-- always missing
- deribit_atm_iv: 1.0  <-- always missing
- deribit_options_open_interest_total: 1.0  <-- always missing
- deribit_put_call_oi_ratio: 1.0  <-- always missing
- deribit_put_call_volume_ratio: 1.0  <-- always missing
- deribit_skew_proxy: 1.0  <-- always missing
- deribit_iv_minus_realized_vol_60s: 1.0  <-- always missing
- coinbase_stale: 1.0  <-- always missing
- binance_stale: 1.0  <-- always missing
- has_spot_feed: 1.0  <-- always missing
- has_perp_feed: 1.0  <-- always missing

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
