# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 724, 'train_windows': 362, 'calib_windows': 181, 'test_windows': 179, 'embargo_windows': 1}  rows: 115569  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1264 log_loss=0.3862 ECE_row=0.0218 ECE_window=0.0199

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1264 | 0.0000 | 0.3862 | 0.0199 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.1260 | -0.0005 | 0.3890 | 0.0247 | 0.0048 | 0.1609 | 0.5922 | 3 | 3 | -3.8340 |
| elasticnet | 0.1261 | -0.0003 | 0.3877 | 0.0215 | 0.0016 | 0.1342 | 0.5555 | 0 | 0 | 0.8410 |
| logistic_offset | 0.1257 | -0.0007 | 0.3832 | 0.0414 | 0.0216 | 0.2371 | 0.6533 | 5 | 2 | -1.2060 |
| lightgbm | 0.1285 | 0.0021 | 0.3917 | 0.0695 | 0.0496 | 0.0508 | 0.5201 | 209 | 6 | 2.1440 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=-0.0001 dECE_win=0.0077 IC=0.1476
- market+kalshi_book: dBrier=0.0001 dECE_win=0.0139 IC=0.2223
- market+underlying: dBrier=-0.0006 dECE_win=-0.0021 IC=0.0643
- market+deribit: dBrier=-0.0001 dECE_win=-0.0025 IC=0.1864
- market+all: dBrier=-0.0005 dECE_win=0.0048 IC=0.1609

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.05788), np.float64(0.00256), np.float64(-0.0005)] ic=[-0.1117, 0.1344, 0.1443] stable_improvement=False
- elasticnet: deltas=[np.float64(0.0191), np.float64(-0.0002), np.float64(-0.00022)] ic=[-0.0553, 0.1419, 0.093] stable_improvement=False
- logistic_offset: deltas=[0.07401, 0.00513, -0.00099] ic=[-0.1647, 0.1618, 0.2365] stable_improvement=False
- lightgbm: deltas=[0.0439, 0.00133, -0.00036] ic=[-0.2368, 0.0844, 0.0626] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'deribit_atm_iv': 0.06438, 'perp_trade_intensity_60s': -0.05342, 'spot_trade_intensity_60s': 0.05019, 'deribit_dvol': -0.04048, 'deribit_historical_vol': -0.04046, 'no_ask': -0.03644, 'executable_no_buy_price': -0.03644, 'yes_bid': 0.03644}
- elasticnet: {'deribit_put_call_volume_ratio': 0.01814, 'spot_perp_basis': -0.01385, 'deribit_historical_vol': -0.01157, 'realized_vol_180s': 0.00794, 'no_spread': -0.0064, 'yes_spread': -0.00604, 'deribit_atm_iv': 0.0046, 'depth_imbalance': 0.00375}
- logistic_offset: {'__logit_market__': 2.1011, 'deribit_atm_iv': 0.50397, 'perp_trade_intensity_60s': -0.43339, 'spot_trade_intensity_60s': 0.41637, 'deribit_dvol': -0.35539, 'deribit_historical_vol': -0.33557, 'deribit_near_expiry_iv': 0.2118, 'spot_perp_basis': -0.20814}
- lightgbm: {'spot_sigma_per_sqrt_s': 357, 'deribit_put_call_oi_ratio': 160, 'realized_vol_window_to_date': 141, 'executable_no_buy_price': 137, '__logit_market__': 97, 'deribit_atm_iv': 87, 'executable_yes_buy_price': 87, 'spot_return_since_window_start': 76}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
