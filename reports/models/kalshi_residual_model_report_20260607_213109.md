# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 508, 'train_windows': 254, 'calib_windows': 127, 'test_windows': 125, 'embargo_windows': 1}  rows: 81614  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1479 log_loss=0.4491 ECE_row=0.0326 ECE_window=0.0298

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1479 | 0.0000 | 0.4491 | 0.0298 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.1535 | 0.0057 | 0.5135 | 0.0921 | 0.0622 | 0.0824 | 0.5054 | 0 | 0 | -6.9350 |
| elasticnet | 0.1499 | 0.0020 | 0.4730 | 0.0723 | 0.0424 | 0.0858 | 0.5304 | 0 | 0 | -7.6550 |
| logistic_offset | 0.1569 | 0.0090 | 0.4775 | 0.1120 | 0.0822 | 0.0965 | 0.6026 | 0 | 0 | -6.8100 |
| lightgbm | 0.1510 | 0.0032 | 0.4565 | 0.0712 | 0.0413 | -0.0130 | 0.5070 | 0 | 0 | -9.2220 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=0.0010 dECE_win=0.0213 IC=0.0643
- market+kalshi_book: dBrier=0.0004 dECE_win=0.0286 IC=0.1768
- market+underlying: dBrier=0.0029 dECE_win=0.0307 IC=-0.0147
- market+deribit: dBrier=0.0011 dECE_win=0.0136 IC=-0.0203
- market+all: dBrier=0.0057 dECE_win=0.0622 IC=0.0824

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.14758), np.float64(0.00472), np.float64(0.0005)] ic=[-0.0817, 0.0341, 0.1298] stable_improvement=False
- elasticnet: deltas=[np.float64(0.02898), np.float64(0.00095), np.float64(-0.00036)] ic=[-0.0164, 0.1095, 0.128] stable_improvement=False
- logistic_offset: deltas=[0.17433, 0.00855, 0.00275] ic=[-0.0761, 0.0848, 0.1686] stable_improvement=False
- lightgbm: deltas=[0.03087, 0.0175, 0.00148] ic=[-0.1197, 0.0474, -0.0165] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'deribit_atm_iv': 0.08557, 'perp_trade_intensity_60s': -0.06707, 'spot_trade_intensity_60s': 0.06672, 'deribit_dvol': -0.06153, 'deribit_historical_vol': -0.04532, 'yes_bid': 0.04085, 'no_ask': -0.04085, 'executable_no_buy_price': -0.04085}
- elasticnet: {'deribit_put_call_volume_ratio': 0.02457, 'deribit_historical_vol': -0.02033, 'realized_vol_180s': 0.01534, 'deribit_atm_iv': 0.01051, 'deribit_put_call_oi_ratio': 0.00699, 'fraction_window_elapsed': 0.00605, 'seconds_to_close': -0.00604, 'deribit_stale': -0.00469}
- logistic_offset: {'__logit_market__': 1.66505, 'deribit_atm_iv': 0.69339, 'spot_trade_intensity_60s': 0.589, 'perp_trade_intensity_60s': -0.57416, 'deribit_dvol': -0.55168, 'deribit_historical_vol': -0.38788, 'distance_to_line_vol_normalized': 0.34192, 'deribit_put_call_volume_ratio': 0.30794}
- lightgbm: {'spot_sigma_per_sqrt_s': 241, 'deribit_put_call_oi_ratio': 178, 'executable_no_buy_price': 142, 'deribit_atm_iv': 116, 'realized_vol_window_to_date': 102, 'realized_vol_180s': 92, 'deribit_options_open_interest_total': 89, 'deribit_put_call_volume_ratio': 85}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
