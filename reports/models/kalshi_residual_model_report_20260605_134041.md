# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 328, 'train_windows': 164, 'calib_windows': 82, 'test_windows': 80, 'embargo_windows': 1}  rows: 47124  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1169 log_loss=0.3719 ECE_row=0.0292 ECE_window=0.0318

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1169 | 0.0000 | 0.3719 | 0.0318 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.5524 | 0.4355 | 5.0892 | 0.5499 | 0.5181 | -0.2678 | 0.4474 | 0 | 0 | -4.1480 |
| elasticnet | 0.1453 | 0.0283 | 0.5057 | 0.1669 | 0.1351 | -0.0855 | 0.4474 | 0 | 0 | -4.1480 |
| logistic_offset | 0.1176 | 0.0007 | 0.3723 | 0.0423 | 0.0105 | 0.1949 | 0.6230 | 0 | 0 | -3.1420 |
| lightgbm | 0.2583 | 0.1413 | 1.0155 | 0.3694 | 0.3375 | -0.0975 | 0.5726 | 0 | 0 | 0.3760 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=0.0016 dECE_win=0.0306 IC=0.1497
- market+kalshi_book: dBrier=0.0014 dECE_win=0.0151 IC=0.2590
- market+underlying: dBrier=0.0012 dECE_win=0.0062 IC=-0.0265
- market+deribit: dBrier=0.4355 dECE_win=0.5181 IC=-0.2678
- market+all: dBrier=0.4355 dECE_win=0.5181 IC=-0.2678

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.02007), np.float64(0.16959), 0.44511] ic=[0.0741, -0.2083, -0.2592] stable_improvement=False
- elasticnet: deltas=[np.float64(0.13347), np.float64(0.03444), np.float64(0.00227)] ic=[-0.1624, -0.1085, 0.045] stable_improvement=False
- logistic_offset: deltas=[0.03588, 0.03524, 0.00279] ic=[-0.0486, -0.0987, 0.089] stable_improvement=False
- lightgbm: deltas=[0.22696, 0.04857, 0.13869] ic=[-0.1593, -0.1279, -0.0864] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'deribit_put_call_volume_ratio': 0.28973, 'deribit_put_call_oi_ratio': 0.15962, 'yes_spread': -0.12087, 'no_spread': -0.12087, 'no_ask': -0.08401, 'executable_no_buy_price': -0.08401, 'yes_bid': 0.08401, 'deribit_available': -0.07007}
- elasticnet: {'deribit_historical_vol': -0.0301, 'deribit_atm_iv': 0.02013, 'deribit_near_expiry_iv': 0.01545, 'perp_cvd_60s': -0.0043, 'depth_imbalance': 0.00369, 'deribit_iv_minus_realized_vol_60s': -0.00049, 'spot_perp_basis': 0.00023, 'seconds_to_close': -0.00013}
- logistic_offset: {'__logit_market__': 0.80846, 'deribit_atm_iv': 0.14786, 'executable_no_buy_price': -0.12474, 'no_ask': -0.12474, 'no_bid': -0.12473, 'yes_bid': 0.12343, 'executable_yes_buy_price': 0.12343, 'yes_ask': 0.12343}
- lightgbm: {'deribit_put_call_oi_ratio': 224, 'spot_sigma_per_sqrt_s': 161, 'deribit_put_call_volume_ratio': 121, 'executable_yes_buy_price': 121, 'executable_no_buy_price': 119, 'deribit_atm_iv': 106, 'deribit_dvol': 105, 'realized_vol_window_to_date': 98}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
