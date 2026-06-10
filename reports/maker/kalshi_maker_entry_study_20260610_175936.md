# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-through)

> READ-ONLY research. REAL trade prints, CERTAIN fills only: a resting bid counts as filled when the tape traded strictly THROUGH the level (queue-position-free). Conservative on fill count, but fills/outcomes come from actual flow. No orders, no paper, no promotion; live disabled.

- windows: 552  decision points: 7241  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0154
- maker fee rate: 0.0 (ASSUMED_ZERO_MAKER_FEE); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 7241 | 5491 | 75.8% | 3.1 | 39.9% | 58.5% | -3.66 | -2.77 | -3.84 | 549 |
| YES/join/180 | 7241 | 5972 | 82.5% | 3.7 | 39.6% | 66.8% | -3.69 | -3.04 | -3.84 | 549 |
| YES/join/300 | 7241 | 6084 | 84.0% | 3.8 | 39.5% | 69.7% | -3.73 | -3.14 | -3.84 | 549 |
| YES/join/close | 7241 | 6164 | 85.1% | 3.9 | 39.6% | 71.9% | -3.72 | -3.16 | -3.84 | 549 |
| YES/improve/60 | 585 | 506 | 86.5% | 0.6 | 44.9% | 50.6% | -5.12 | -4.42 | -7.58 | 323 |
| YES/improve/180 | 585 | 530 | 90.6% | 0.7 | 44.2% | 60.0% | -5.62 | -5.09 | -7.58 | 333 |
| YES/improve/300 | 585 | 535 | 91.5% | 0.8 | 44.3% | 60.0% | -5.46 | -4.99 | -7.58 | 334 |
| YES/improve/close | 585 | 545 | 93.2% | 0.8 | 44.0% | 67.5% | -5.58 | -5.20 | -7.58 | 336 |
| NO/join/60 | 7241 | 5306 | 73.3% | 3.2 | 51.6% | 66.6% | 0.38 | 0.28 | -0.16 | 549 |
| NO/join/180 | 7241 | 5806 | 80.2% | 3.8 | 51.1% | 73.9% | 0.19 | 0.15 | -0.16 | 549 |
| NO/join/300 | 7241 | 5938 | 82.0% | 4.0 | 51.1% | 76.1% | 0.20 | 0.17 | -0.16 | 549 |
| NO/join/close | 7241 | 6035 | 83.3% | 4.1 | 50.9% | 79.3% | 0.02 | 0.01 | -0.16 | 549 |
| NO/improve/60 | 585 | 516 | 88.2% | 0.6 | 51.6% | 75.4% | 2.45 | 2.16 | 1.00 | 322 |
| NO/improve/180 | 585 | 535 | 91.5% | 0.6 | 51.8% | 82.0% | 2.72 | 2.49 | 1.00 | 333 |
| NO/improve/300 | 585 | 542 | 92.6% | 0.7 | 51.3% | 93.0% | 2.27 | 2.10 | 1.00 | 334 |
| NO/improve/close | 585 | 548 | 93.7% | 0.7 | 51.3% | 100.0% | 2.30 | 2.15 | 1.00 | 336 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 7241 | 6164 | 85.1% | 3.9 | 39.6% | 71.9% | -5.31 | -4.52 | -3.84 | 549 |
| NO/join/close | 7241 | 6035 | 83.3% | 4.1 | 50.9% | 79.3% | -1.58 | -1.32 | -0.16 | 549 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1373 | 1072 | 78.1% | 9.3 | 4.5% | 3.7% | -0.06 | -0.05 | -0.71 | 299 |
| YES/[10c,20c) | 690 | 678 | 98.3% | 4.7 | 11.1% | 100.0% | -3.21 | -3.15 | -4.04 | 285 |
| YES/[20c,30c) | 676 | 648 | 95.9% | 3.5 | 18.4% | 53.6% | -6.03 | -5.78 | -7.99 | 293 |
| YES/[30c,40c) | 607 | 587 | 96.7% | 2.5 | 27.9% | 100.0% | -6.58 | -6.36 | -7.47 | 289 |
| YES/[40c,50c) | 636 | 601 | 94.5% | 2.6 | 34.9% | 100.0% | -9.57 | -9.04 | -9.24 | 318 |
| YES/[50c,60c) | 687 | 643 | 93.6% | 3.3 | 46.5% | 100.0% | -7.58 | -7.10 | -7.57 | 311 |
| YES/[60c,70c) | 560 | 513 | 91.6% | 2.4 | 59.5% | 100.0% | -5.16 | -4.73 | -4.84 | 246 |
| YES/[70c,80c) | 470 | 430 | 91.5% | 3.0 | 70.5% | 100.0% | -3.97 | -3.63 | -4.56 | 216 |
| YES/[80c,90c) | 527 | 453 | 86.0% | 3.6 | 86.3% | 100.0% | 1.58 | 1.36 | 1.21 | 199 |
| YES/[90c,100c) | 1015 | 539 | 53.1% | 6.1 | 97.4% | 100.0% | 2.53 | 1.35 | 1.15 | 191 |
| NO/[0c,10c) | 1021 | 767 | 75.1% | 9.2 | 1.4% | 1.6% | -3.18 | -2.39 | -3.47 | 214 |
| NO/[10c,20c) | 526 | 517 | 98.3% | 4.8 | 10.4% | 100.0% | -3.76 | -3.70 | -4.81 | 217 |
| NO/[20c,30c) | 475 | 446 | 93.9% | 3.7 | 22.4% | 100.0% | -2.02 | -1.90 | -0.50 | 227 |
| NO/[30c,40c) | 567 | 540 | 95.2% | 2.8 | 34.3% | 100.0% | -0.18 | -0.17 | -0.25 | 258 |
| NO/[40c,50c) | 681 | 641 | 94.1% | 2.9 | 47.4% | 100.0% | 2.72 | 2.56 | 2.50 | 309 |
| NO/[50c,60c) | 643 | 579 | 90.0% | 3.3 | 58.0% | 100.0% | 3.69 | 3.33 | 4.34 | 304 |
| NO/[60c,70c) | 604 | 543 | 89.9% | 3.5 | 66.3% | 100.0% | 1.91 | 1.71 | 2.14 | 266 |
| NO/[70c,80c) | 667 | 601 | 90.1% | 3.0 | 77.2% | 100.0% | 2.68 | 2.41 | 1.79 | 271 |
| NO/[80c,90c) | 696 | 608 | 87.4% | 3.3 | 86.2% | 100.0% | 1.49 | 1.30 | 0.96 | 270 |
| NO/[90c,100c) | 1361 | 793 | 58.3% | 7.4 | 92.6% | 100.0% | -2.44 | -1.42 | -1.75 | 276 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 2180 | 1897 | 87.0% | 4.7 | 38.3% | 85.5% | -2.14 | -1.87 | -2.47 | 536 |
| YES/420-660s | 2132 | 2007 | 94.1% | 4.4 | 41.2% | 96.8% | -4.32 | -4.07 | -4.85 | 534 |
| YES/<180s | 1337 | 742 | 55.5% | 3.4 | 35.6% | 57.0% | -1.24 | -0.69 | -0.56 | 384 |
| YES/>=660s | 1592 | 1518 | 95.4% | 3.1 | 41.0% | 97.3% | -6.09 | -5.81 | -7.13 | 508 |
| NO/180-420s | 2180 | 1837 | 84.3% | 5.0 | 49.6% | 87.5% | -1.30 | -1.10 | -1.00 | 538 |
| NO/420-660s | 2132 | 1958 | 91.8% | 4.3 | 51.6% | 99.4% | 0.54 | 0.50 | 0.49 | 535 |
| NO/<180s | 1337 | 745 | 55.7% | 3.3 | 46.7% | 65.2% | -3.47 | -1.94 | -2.32 | 377 |
| NO/>=660s | 1592 | 1495 | 93.9% | 3.6 | 53.6% | 100.0% | 2.70 | 2.53 | 1.91 | 510 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 34 | 30 | 88.2% | 6.9 | 86.7% | 75.0% | 16.28 | 14.36 | 12.30 | 3 |
| YES/2026-06-02 | 1270 | 1092 | 86.0% | 3.8 | 34.5% | 61.8% | -6.71 | -5.77 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1049 | 85.1% | 3.9 | 37.7% | 70.5% | -6.97 | -5.94 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 665 | 79.3% | 3.7 | 36.7% | 70.7% | -4.99 | -3.96 | -3.90 | 73 |
| YES/2026-06-05 | 979 | 849 | 86.7% | 3.2 | 43.8% | 68.5% | 1.10 | 0.95 | 0.50 | 73 |
| YES/2026-06-06 | 879 | 781 | 88.9% | 3.3 | 39.7% | 80.6% | -4.82 | -4.28 | -5.49 | 64 |
| YES/2026-06-07 | 1129 | 963 | 85.3% | 4.5 | 48.2% | 76.5% | 2.59 | 2.21 | 1.41 | 87 |
| YES/2026-06-08 | 569 | 475 | 83.5% | 4.8 | 39.2% | 76.6% | -4.36 | -3.64 | -4.15 | 48 |
| YES/2026-06-09 | 178 | 137 | 77.0% | 4.6 | 29.9% | 87.8% | -4.40 | -3.38 | -0.43 | 15 |
| YES/2026-06-10 | 132 | 123 | 93.2% | 8.6 | 19.5% | 66.7% | -19.80 | -18.45 | -20.28 | 9 |
| NO/2026-06-01 | 34 | 31 | 91.2% | 3.7 | 9.7% | 66.7% | -16.66 | -15.19 | -16.62 | 3 |
| NO/2026-06-02 | 1270 | 1033 | 81.3% | 4.1 | 56.2% | 85.2% | 3.04 | 2.48 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1019 | 82.7% | 4.1 | 53.0% | 78.9% | 3.24 | 2.68 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 652 | 77.7% | 4.7 | 50.3% | 77.0% | 0.08 | 0.07 | 0.14 | 72 |
| NO/2026-06-05 | 979 | 815 | 83.2% | 3.2 | 46.6% | 84.1% | -4.88 | -4.06 | -4.42 | 73 |
| NO/2026-06-06 | 879 | 777 | 88.4% | 3.4 | 53.3% | 74.5% | 2.53 | 2.24 | 1.35 | 64 |
| NO/2026-06-07 | 1129 | 973 | 86.2% | 5.1 | 43.3% | 75.0% | -5.79 | -4.99 | -5.47 | 87 |
| NO/2026-06-08 | 569 | 479 | 84.2% | 4.2 | 51.1% | 73.3% | 1.37 | 1.15 | 0.42 | 48 |
| NO/2026-06-09 | 178 | 145 | 81.5% | 4.7 | 52.4% | 75.8% | -5.86 | -4.78 | -3.40 | 16 |
| NO/2026-06-10 | 132 | 111 | 84.1% | 6.8 | 75.7% | 85.7% | 17.61 | 14.81 | 15.98 | 9 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 7241  double fills: 5432 (75.0%) across 548 windows
- mean pair cost: 0.9903  mean locked net per pair: 0.0097  total locked net: 52.698

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
