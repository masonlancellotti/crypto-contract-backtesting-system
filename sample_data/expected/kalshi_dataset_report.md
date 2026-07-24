# Kalshi model dataset report — KXBTC15M

- status: **NOT_TRAINING_READY**
- dataset_file: `C:\Users\mason\downloads\polymarket-btc-five-mins\sample_data\models\kalshi_dataset_20260724_173534.jsonl`
- final_model_rows: 380
- distinct_windows: 95
- gate_windows: 95 / train 150 (backtest 60)
- windows_remaining_to_backtest: 0
- windows_remaining_to_train: 55
- feature_set_version_counts: {'3': 380}
- deribit_included (selected for model): False  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 380
- feature_rows_with_orderbook: 380
- feature_rows_with_underlying: 380
- feature_rows_with_start_reference: 380
- feature_rows_joined_to_official: 380
- rows_rejected_missing_book: 0
- rows_rejected_missing_underlying: 0
- rows_rejected_missing_label: 0
- rows_rejected_window_closed_or_bad_book: 0
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 380

## Deribit (OPTIONAL; column presence != candidate-feature selection)
- candidate_feature_group_status: **EXCLUDED_BY_CONFIG**
- columns_present: True
- enabled_in_config: False
- include_in_model_features: False
- selected_for_model_features: False
- rows_with_deribit_used: 0/380 (stale 380, fraction_used 0.0)
- selected_candidate_feature_count: 0
- Column presence != candidate-feature selection. Disabled/leftover Deribit columns are never silently fed to the model; selection requires DERIBIT_INCLUDE_IN_MODEL_FEATURES (and an enabled source, or an explicit allow-historical opt-in).

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.0
- distance_to_line_vol_normalized: 0.0
- yes_bid: 0.0
- yes_ask: 0.0
- no_bid: 0.0
- no_ask: 0.0
- executable_yes_buy_price: 0.0
- executable_no_buy_price: 0.0
- yes_spread: 0.0
- no_spread: 0.0
- top_depth: 0.0
- depth_imbalance: 0.0
- quote_age_ms: 1.0  <-- always missing
- spot_return_5s: 0.0
- spot_return_15s: 0.0
- spot_return_30s: 0.0
- spot_return_60s: 0.0
- spot_return_180s: 0.0
- spot_return_since_window_start: 0.0
- spot_sigma_per_sqrt_s: 0.0
- realized_vol_30s: 0.25
- realized_vol_60s: 0.25
- realized_vol_180s: 0.25
- realized_vol_window_to_date: 0.25
- spot_perp_basis: 0.0
- spot_perp_basis_change_60s: 0.0
- binance_queue_imbalance: 0.0
- binance_ofi_best: 0.0
- spot_cvd_60s: 0.0
- perp_cvd_60s: 0.0
- spot_signed_trade_imbalance_60s: 0.0
- perp_signed_trade_imbalance_60s: 0.0
- spot_trade_intensity_60s: 0.0
- perp_trade_intensity_60s: 0.0
- coinbase_spread: 0.0
- binance_spread: 0.0
- deribit_available: 0.0
- deribit_stale: 0.0
- deribit_dvol: 1.0  <-- always missing
- deribit_historical_vol: 1.0  <-- always missing
- deribit_near_expiry_iv: 1.0  <-- always missing
- deribit_atm_iv: 1.0  <-- always missing
- deribit_options_open_interest_total: 1.0  <-- always missing
- deribit_put_call_oi_ratio: 1.0  <-- always missing
- deribit_put_call_volume_ratio: 1.0  <-- always missing
- deribit_skew_proxy: 1.0  <-- always missing
- deribit_iv_minus_realized_vol_60s: 1.0  <-- always missing
- coinbase_stale: 0.0
- binance_stale: 0.0
- has_spot_feed: 0.0
- has_perp_feed: 0.0

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
