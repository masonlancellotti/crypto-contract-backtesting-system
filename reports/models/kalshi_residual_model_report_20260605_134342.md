# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 328, 'train_windows': 164, 'calib_windows': 82, 'test_windows': 80, 'embargo_windows': 1}  rows: 47124  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1169 log_loss=0.3719 ECE_row=0.0292 ECE_window=0.0318

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1169 | 0.0000 | 0.3719 | 0.0318 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.1208 | 0.0038 | 0.4029 | 0.0385 | 0.0067 | 0.0029 | 0.5210 | 0 | 0 | -2.1420 |
| elasticnet | 0.1182 | 0.0013 | 0.3953 | 0.0429 | 0.0111 | 0.1414 | 0.6032 | 0 | 0 | -1.7500 |
| logistic_offset | 0.1235 | 0.0066 | 0.3928 | 0.0381 | 0.0063 | 0.0894 | 0.6846 | 0 | 0 | -3.1020 |
| lightgbm | 0.1376 | 0.0207 | 0.4281 | 0.0686 | 0.0368 | 0.0043 | 0.6114 | 0 | 0 | -1.6680 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=0.0016 dECE_win=0.0305 IC=0.1441
- market+kalshi_book: dBrier=0.0015 dECE_win=0.0194 IC=0.2436
- market+underlying: dBrier=0.0030 dECE_win=0.0136 IC=0.0392
- market+deribit: dBrier=-0.0001 dECE_win=-0.0007 IC=0.2956
- market+all: dBrier=0.0038 dECE_win=0.0067 IC=0.0029

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.14623), np.float64(0.17891), np.float64(0.00447)] ic=[-0.0093, -0.1889, 0.0087] stable_improvement=False
- elasticnet: deltas=[np.float64(0.04334), np.float64(0.03986), np.float64(0.00157)] ic=[-0.0036, -0.1189, 0.1396] stable_improvement=False
- logistic_offset: deltas=[0.0776, 0.19869, 0.00788] ic=[0.0973, -0.1789, 0.0933] stable_improvement=False
- lightgbm: deltas=[0.20754, 0.06643, 0.0232] ic=[-0.1607, -0.2501, 0.0272] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'deribit_atm_iv': 0.10856, 'deribit_near_expiry_iv': 0.05567, 'deribit_historical_vol': -0.05175, 'deribit_dvol': -0.05133, 'deribit_options_open_interest_total': -0.04366, 'deribit_put_call_volume_ratio': 0.03932, 'deribit_put_call_oi_ratio': 0.03638, 'spot_trade_intensity_60s': 0.03517}
- elasticnet: {'deribit_historical_vol': -0.04293, 'deribit_put_call_volume_ratio': 0.03367, 'deribit_atm_iv': 0.02476, 'realized_vol_180s': 0.0205, 'deribit_put_call_oi_ratio': 0.01931, 'deribit_near_expiry_iv': 0.01267, 'fraction_window_elapsed': 0.01233, 'seconds_to_close': -0.01174}
- logistic_offset: {'__logit_market__': 2.91318, 'deribit_atm_iv': 0.95095, 'distance_to_start': -0.68526, 'deribit_dvol': -0.56986, 'spot_return_since_window_start': 0.55904, 'deribit_near_expiry_iv': 0.43814, 'deribit_historical_vol': -0.42922, 'distance_to_line_vol_normalized': 0.41457}
- lightgbm: {'deribit_put_call_oi_ratio': 215, 'spot_sigma_per_sqrt_s': 191, 'deribit_atm_iv': 135, 'executable_yes_buy_price': 126, 'deribit_put_call_volume_ratio': 119, 'executable_no_buy_price': 116, 'realized_vol_window_to_date': 108, 'deribit_dvol': 106}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
