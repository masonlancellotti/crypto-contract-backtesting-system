# Kalshi maker-entry feasibility study — KXBTC15M

> READ-ONLY research. Conservative trade-through fill model: a resting bid is counted filled ONLY when a later snapshot's same-side ask crosses to/below the limit, so fills are undercounted AND adversely selected — every maker EV here is a LOWER BOUND. No orders, no paper, no promotion; live disabled.

- windows: 769  decision points: 9646  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0154
- maker fee rate: 0.0 (ASSUMED_ZERO_MAKER_FEE); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 9646 | 7107 | 73.7% | 7.7 | 39.0% | 66.0% | -3.55 | -2.61 | -2.92 | 766 |
| YES/join/180 | 9646 | 7929 | 82.2% | 7.8 | 38.9% | 79.1% | -3.51 | -2.89 | -2.92 | 766 |
| YES/join/300 | 9646 | 8116 | 84.1% | 7.9 | 38.9% | 84.0% | -3.56 | -2.99 | -2.92 | 766 |
| YES/join/close | 9646 | 8232 | 85.3% | 7.9 | 38.9% | 87.8% | -3.58 | -3.05 | -2.92 | 766 |
| YES/improve/60 | 815 | 629 | 77.2% | 5.6 | 45.8% | 56.5% | -4.28 | -3.30 | -5.72 | 412 |
| YES/improve/180 | 815 | 700 | 85.9% | 7.0 | 44.3% | 72.2% | -5.66 | -4.86 | -5.72 | 437 |
| YES/improve/300 | 815 | 713 | 87.5% | 7.2 | 44.2% | 76.5% | -5.73 | -5.01 | -5.72 | 439 |
| YES/improve/close | 815 | 730 | 89.6% | 7.5 | 44.1% | 83.5% | -5.64 | -5.05 | -5.72 | 441 |
| NO/join/60 | 9646 | 6874 | 71.3% | 7.7 | 46.5% | 72.4% | -1.93 | -1.38 | -1.09 | 766 |
| NO/join/180 | 9646 | 7679 | 79.6% | 7.9 | 46.3% | 83.5% | -1.96 | -1.56 | -1.09 | 766 |
| NO/join/300 | 9646 | 7877 | 81.7% | 7.9 | 46.3% | 87.8% | -2.00 | -1.63 | -1.09 | 766 |
| NO/join/close | 9646 | 8023 | 83.2% | 7.9 | 46.2% | 91.9% | -2.05 | -1.70 | -1.09 | 766 |
| NO/improve/60 | 815 | 633 | 77.7% | 5.7 | 46.4% | 70.3% | -1.18 | -0.92 | -0.60 | 405 |
| NO/improve/180 | 815 | 692 | 84.9% | 7.4 | 45.4% | 87.8% | -2.30 | -1.95 | -0.60 | 428 |
| NO/improve/300 | 815 | 708 | 86.9% | 7.5 | 45.2% | 95.3% | -2.52 | -2.19 | -0.60 | 432 |
| NO/improve/close | 815 | 717 | 88.0% | 7.6 | 45.2% | 100.0% | -2.44 | -2.14 | -0.60 | 435 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 9646 | 8232 | 85.3% | 7.9 | 38.9% | 87.8% | -5.15 | -4.40 | -2.92 | 766 |
| NO/join/close | 9646 | 8023 | 83.2% | 7.9 | 46.2% | 91.9% | -3.63 | -3.02 | -1.09 | 766 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1778 | 1606 | 90.3% | 11.3 | 3.5% | 8.1% | -0.44 | -0.40 | -1.02 | 396 |
| YES/[10c,20c) | 889 | 864 | 97.2% | 11.4 | 11.0% | 96.0% | -3.25 | -3.16 | -3.27 | 371 |
| YES/[20c,30c) | 876 | 828 | 94.5% | 7.8 | 19.7% | 72.9% | -4.73 | -4.47 | -5.16 | 383 |
| YES/[30c,40c) | 824 | 780 | 94.7% | 7.8 | 30.1% | 100.0% | -4.47 | -4.23 | -3.91 | 393 |
| YES/[40c,50c) | 841 | 776 | 92.3% | 7.8 | 37.0% | 100.0% | -7.49 | -6.91 | -5.86 | 413 |
| YES/[50c,60c) | 886 | 805 | 90.9% | 7.9 | 45.3% | 98.8% | -8.89 | -8.08 | -7.35 | 401 |
| YES/[60c,70c) | 765 | 680 | 88.9% | 7.8 | 58.8% | 100.0% | -5.77 | -5.13 | -4.32 | 335 |
| YES/[70c,80c) | 676 | 580 | 85.8% | 7.8 | 69.1% | 100.0% | -5.36 | -4.60 | -4.11 | 295 |
| YES/[80c,90c) | 735 | 589 | 80.1% | 7.8 | 84.7% | 100.0% | -0.01 | -0.01 | 0.71 | 261 |
| YES/[90c,100c) | 1376 | 724 | 52.6% | 7.8 | 97.1% | 100.0% | 2.05 | 1.08 | 0.96 | 262 |
| NO/[0c,10c) | 1389 | 1248 | 89.8% | 11.3 | 1.0% | 6.4% | -2.86 | -2.57 | -3.33 | 321 |
| NO/[10c,20c) | 732 | 713 | 97.4% | 11.2 | 10.1% | 100.0% | -4.14 | -4.03 | -4.36 | 303 |
| NO/[20c,30c) | 678 | 639 | 94.2% | 7.9 | 22.4% | 100.0% | -2.03 | -1.92 | -0.79 | 322 |
| NO/[30c,40c) | 773 | 723 | 93.5% | 8.0 | 32.5% | 100.0% | -1.91 | -1.79 | -0.73 | 347 |
| NO/[40c,50c) | 876 | 797 | 91.0% | 8.0 | 45.0% | 100.0% | 0.42 | 0.39 | 2.12 | 397 |
| NO/[50c,60c) | 850 | 739 | 86.9% | 7.9 | 52.6% | 100.0% | -1.70 | -1.48 | 1.03 | 390 |
| NO/[60c,70c) | 822 | 711 | 86.5% | 7.9 | 60.8% | 100.0% | -3.60 | -3.11 | -1.47 | 361 |
| NO/[70c,80c) | 867 | 741 | 85.5% | 7.8 | 73.0% | 100.0% | -1.52 | -1.30 | -0.74 | 340 |
| NO/[80c,90c) | 895 | 732 | 81.8% | 7.8 | 84.0% | 100.0% | -0.62 | -0.51 | -0.06 | 330 |
| NO/[90c,100c) | 1764 | 980 | 55.6% | 7.9 | 93.0% | 100.0% | -2.23 | -1.24 | -1.37 | 342 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 3044 | 2668 | 87.6% | 7.9 | 39.1% | 97.3% | -1.79 | -1.57 | -1.49 | 757 |
| YES/420-660s | 2938 | 2722 | 92.6% | 7.9 | 42.1% | 98.1% | -3.68 | -3.41 | -3.60 | 752 |
| YES/<180s | 1931 | 1230 | 63.7% | 7.8 | 29.4% | 77.7% | -3.05 | -1.94 | -0.88 | 616 |
| YES/>=660s | 1733 | 1612 | 93.0% | 10.8 | 40.5% | 97.5% | -6.76 | -6.29 | -6.54 | 583 |
| NO/180-420s | 3044 | 2579 | 84.7% | 7.9 | 45.7% | 98.3% | -3.32 | -2.81 | -2.11 | 757 |
| NO/420-660s | 2938 | 2644 | 90.0% | 8.0 | 48.6% | 100.0% | -1.58 | -1.42 | -0.82 | 750 |
| NO/<180s | 1931 | 1228 | 63.6% | 7.8 | 36.2% | 82.4% | -3.83 | -2.43 | -2.05 | 617 |
| NO/>=660s | 1733 | 1572 | 90.7% | 11.0 | 51.0% | 100.0% | 0.63 | 0.57 | 1.33 | 580 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 315 | 271 | 86.0% | 15.7 | 35.4% | 81.8% | -10.48 | -9.01 | -8.91 | 22 |
| YES/2026-06-02 | 1270 | 1097 | 86.4% | 11.0 | 31.8% | 79.8% | -7.69 | -6.65 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1032 | 83.8% | 11.3 | 33.8% | 87.5% | -8.49 | -7.11 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 702 | 83.7% | 7.8 | 35.0% | 88.3% | -4.93 | -4.12 | -3.90 | 73 |
| YES/2026-06-05 | 979 | 861 | 87.9% | 7.6 | 41.2% | 89.8% | 0.35 | 0.31 | 0.50 | 73 |
| YES/2026-06-06 | 1044 | 901 | 86.3% | 7.8 | 39.1% | 92.3% | -5.81 | -5.01 | -4.83 | 76 |
| YES/2026-06-07 | 1231 | 1049 | 85.2% | 7.8 | 49.8% | 86.8% | 4.72 | 4.02 | 3.94 | 95 |
| YES/2026-06-08 | 1128 | 946 | 83.9% | 7.9 | 37.1% | 89.0% | -4.68 | -3.92 | -3.60 | 96 |
| YES/2026-06-09 | 1039 | 891 | 85.8% | 7.9 | 43.4% | 93.2% | -0.23 | -0.20 | 0.36 | 96 |
| YES/2026-06-10 | 569 | 482 | 84.7% | 7.9 | 40.9% | 86.2% | -2.75 | -2.33 | -2.75 | 58 |
| NO/2026-06-01 | 315 | 263 | 83.5% | 15.6 | 51.0% | 94.2% | 3.96 | 3.30 | 4.60 | 22 |
| NO/2026-06-02 | 1270 | 1003 | 79.0% | 11.1 | 52.7% | 95.1% | 1.18 | 0.93 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 999 | 81.1% | 11.0 | 49.0% | 93.6% | 1.35 | 1.10 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 663 | 79.0% | 7.8 | 47.5% | 89.2% | -0.96 | -0.76 | 0.14 | 73 |
| NO/2026-06-05 | 979 | 817 | 83.5% | 7.6 | 44.7% | 94.4% | -5.75 | -4.80 | -4.42 | 73 |
| NO/2026-06-06 | 1044 | 906 | 86.8% | 7.8 | 48.6% | 87.0% | 1.02 | 0.89 | 0.73 | 76 |
| NO/2026-06-07 | 1231 | 1070 | 86.9% | 7.9 | 37.8% | 91.3% | -9.36 | -8.14 | -8.03 | 95 |
| NO/2026-06-08 | 1128 | 938 | 83.2% | 7.9 | 47.0% | 91.6% | -0.76 | -0.63 | -0.21 | 96 |
| NO/2026-06-09 | 1039 | 881 | 84.8% | 7.9 | 42.5% | 88.6% | -4.89 | -4.14 | -4.34 | 96 |
| NO/2026-06-10 | 569 | 483 | 84.9% | 8.1 | 45.1% | 91.9% | -1.18 | -1.00 | -1.20 | 58 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 9646  double fills: 6869 (71.2%) across 765 windows
- mean pair cost: 0.9904  mean locked net per pair: 0.0096  total locked net: 65.602

## Verdict

- sides with POSITIVE conservative maker EV: []
- sides where maker(lower bound) beats taker: []
- The conservative lower bound on maker EV is negative or under-sampled: trade-through fills are adversely selected and the spread saved did not cover the adverse selection measured this way. This does NOT prove maker entries lose (fills are undercounted and the counted ones are the worst subset) — resolving it needs trade prints or sub-second WS book data.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
