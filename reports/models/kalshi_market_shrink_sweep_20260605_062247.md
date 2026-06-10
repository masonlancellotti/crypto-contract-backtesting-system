# Kalshi market-shrink alpha sweep — KXBTC15M

> STAGED / report-only. `p = alpha*p_model + (1-alpha)*p_market`. alpha selected ONLY by out-of-sample window ECE (never in-sample P&L). No promotion; live disabled.

- split (windows): {'n_windows': 299, 'train_windows': 150, 'calib_windows': 75, 'test_windows': 72, 'embargo_windows': 1}  base_rate(TEST): 0.4271
- market-implied baseline: ECE(window)=0.0303 brier=0.1059
- **recommended: base=platt alpha=0.4 (ECE_window=0.0200, beats_market=True)**
- alpha stability across folds: stable=True alphas=[0.1, 0.0, 0.0] (min=0.0 max=0.1)
- **conservative alpha (stability-aware): 0.0** — main-split alpha=0.4 but walk-forward median alpha=0.0: the model's marginal value over market is within noise — shrink HEAVILY toward market (use the lower alpha).

## alpha sweep by base (ECE window; lower=better). alpha=0 is pure market, alpha=1 is pure model.

### base = raw
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1059 | 0.3304 | 0.0277 | 0.0303 | 1.05 |
| 0.1 | 0.1058 | 0.3308 | 0.0263 | 0.0300 | 0.88 |
| 0.2 | 0.1059 | 0.3315 | 0.0256 | 0.0331 | 0.72 |
| 0.3 | 0.1060 | 0.3325 | 0.0243 | 0.0387 | 0.56 |
| 0.4 | 0.1062 | 0.3336 | 0.0242 | 0.0371 | 0.40 |
| 0.5 | 0.1065 | 0.3351 | 0.0257 | 0.0384 | 0.23 |
| 0.6 | 0.1069 | 0.3369 | 0.0277 | 0.0395 | 0.07 |
| 0.7 | 0.1074 | 0.3389 | 0.0293 | 0.0401 | -0.09 |
| 0.8 | 0.1079 | 0.3414 | 0.0300 | 0.0487 | -0.25 |
| 0.9 | 0.1086 | 0.3442 | 0.0276 | 0.0502 | -0.42 |
| 1.0 | 0.1093 | 0.3475 | 0.0267 | 0.0539 | -0.58 |

### base = platt
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1059 | 0.3304 | 0.0277 | 0.0303 | 1.05 |
| 0.1 | 0.1059 | 0.3329 | 0.0296 | 0.0261 | 0.70 |
| 0.2 | 0.1062 | 0.3358 | 0.0323 | 0.0279 | 0.34 |
| 0.3 | 0.1065 | 0.3389 | 0.0353 | 0.0222 | -0.01 |
| 0.4 | 0.1070 | 0.3424 | 0.0390 | 0.0200 | -0.36 |
| 0.5 | 0.1077 | 0.3463 | 0.0449 | 0.0205 | -0.71 |
| 0.6 | 0.1085 | 0.3505 | 0.0513 | 0.0323 | -1.06 |
| 0.7 | 0.1095 | 0.3550 | 0.0567 | 0.0405 | -1.41 |
| 0.8 | 0.1106 | 0.3601 | 0.0620 | 0.0464 | -1.76 |
| 0.9 | 0.1119 | 0.3655 | 0.0686 | 0.0470 | -2.11 |
| 1.0 | 0.1134 | 0.3715 | 0.0741 | 0.0531 | -2.46 |

### base = isotonic
| alpha | brier | log_loss | ECE(row) | ECE(window) | YES_overpred(c) |
|---|---|---|---|---|---|
| 0.0 | 0.1059 | 0.3304 | 0.0277 | 0.0303 | 1.05 |
| 0.1 | 0.1061 | 0.3316 | 0.0276 | 0.0292 | 0.76 |
| 0.2 | 0.1064 | 0.3331 | 0.0287 | 0.0254 | 0.48 |
| 0.3 | 0.1068 | 0.3349 | 0.0288 | 0.0279 | 0.19 |
| 0.4 | 0.1073 | 0.3369 | 0.0285 | 0.0221 | -0.09 |
| 0.5 | 0.1080 | 0.3392 | 0.0308 | 0.0303 | -0.38 |
| 0.6 | 0.1087 | 0.3419 | 0.0338 | 0.0334 | -0.66 |
| 0.7 | 0.1096 | 0.3448 | 0.0416 | 0.0404 | -0.95 |
| 0.8 | 0.1105 | 0.3481 | 0.0444 | 0.0516 | -1.23 |
| 0.9 | 0.1116 | 0.3518 | 0.0461 | 0.0616 | -1.52 |
| 1.0 | 0.1128 | 0.3559 | 0.0498 | 0.0667 | -1.80 |

## Safety
- STAGED/report-only; alpha not promoted; no manifest changed; live disabled.
