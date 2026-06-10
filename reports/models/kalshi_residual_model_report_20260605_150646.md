# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 332, 'train_windows': 166, 'calib_windows': 83, 'test_windows': 81, 'embargo_windows': 1}  rows: 47900  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1210 log_loss=0.3817 ECE_row=0.0281 ECE_window=0.0296

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1210 | 0.0000 | 0.3817 | 0.0296 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.1259 | 0.0049 | 0.4213 | 0.0489 | 0.0193 | 0.0151 | 0.5420 | 0 | 0 | -1.8610 |
| elasticnet | 0.1226 | 0.0016 | 0.4103 | 0.0375 | 0.0079 | 0.1327 | 0.6055 | 0 | 0 | -1.3670 |
| logistic_offset | 0.1299 | 0.0089 | 0.4111 | 0.0546 | 0.0250 | 0.1103 | 0.6988 | 0 | 0 | -1.7520 |
| lightgbm | 0.1528 | 0.0318 | 0.4683 | 0.0862 | 0.0566 | -0.0266 | 0.6002 | 0 | 0 | -3.6280 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=0.0008 dECE_win=0.0219 IC=0.1689
- market+kalshi_book: dBrier=0.0010 dECE_win=0.0132 IC=0.2611
- market+underlying: dBrier=0.0035 dECE_win=0.0039 IC=0.0421
- market+deribit: dBrier=0.0000 dECE_win=-0.0010 IC=0.1420
- market+all: dBrier=0.0049 dECE_win=0.0193 IC=0.0151

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.05298), np.float64(0.17628), np.float64(0.00434)] ic=[0.011, -0.1639, -0.0189] stable_improvement=False
- elasticnet: deltas=[np.float64(0.14022), np.float64(0.03147), np.float64(0.00145)] ic=[-0.18, -0.0801, 0.1202] stable_improvement=False
- logistic_offset: deltas=[0.2226, 0.19534, 0.00874] ic=[-0.1582, -0.1577, 0.0475] stable_improvement=False
- lightgbm: deltas=[0.2479, 0.06938, 0.02348] ic=[-0.2048, -0.1946, -0.0139] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'deribit_atm_iv': 0.12139, 'deribit_dvol': -0.0843, 'deribit_near_expiry_iv': 0.05191, 'deribit_historical_vol': -0.04205, 'distance_to_start': -0.03897, 'spot_trade_intensity_60s': 0.03583, 'spot_return_since_window_start': 0.03554, 'perp_trade_intensity_60s': -0.03404}
- elasticnet: {'deribit_put_call_volume_ratio': 0.03239, 'deribit_historical_vol': -0.03037, 'realized_vol_180s': 0.01761, 'deribit_atm_iv': 0.01434, 'fraction_window_elapsed': 0.01218, 'seconds_to_close': -0.01174, 'deribit_put_call_oi_ratio': 0.01057, 'deribit_near_expiry_iv': 0.00816}
- logistic_offset: {'__logit_market__': 2.70186, 'deribit_atm_iv': 1.0691, 'deribit_dvol': -0.88343, 'distance_to_start': -0.81411, 'spot_return_since_window_start': 0.71683, 'distance_to_line_vol_normalized': 0.5417, 'deribit_near_expiry_iv': 0.41382, 'deribit_historical_vol': -0.34974}
- lightgbm: {'spot_sigma_per_sqrt_s': 194, 'deribit_put_call_oi_ratio': 190, 'deribit_put_call_volume_ratio': 127, 'deribit_dvol': 126, 'executable_yes_buy_price': 122, 'executable_no_buy_price': 117, 'realized_vol_window_to_date': 117, 'deribit_atm_iv': 107}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
