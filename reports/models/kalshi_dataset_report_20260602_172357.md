# Kalshi model dataset report — KXBTC15M

- status: **NOT_TRAINING_READY**
- dataset_file: `C:\Users\mason\Downloads\polymarket-btc-five-mins\data\models\kalshi_dataset_20260602_172357.jsonl`
- final_model_rows: 10867
- distinct_windows: 86
- gate_windows: 86 / train 150 (backtest 60)
- windows_remaining_to_backtest: 0
- windows_remaining_to_train: 64
- feature_set_version_counts: {'None': 2315, '2': 3442, '3': 5110}
- deribit_included: True  strict: False

## Row accounting (every drop has a reason)
- total_feature_rows: 52081
- feature_rows_with_orderbook: 11873
- feature_rows_with_underlying: 52081
- feature_rows_with_start_reference: 11666
- feature_rows_joined_to_official: 10867
- rows_rejected_missing_book: 40208
- rows_rejected_missing_underlying: 0
- rows_rejected_missing_label: 208
- rows_rejected_window_closed_or_bad_book: 798
- rows_rejected_stale_source: 0
- rows_rejected_old_feature_version: 0
- final_model_rows: 10867

## Training-feature missingness (fraction None over final rows)
- seconds_to_close: 0.0
- fraction_window_elapsed: 0.0
- distance_to_start: 0.5655  <-- often missing
- distance_to_line_vol_normalized: 0.7076  <-- often missing
- yes_bid: 0.0
- yes_ask: 0.0
- no_bid: 0.0
- no_ask: 0.0
- executable_yes_buy_price: 0.0
- executable_no_buy_price: 0.0
- yes_spread: 0.213
- no_spread: 0.213
- top_depth: 0.213
- depth_imbalance: 0.213
- quote_age_ms: 1.0  <-- always missing
- spot_return_5s: 0.2133
- spot_return_15s: 0.2139
- spot_return_30s: 0.2145
- spot_return_60s: 0.2158
- spot_return_180s: 0.2204
- spot_return_since_window_start: 0.213
- spot_sigma_per_sqrt_s: 0.0086
- realized_vol_30s: 0.228
- realized_vol_60s: 0.2174
- realized_vol_180s: 0.2139
- realized_vol_window_to_date: 0.2328
- spot_perp_basis: 0.213
- spot_perp_basis_change_60s: 0.2159
- binance_queue_imbalance: 0.213
- binance_ofi_best: 0.2133
- spot_cvd_60s: 0.213
- perp_cvd_60s: 0.213
- spot_signed_trade_imbalance_60s: 0.213
- perp_signed_trade_imbalance_60s: 0.213
- spot_trade_intensity_60s: 0.213
- perp_trade_intensity_60s: 0.213
- coinbase_spread: 0.213
- binance_spread: 0.213
- deribit_available: 0.5298  <-- often missing
- deribit_stale: 0.5298  <-- often missing
- deribit_dvol: 0.5298  <-- often missing
- deribit_historical_vol: 0.5298  <-- often missing
- deribit_near_expiry_iv: 0.5298  <-- often missing
- deribit_atm_iv: 0.5298  <-- often missing
- deribit_options_open_interest_total: 0.5298  <-- often missing
- deribit_put_call_oi_ratio: 0.5298  <-- often missing
- deribit_put_call_volume_ratio: 0.5298  <-- often missing
- deribit_skew_proxy: 0.5298  <-- often missing
- deribit_iv_minus_realized_vol_60s: 0.5335  <-- often missing
- coinbase_stale: 0.213
- binance_stale: 0.213
- has_spot_feed: 0.213
- has_perp_feed: 0.213

## Leakage exclusions (never in training matrix)
- binance_best_ask, binance_best_bid, binance_microprice, coinbase_best_ask, coinbase_best_bid, decision_state, fill_status, is_paper, known_outcome, label_source, label_source_status, label_yes_resolved, mid_yes_diagnostic, paper_pnl, paper_pnl_when_known, reference_price, reference_start_price, result, settlement_outcome, settlement_outcome_when_known, settlement_status, simulated_fill_price, simulated_fill_size

## Safety
- OFFICIAL feature-backed labels only; orphan labels excluded.
- Windows (not rows) drive the gate; purge/embargo applied at split time.
- Hard Up/Down class is diagnostic only; no PAPER_CANDIDATE; live disabled.
