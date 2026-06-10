# Kalshi model dataset report — KXBTC15M

- status: **NOT_TRAINING_READY**
- dataset_file: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\kalshi_dataset_20260603_051147.jsonl`
- final_model_rows: 16731
- distinct_windows: 132
- gate_windows: 132 / train 150 (backtest 60)
- windows_remaining_to_backtest: 0
- windows_remaining_to_train: 18
- feature_set_version_counts: {'None': 2315, '2': 3442, '3': 10974}
- deribit_included: True  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 78200
- feature_rows_with_orderbook: 18414
- feature_rows_with_underlying: 78200
- feature_rows_with_start_reference: 18196
- feature_rows_joined_to_official: 16731
- rows_rejected_missing_book: 59786
- rows_rejected_missing_underlying: 0
- rows_rejected_missing_label: 262
- rows_rejected_window_closed_or_bad_book: 1421
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 16731

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.5693  <-- often missing
- distance_to_line_vol_normalized: 0.6616  <-- often missing
- yes_bid: 0.0
- yes_ask: 0.0
- no_bid: 0.0
- no_ask: 0.0
- executable_yes_buy_price: 0.0
- executable_no_buy_price: 0.0
- yes_spread: 0.1384
- no_spread: 0.1384
- top_depth: 0.1384
- depth_imbalance: 0.1384
- quote_age_ms: 1.0  <-- always missing
- spot_return_5s: 0.1385
- spot_return_15s: 0.1389
- spot_return_30s: 0.1393
- spot_return_60s: 0.1402
- spot_return_180s: 0.1431
- spot_return_since_window_start: 0.1384
- spot_sigma_per_sqrt_s: 0.0056
- realized_vol_30s: 0.1549
- realized_vol_60s: 0.148
- realized_vol_180s: 0.1389
- realized_vol_window_to_date: 0.1607
- spot_perp_basis: 0.1384
- spot_perp_basis_change_60s: 0.1402
- binance_queue_imbalance: 0.1384
- binance_ofi_best: 0.1385
- spot_cvd_60s: 0.1384
- perp_cvd_60s: 0.1384
- spot_signed_trade_imbalance_60s: 0.1384
- perp_signed_trade_imbalance_60s: 0.1384
- spot_trade_intensity_60s: 0.1384
- perp_trade_intensity_60s: 0.1384
- coinbase_spread: 0.1384
- binance_spread: 0.1384
- deribit_available: 0.3441
- deribit_stale: 0.3441
- deribit_dvol: 0.3441
- deribit_historical_vol: 0.3441
- deribit_near_expiry_iv: 0.3441
- deribit_atm_iv: 0.3441
- deribit_options_open_interest_total: 0.3441
- deribit_put_call_oi_ratio: 0.3441
- deribit_put_call_volume_ratio: 0.3441
- deribit_skew_proxy: 0.3441
- deribit_iv_minus_realized_vol_60s: 0.3534
- coinbase_stale: 0.1384
- binance_stale: 0.1384
- has_spot_feed: 0.1384
- has_perp_feed: 0.1384

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
