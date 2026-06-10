# Kalshi market-shrink alpha sweep — KXBTC15M

> STAGED / report-only. `p = alpha*p_model + (1-alpha)*p_market`. alpha selected ONLY by out-of-sample window ECE (never in-sample P&L). No promotion; live disabled.

- split (windows): {'n_windows': 301, 'train_windows': 150, 'calib_windows': 75, 'test_windows': 74, 'embargo_windows': 1}  base_rate(TEST): 0.4294
- market-implied baseline: ECE(window)=0.0301 brier=0.1040
- **recommended: base=platt alpha=0.5 (ECE_window=0.0173, beats_market=True)**
- alpha stability across folds: stable=True alphas=[0.3, 0.0, 0.1] (min=0.0 max=0.3)
- **conservative alpha (stability-aware): 0.1** — main-split alpha=0.5 but walk-forward median alpha=0.1: the model's marginal value over market is within noise — shrink HEAVILY toward market (use the lower alpha).

## alpha sweep by base (ECE window; lower=better). alpha=0 is pure market, alpha=1 is pure model.

### base = raw
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1040 | 0.3265 | 0.0301 | 0.0301 | 0.93 |
| 0.1 | 0.1039 | 0.3267 | 0.0273 | 0.0310 | 0.78 |
| 0.2 | 0.1039 | 0.3272 | 0.0266 | 0.0314 | 0.63 |
| 0.3 | 0.1040 | 0.3279 | 0.0249 | 0.0368 | 0.48 |
| 0.4 | 0.1041 | 0.3289 | 0.0252 | 0.0352 | 0.33 |
| 0.5 | 0.1044 | 0.3302 | 0.0259 | 0.0364 | 0.19 |
| 0.6 | 0.1047 | 0.3317 | 0.0282 | 0.0375 | 0.04 |
| 0.7 | 0.1051 | 0.3336 | 0.0280 | 0.0368 | -0.11 |
| 0.8 | 0.1056 | 0.3358 | 0.0282 | 0.0456 | -0.26 |
| 0.9 | 0.1061 | 0.3384 | 0.0258 | 0.0465 | -0.41 |
| 1.0 | 0.1068 | 0.3415 | 0.0251 | 0.0500 | -0.56 |

### base = platt
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1040 | 0.3265 | 0.0301 | 0.0301 | 0.93 |
| 0.1 | 0.1040 | 0.3288 | 0.0307 | 0.0257 | 0.59 |
| 0.2 | 0.1042 | 0.3315 | 0.0336 | 0.0270 | 0.25 |
| 0.3 | 0.1045 | 0.3345 | 0.0358 | 0.0194 | -0.09 |
| 0.4 | 0.1049 | 0.3378 | 0.0388 | 0.0184 | -0.42 |
| 0.5 | 0.1055 | 0.3414 | 0.0442 | 0.0173 | -0.76 |
| 0.6 | 0.1063 | 0.3454 | 0.0504 | 0.0290 | -1.10 |
| 0.7 | 0.1072 | 0.3498 | 0.0559 | 0.0366 | -1.44 |
| 0.8 | 0.1082 | 0.3546 | 0.0611 | 0.0429 | -1.78 |
| 0.9 | 0.1094 | 0.3598 | 0.0677 | 0.0431 | -2.11 |
| 1.0 | 0.1108 | 0.3655 | 0.0732 | 0.0500 | -2.45 |

### base = isotonic
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1040 | 0.3265 | 0.0301 | 0.0301 | 0.93 |
| 0.1 | 0.1042 | 0.3277 | 0.0296 | 0.0302 | 0.65 |
| 0.2 | 0.1045 | 0.3292 | 0.0294 | 0.0276 | 0.37 |
| 0.3 | 0.1050 | 0.3309 | 0.0296 | 0.0307 | 0.09 |
| 0.4 | 0.1055 | 0.3329 | 0.0317 | 0.0245 | -0.18 |
| 0.5 | 0.1061 | 0.3352 | 0.0329 | 0.0340 | -0.46 |
| 0.6 | 0.1069 | 0.3378 | 0.0335 | 0.0340 | -0.74 |
| 0.7 | 0.1077 | 0.3407 | 0.0404 | 0.0412 | -1.02 |
| 0.8 | 0.1087 | 0.3439 | 0.0449 | 0.0514 | -1.30 |
| 0.9 | 0.1097 | 0.3475 | 0.0467 | 0.0612 | -1.57 |
| 1.0 | 0.1109 | 0.3516 | 0.0504 | 0.0669 | -1.85 |

## Safety
- STAGED/report-only; alpha not promoted; no manifest changed; live disabled.
