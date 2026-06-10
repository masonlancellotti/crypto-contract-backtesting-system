# Kalshi model dataset report — KXBTC15M

- status: **TRAINING_READY**
- dataset_file: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\staged\kalshi_dataset_20260610_032553.parquet`
- final_model_rows: 115569
- distinct_windows: 724
- gate_windows: 724 / train 150 (backtest 60)
- windows_remaining_to_backtest: 0
- windows_remaining_to_train: 0
- feature_set_version_counts: {'None': 2315, '2': 3442, '3': 109812}
- deribit_included (selected for model): True  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 231477
- feature_rows_with_orderbook: 125291
- feature_rows_with_underlying: 231464
- feature_rows_with_start_reference: 129931
- feature_rows_joined_to_official: 115569
- rows_rejected_missing_book: 106186
- rows_rejected_missing_underlying: 4
- rows_rejected_missing_label: 636
- rows_rejected_window_closed_or_bad_book: 9082
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 115569

## Deribit (OPTIONAL; column presence != candidate-feature selection)
- candidate_feature_group_status: **INCLUDED**
- columns_present: True
- enabled_in_config: True
- include_in_model_features: True
- selected_for_model_features: True
- rows_with_deribit_used: 22584/115569 (stale 68569, fraction_used 0.1954)
- selected_candidate_feature_count: 11
- Column presence != candidate-feature selection. Disabled/leftover Deribit columns are never silently fed to the model; selection requires DERIBIT_INCLUDE_IN_MODEL_FEATURES (and an enabled source, or an explicit allow-historical opt-in).

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.1415
- distance_to_line_vol_normalized: 0.1551
- yes_bid: 0.0
- yes_ask: 0.0
- no_bid: 0.0
- no_ask: 0.0
- executable_yes_buy_price: 0.0
- executable_no_buy_price: 0.0
- yes_spread: 0.02
- no_spread: 0.02
- top_depth: 0.02
- depth_imbalance: 0.02
- quote_age_ms: 1.0  <-- always missing
- spot_return_5s: 0.0201
- spot_return_15s: 0.0204
- spot_return_30s: 0.0207
- spot_return_60s: 0.0213
- spot_return_180s: 0.0238
- spot_return_since_window_start: 0.02
- spot_sigma_per_sqrt_s: 0.001
- realized_vol_30s: 0.038
- realized_vol_60s: 0.0363
- realized_vol_180s: 0.0257
- realized_vol_window_to_date: 0.0346
- spot_perp_basis: 0.02
- spot_perp_basis_change_60s: 0.0213
- binance_queue_imbalance: 0.02
- binance_ofi_best: 0.0201
- spot_cvd_60s: 0.02
- perp_cvd_60s: 0.02
- spot_signed_trade_imbalance_60s: 0.02
- perp_signed_trade_imbalance_60s: 0.02
- spot_trade_intensity_60s: 0.02
- perp_trade_intensity_60s: 0.02
- coinbase_spread: 0.02
- binance_spread: 0.02
- deribit_available: 0.0498
- deribit_stale: 0.0498
- deribit_dvol: 0.8046  <-- often missing
- deribit_historical_vol: 0.8046  <-- often missing
- deribit_near_expiry_iv: 0.8046  <-- often missing
- deribit_atm_iv: 0.8046  <-- often missing
- deribit_options_open_interest_total: 0.8046  <-- often missing
- deribit_put_call_oi_ratio: 0.8046  <-- often missing
- deribit_put_call_volume_ratio: 0.8046  <-- often missing
- deribit_skew_proxy: 0.8046  <-- often missing
- deribit_iv_minus_realized_vol_60s: 0.8078  <-- often missing
- coinbase_stale: 0.02
- binance_stale: 0.02
- has_spot_feed: 0.02
- has_perp_feed: 0.02

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
