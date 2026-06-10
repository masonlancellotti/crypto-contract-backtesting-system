# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-front)

> READ-ONLY research. REAL trade prints, FRONT-OF-QUEUE assumption: a resting bid counts as filled when the tape traded AT or through the level. OPTIMISTIC upper bound — real queue position would forfeit some at-level fills. No orders, no paper, no promotion; live disabled.

- windows: 560  decision points: 7346  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0154
- maker fee rate: 0.0 (ASSUMED_ZERO_MAKER_FEE); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 7346 | 6934 | 94.4% | 0.4 | 43.4% | 65.3% | -1.84 | -1.74 | -3.73 | 559 |
| YES/join/180 | 7346 | 7064 | 96.2% | 0.4 | 43.3% | 78.4% | -1.89 | -1.82 | -3.73 | 559 |
| YES/join/300 | 7346 | 7103 | 96.7% | 0.4 | 43.2% | 84.8% | -1.89 | -1.83 | -3.73 | 559 |
| YES/join/close | 7346 | 7135 | 97.1% | 0.4 | 43.2% | 93.4% | -1.96 | -1.91 | -3.73 | 559 |
| YES/improve/60 | 593 | 539 | 90.9% | 0.4 | 45.8% | 46.3% | -4.33 | -3.94 | -7.43 | 337 |
| YES/improve/180 | 593 | 551 | 92.9% | 0.4 | 45.4% | 52.4% | -4.74 | -4.41 | -7.43 | 344 |
| YES/improve/300 | 593 | 554 | 93.4% | 0.4 | 45.5% | 51.3% | -4.64 | -4.34 | -7.43 | 345 |
| YES/improve/close | 593 | 564 | 95.1% | 0.4 | 45.4% | 55.2% | -4.66 | -4.43 | -7.43 | 348 |
| NO/join/60 | 7346 | 6895 | 93.9% | 0.4 | 54.1% | 75.2% | 1.57 | 1.48 | -0.28 | 559 |
| NO/join/180 | 7346 | 7014 | 95.5% | 0.4 | 54.0% | 84.6% | 1.55 | 1.48 | -0.28 | 559 |
| NO/join/300 | 7346 | 7057 | 96.1% | 0.4 | 54.0% | 90.0% | 1.54 | 1.48 | -0.28 | 559 |
| NO/join/close | 7346 | 7095 | 96.6% | 0.4 | 53.8% | 100.0% | 1.40 | 1.35 | -0.28 | 559 |
| NO/improve/60 | 593 | 546 | 92.1% | 0.4 | 51.8% | 80.9% | 2.67 | 2.46 | 0.86 | 336 |
| NO/improve/180 | 593 | 557 | 93.9% | 0.4 | 52.2% | 83.3% | 3.07 | 2.88 | 0.86 | 344 |
| NO/improve/300 | 593 | 561 | 94.6% | 0.4 | 52.0% | 90.6% | 2.89 | 2.73 | 0.86 | 345 |
| NO/improve/close | 593 | 567 | 95.6% | 0.4 | 52.0% | 100.0% | 2.91 | 2.78 | 0.86 | 347 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 7346 | 7135 | 97.1% | 0.4 | 43.2% | 93.4% | -3.50 | -3.40 | -3.73 | 559 |
| NO/join/close | 7346 | 7095 | 96.6% | 0.4 | 53.8% | 100.0% | -0.15 | -0.14 | -0.28 | 559 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1390 | 1384 | 99.6% | 0.6 | 3.9% | 83.3% | 0.28 | 0.28 | -0.76 | 310 |
| YES/[10c,20c) | 696 | 690 | 99.1% | 0.3 | 11.7% | 100.0% | -2.54 | -2.52 | -4.14 | 291 |
| YES/[20c,30c) | 682 | 665 | 97.5% | 0.4 | 20.0% | 23.5% | -4.38 | -4.27 | -7.72 | 301 |
| YES/[30c,40c) | 614 | 603 | 98.2% | 0.4 | 29.4% | 100.0% | -5.18 | -5.08 | -7.17 | 297 |
| YES/[40c,50c) | 648 | 636 | 98.1% | 0.4 | 37.9% | 100.0% | -6.64 | -6.52 | -8.74 | 335 |
| YES/[50c,60c) | 693 | 677 | 97.7% | 0.4 | 48.9% | 100.0% | -5.23 | -5.11 | -7.43 | 323 |
| YES/[60c,70c) | 570 | 550 | 96.5% | 0.4 | 61.5% | 100.0% | -3.19 | -3.08 | -4.91 | 265 |
| YES/[70c,80c) | 482 | 467 | 96.9% | 0.3 | 72.6% | 100.0% | -1.84 | -1.78 | -4.12 | 232 |
| YES/[80c,90c) | 532 | 512 | 96.2% | 0.4 | 87.7% | 100.0% | 2.98 | 2.87 | 1.14 | 216 |
| YES/[90c,100c) | 1039 | 951 | 91.5% | 0.6 | 98.5% | 100.0% | 2.37 | 2.17 | 1.17 | 226 |
| NO/[0c,10c) | 1045 | 1043 | 99.8% | 0.6 | 1.2% | 100.0% | -2.29 | -2.29 | -3.48 | 230 |
| NO/[10c,20c) | 531 | 528 | 99.4% | 0.3 | 11.6% | 100.0% | -2.66 | -2.65 | -4.75 | 221 |
| NO/[20c,30c) | 487 | 473 | 97.1% | 0.4 | 24.5% | 100.0% | 0.07 | 0.07 | -0.94 | 238 |
| NO/[30c,40c) | 577 | 570 | 98.8% | 0.4 | 36.7% | 100.0% | 2.25 | 2.22 | -0.18 | 273 |
| NO/[40c,50c) | 687 | 674 | 98.1% | 0.4 | 49.4% | 100.0% | 4.70 | 4.61 | 2.36 | 323 |
| NO/[50c,60c) | 655 | 623 | 95.1% | 0.4 | 59.7% | 100.0% | 5.36 | 5.10 | 3.83 | 323 |
| NO/[60c,70c) | 611 | 586 | 95.9% | 0.4 | 68.1% | 100.0% | 3.69 | 3.54 | 1.85 | 285 |
| NO/[70c,80c) | 673 | 655 | 97.3% | 0.3 | 78.6% | 100.0% | 4.06 | 3.95 | 1.53 | 294 |
| NO/[80c,90c) | 702 | 679 | 96.7% | 0.3 | 87.6% | 100.0% | 2.88 | 2.79 | 1.06 | 289 |
| NO/[90c,100c) | 1378 | 1264 | 91.7% | 0.6 | 95.3% | 100.0% | -0.71 | -0.65 | -1.71 | 305 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 2212 | 2150 | 97.2% | 0.4 | 43.3% | 93.5% | -0.76 | -0.74 | -2.33 | 556 |
| YES/420-660s | 2164 | 2117 | 97.8% | 0.4 | 43.7% | 91.5% | -2.80 | -2.74 | -4.67 | 543 |
| YES/<180s | 1358 | 1279 | 94.2% | 0.6 | 42.3% | 94.9% | 0.44 | 0.41 | -0.56 | 546 |
| YES/>=660s | 1612 | 1589 | 98.6% | 0.4 | 43.0% | 91.3% | -4.40 | -4.34 | -7.05 | 521 |
| NO/180-420s | 2212 | 2150 | 97.2% | 0.4 | 54.0% | 100.0% | 0.14 | 0.13 | -1.14 | 557 |
| NO/420-660s | 2164 | 2107 | 97.4% | 0.4 | 54.1% | 100.0% | 2.15 | 2.09 | 0.31 | 545 |
| NO/<180s | 1358 | 1257 | 92.6% | 0.6 | 51.0% | 100.0% | -1.36 | -1.26 | -2.31 | 542 |
| NO/>=660s | 1612 | 1581 | 98.1% | 0.4 | 55.4% | 100.0% | 4.29 | 4.21 | 1.83 | 521 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 94 | 93 | 98.9% | 0.6 | 62.4% | 100.0% | 2.39 | 2.37 | -0.24 | 7 |
| YES/2026-06-02 | 1270 | 1241 | 97.7% | 0.4 | 36.9% | 100.0% | -5.02 | -4.91 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1202 | 97.6% | 0.4 | 41.2% | 96.7% | -4.79 | -4.67 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 802 | 95.6% | 0.5 | 41.1% | 100.0% | -3.16 | -3.02 | -3.90 | 74 |
| YES/2026-06-05 | 979 | 962 | 98.3% | 0.4 | 46.2% | 100.0% | 2.35 | 2.31 | 0.50 | 73 |
| YES/2026-06-06 | 879 | 855 | 97.3% | 0.4 | 42.7% | 100.0% | -3.36 | -3.27 | -5.49 | 64 |
| YES/2026-06-07 | 1129 | 1094 | 96.9% | 0.3 | 52.0% | 62.9% | 3.95 | 3.83 | 1.41 | 87 |
| YES/2026-06-08 | 614 | 601 | 97.9% | 0.4 | 46.4% | 100.0% | -0.83 | -0.81 | -2.41 | 52 |
| YES/2026-06-09 | 178 | 158 | 88.8% | 0.5 | 36.1% | 100.0% | -3.09 | -2.74 | -0.43 | 16 |
| YES/2026-06-10 | 132 | 127 | 96.2% | 5.9 | 19.7% | 100.0% | -19.18 | -18.45 | -20.28 | 9 |
| NO/2026-06-01 | 94 | 91 | 96.8% | 0.6 | 35.2% | 100.0% | -2.77 | -2.69 | -3.96 | 7 |
| NO/2026-06-02 | 1270 | 1228 | 96.7% | 0.4 | 60.3% | 100.0% | 4.80 | 4.64 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1183 | 96.0% | 0.5 | 55.7% | 100.0% | 4.54 | 4.36 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 810 | 96.5% | 0.5 | 54.7% | 100.0% | 1.83 | 1.76 | 0.14 | 74 |
| NO/2026-06-05 | 979 | 948 | 96.8% | 0.4 | 51.4% | 100.0% | -2.91 | -2.81 | -4.42 | 73 |
| NO/2026-06-06 | 879 | 860 | 97.8% | 0.4 | 54.8% | 100.0% | 3.50 | 3.43 | 1.35 | 64 |
| NO/2026-06-07 | 1129 | 1094 | 96.9% | 0.4 | 46.0% | 100.0% | -4.03 | -3.91 | -5.47 | 87 |
| NO/2026-06-08 | 614 | 598 | 97.4% | 0.4 | 51.2% | 100.0% | 0.43 | 0.42 | -1.31 | 52 |
| NO/2026-06-09 | 178 | 164 | 92.1% | 0.4 | 53.0% | 100.0% | -4.23 | -3.90 | -3.40 | 16 |
| NO/2026-06-10 | 132 | 119 | 90.2% | 5.1 | 74.8% | 100.0% | 16.79 | 15.14 | 15.98 | 9 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 7346  double fills: 6898 (93.9%) across 559 windows
- mean pair cost: 0.9912  mean locked net per pair: 0.0088  total locked net: 60.813

## Verdict

- sides with POSITIVE conservative maker EV: ['NO']
- sides where maker(lower bound) beats taker: ['YES', 'NO']
- POSITIVE lower bound: even counting only adverse trade-through fills, resting at the bid earned more than it cost on: NO. Worth a deeper study with real trade prints / WS book data before any paper or live step.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
