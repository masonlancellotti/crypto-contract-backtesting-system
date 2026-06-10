# Kalshi residual-alpha model report — KXBTC15M

> STAGED / report-only. Every model uses p_market as the BASELINE; metrics are OUT-OF-SAMPLE on held-out distinct windows. A model is interesting only if it beats market AND clears the unchanged +2c final edge gate across >=2 windows. No promotion; live/paper disabled.

- split(windows): {'n_windows': 617, 'train_windows': 308, 'calib_windows': 154, 'test_windows': 153, 'embargo_windows': 1}  rows: 99658  sklearn=True lightgbm=True
- **market-implied baseline (TEST)**: brier=0.1212 log_loss=0.3765 ECE_row=0.0218 ECE_window=0.0112

| model | brier | dBrier_vs_mkt | log_loss | ECE_window | dECE_win | IC(spearman) | sign_hit | pass_final(win) | dist_pass_win | backtest_net |
|---|---|---|---|---|---|---|---|---|---|---|
| market_only | 0.1212 | 0.0000 | 0.3765 | 0.0112 | 0.0000 | None | None | 0 | 0 | 0.0000 |
| ridge | 0.1218 | 0.0007 | 0.3822 | 0.0154 | 0.0042 | 0.0884 | 0.5721 | 3 | 2 | -3.5920 |
| elasticnet | 0.1211 | -0.0001 | 0.3781 | 0.0093 | -0.0020 | 0.1287 | 0.5555 | 0 | 0 | 0.2110 |
| logistic_offset | 0.1222 | 0.0010 | 0.3775 | 0.0372 | 0.0260 | 0.2017 | 0.6608 | 0 | 0 | -0.3120 |
| lightgbm | 0.1224 | 0.0012 | 0.3793 | 0.0240 | 0.0128 | 0.0882 | 0.5459 | 9 | 2 | 6.7540 |

## Feature-group ablations (ridge residual; delta-Brier vs market, lower=better)
- market_only: dBrier=0.0000 dECE_win=None IC=None
- market+time: dBrier=0.0004 dECE_win=0.0050 IC=0.1113
- market+kalshi_book: dBrier=-0.0002 dECE_win=0.0044 IC=0.2544
- market+underlying: dBrier=0.0000 dECE_win=0.0048 IC=0.0585
- market+deribit: dBrier=-0.0000 dECE_win=0.0022 IC=0.2145
- market+all: dBrier=0.0007 dECE_win=0.0042 IC=0.0884

## Walk-forward stability (delta-Brier per fold; negative=beats market)
- market_only: deltas=[0.0, 0.0, 0.0] ic=[] stable_improvement=False
- ridge: deltas=[np.float64(0.08143), np.float64(0.00077), np.float64(0.00063)] ic=[-0.0663, 0.0607, 0.0965] stable_improvement=False
- elasticnet: deltas=[np.float64(0.01293), np.float64(-3e-05), np.float64(-9e-05)] ic=[0.0041, 0.1084, 0.135] stable_improvement=False
- logistic_offset: deltas=[0.1032, 0.00618, 0.00095] ic=[-0.0773, 0.0363, 0.2067] stable_improvement=False
- lightgbm: deltas=[0.04813, 0.0036, 0.00215] ic=[-0.1896, 0.0267, 0.0886] stable_improvement=False

## Top features (incremental residual signal, if any)
- ridge: {'perp_trade_intensity_60s': -0.08274, 'spot_trade_intensity_60s': 0.07702, 'deribit_atm_iv': 0.07268, 'deribit_historical_vol': -0.04755, 'deribit_dvol': -0.04427, 'spot_perp_basis': -0.04034, 'yes_bid': 0.03694, 'executable_no_buy_price': -0.03694}
- elasticnet: {'deribit_put_call_volume_ratio': 0.02055, 'deribit_historical_vol': -0.01582, 'spot_perp_basis': -0.01233, 'deribit_atm_iv': 0.00866, 'no_spread': -0.00765, 'yes_spread': -0.00724, 'realized_vol_180s': 0.00594, 'fraction_window_elapsed': 0.00504}
- logistic_offset: {'__logit_market__': 1.85801, 'perp_trade_intensity_60s': -0.65594, 'spot_trade_intensity_60s': 0.62854, 'deribit_atm_iv': 0.57014, 'deribit_historical_vol': -0.40109, 'deribit_dvol': -0.3913, 'spot_perp_basis': -0.29984, 'realized_vol_180s': 0.25387}
- lightgbm: {'spot_sigma_per_sqrt_s': 328, 'deribit_put_call_oi_ratio': 155, 'executable_no_buy_price': 151, 'realized_vol_window_to_date': 148, 'deribit_atm_iv': 95, 'executable_yes_buy_price': 79, 'deribit_options_open_interest_total': 76, 'deribit_put_call_volume_ratio': 76}

## Verdict
- any model beats market OOS: **False** []
- any model multi-window final edge: **False** []
- **recommendation: NO residual model beats market-implied out-of-sample (IC ~ 0, delta-Brier >= 0). The apparent raw edge was model miscalibration, not alpha. Continue DATA COLLECTION and research only; do not promote, do not lower gates, do not remove buffers.**

## Safety
- STAGED/report-only; market is the baseline; buffers intact; +2c gate intact; no promotion; live/paper disabled; live_submission_allowed=false.
