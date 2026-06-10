# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-through)

> READ-ONLY research. REAL trade prints, CERTAIN fills only: a resting bid counts as filled when the tape traded strictly THROUGH the level (queue-position-free). Conservative on fill count, but fills/outcomes come from actual flow. No orders, no paper, no promotion; live disabled.

- windows: 786  decision points: 9892  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0155
- maker fee rate: 0.0 (ASSUMED_ZERO_MAKER_FEE); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 9892 | 7537 | 76.2% | 3.0 | 41.8% | 58.6% | -2.80 | -2.14 | -3.15 | 783 |
| YES/join/180 | 9892 | 8198 | 82.9% | 3.6 | 41.5% | 66.6% | -2.77 | -2.30 | -3.15 | 783 |
| YES/join/300 | 9892 | 8343 | 84.3% | 3.8 | 41.4% | 69.4% | -2.83 | -2.39 | -3.15 | 783 |
| YES/join/close | 9892 | 8444 | 85.4% | 3.9 | 41.4% | 71.5% | -2.84 | -2.42 | -3.15 | 783 |
| YES/improve/60 | 836 | 741 | 88.6% | 0.6 | 47.0% | 53.7% | -3.67 | -3.25 | -6.10 | 459 |
| YES/improve/180 | 836 | 777 | 92.9% | 0.6 | 46.7% | 61.0% | -3.79 | -3.53 | -6.10 | 470 |
| YES/improve/300 | 836 | 784 | 93.8% | 0.6 | 46.8% | 61.5% | -3.67 | -3.44 | -6.10 | 472 |
| YES/improve/close | 836 | 793 | 94.9% | 0.7 | 46.5% | 69.8% | -3.86 | -3.66 | -6.10 | 472 |
| NO/join/60 | 9892 | 7359 | 74.4% | 3.0 | 50.2% | 65.9% | -0.38 | -0.28 | -0.86 | 783 |
| NO/join/180 | 9892 | 8021 | 81.1% | 3.6 | 49.8% | 73.0% | -0.43 | -0.35 | -0.86 | 783 |
| NO/join/300 | 9892 | 8185 | 82.7% | 3.8 | 49.8% | 75.3% | -0.43 | -0.36 | -0.86 | 783 |
| NO/join/close | 9892 | 8307 | 84.0% | 4.0 | 49.6% | 78.2% | -0.56 | -0.47 | -0.86 | 783 |
| NO/improve/60 | 836 | 756 | 90.4% | 0.5 | 50.3% | 71.2% | 1.73 | 1.56 | -0.20 | 459 |
| NO/improve/180 | 836 | 784 | 93.8% | 0.6 | 50.4% | 80.8% | 1.76 | 1.65 | -0.20 | 471 |
| NO/improve/300 | 836 | 790 | 94.5% | 0.6 | 50.1% | 89.1% | 1.52 | 1.44 | -0.20 | 471 |
| NO/improve/close | 836 | 798 | 95.5% | 0.6 | 50.0% | 100.0% | 1.43 | 1.36 | -0.20 | 473 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 9892 | 8444 | 85.4% | 3.9 | 41.4% | 71.5% | -4.44 | -3.79 | -3.15 | 783 |
| NO/join/close | 9892 | 8307 | 84.0% | 4.0 | 49.6% | 78.2% | -2.16 | -1.82 | -0.86 | 783 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1815 | 1401 | 77.2% | 8.7 | 4.1% | 3.4% | -0.41 | -0.32 | -1.00 | 399 |
| YES/[10c,20c) | 913 | 898 | 98.4% | 4.6 | 12.0% | 100.0% | -2.24 | -2.20 | -3.19 | 383 |
| YES/[20c,30c) | 898 | 861 | 95.9% | 3.2 | 20.8% | 64.9% | -3.62 | -3.47 | -5.16 | 398 |
| YES/[30c,40c) | 846 | 815 | 96.3% | 2.6 | 31.3% | 100.0% | -3.29 | -3.17 | -3.97 | 408 |
| YES/[40c,50c) | 878 | 841 | 95.8% | 2.8 | 39.2% | 100.0% | -5.24 | -5.02 | -5.92 | 437 |
| YES/[50c,60c) | 916 | 861 | 94.0% | 2.8 | 46.6% | 100.0% | -7.64 | -7.19 | -7.79 | 424 |
| YES/[60c,70c) | 787 | 730 | 92.8% | 2.6 | 59.6% | 100.0% | -5.02 | -4.66 | -5.20 | 354 |
| YES/[70c,80c) | 694 | 629 | 90.6% | 2.9 | 69.8% | 100.0% | -4.70 | -4.26 | -5.00 | 318 |
| YES/[80c,90c) | 746 | 645 | 86.5% | 3.8 | 85.1% | 100.0% | 0.38 | 0.33 | 0.12 | 286 |
| YES/[90c,100c) | 1399 | 763 | 54.5% | 5.5 | 97.2% | 100.0% | 2.32 | 1.26 | 0.98 | 275 |
| NO/[0c,10c) | 1412 | 1060 | 75.1% | 9.1 | 1.4% | 2.0% | -3.18 | -2.39 | -3.35 | 312 |
| NO/[10c,20c) | 743 | 732 | 98.5% | 4.1 | 11.7% | 100.0% | -2.53 | -2.49 | -3.76 | 315 |
| NO/[20c,30c) | 696 | 662 | 95.1% | 3.3 | 24.0% | 100.0% | -0.41 | -0.39 | 0.09 | 334 |
| NO/[30c,40c) | 795 | 763 | 96.0% | 2.7 | 35.1% | 100.0% | 0.71 | 0.68 | 0.14 | 367 |
| NO/[40c,50c) | 908 | 855 | 94.2% | 2.7 | 47.4% | 100.0% | 2.75 | 2.59 | 2.55 | 422 |
| NO/[50c,60c) | 885 | 814 | 92.0% | 3.2 | 55.3% | 100.0% | 0.94 | 0.86 | 1.08 | 421 |
| NO/[60c,70c) | 844 | 767 | 90.9% | 3.3 | 62.7% | 100.0% | -1.63 | -1.48 | -1.40 | 387 |
| NO/[70c,80c) | 889 | 805 | 90.6% | 3.0 | 74.5% | 100.0% | 0.02 | 0.02 | -0.72 | 373 |
| NO/[80c,90c) | 921 | 816 | 88.6% | 3.3 | 85.2% | 100.0% | 0.47 | 0.42 | -0.13 | 361 |
| NO/[90c,100c) | 1799 | 1033 | 57.4% | 6.9 | 93.1% | 100.0% | -1.90 | -1.09 | -1.40 | 365 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 3112 | 2748 | 88.3% | 4.1 | 40.6% | 86.5% | -1.14 | -1.01 | -1.63 | 769 |
| YES/420-660s | 3006 | 2847 | 94.7% | 4.3 | 43.1% | 97.5% | -3.04 | -2.88 | -3.87 | 767 |
| YES/<180s | 1977 | 1135 | 57.4% | 3.2 | 38.8% | 57.5% | -1.62 | -0.93 | -0.91 | 575 |
| YES/>=660s | 1797 | 1714 | 95.4% | 3.2 | 41.5% | 97.6% | -6.04 | -5.77 | -7.04 | 602 |
| NO/180-420s | 3112 | 2675 | 86.0% | 4.4 | 48.4% | 88.3% | -2.05 | -1.77 | -1.98 | 768 |
| NO/420-660s | 3006 | 2789 | 92.8% | 4.2 | 50.4% | 99.5% | -0.25 | -0.24 | -0.56 | 767 |
| NO/<180s | 1977 | 1153 | 58.3% | 3.0 | 45.3% | 64.4% | -2.60 | -1.52 | -2.02 | 567 |
| NO/>=660s | 1797 | 1690 | 94.0% | 3.5 | 53.1% | 100.0% | 2.70 | 2.54 | 1.83 | 600 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 315 | 275 | 87.3% | 6.5 | 38.2% | 67.5% | -9.19 | -8.02 | -8.91 | 23 |
| YES/2026-06-02 | 1270 | 1092 | 86.0% | 3.8 | 34.5% | 61.8% | -6.71 | -5.77 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1049 | 85.1% | 3.9 | 37.7% | 70.5% | -6.97 | -5.94 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 665 | 79.3% | 3.7 | 36.7% | 70.7% | -4.99 | -3.96 | -3.90 | 73 |
| YES/2026-06-05 | 979 | 849 | 86.7% | 3.2 | 43.8% | 68.5% | 1.10 | 0.95 | 0.50 | 73 |
| YES/2026-06-06 | 1044 | 917 | 87.8% | 3.4 | 41.9% | 78.7% | -4.24 | -3.73 | -4.83 | 76 |
| YES/2026-06-07 | 1231 | 1056 | 85.8% | 4.4 | 51.6% | 77.1% | 5.50 | 4.72 | 3.94 | 95 |
| YES/2026-06-08 | 1128 | 947 | 84.0% | 4.2 | 40.2% | 72.9% | -3.50 | -2.94 | -3.60 | 96 |
| YES/2026-06-09 | 1039 | 890 | 85.7% | 3.7 | 46.3% | 75.8% | 0.47 | 0.40 | 0.36 | 95 |
| YES/2026-06-10 | 815 | 704 | 86.4% | 3.9 | 39.9% | 69.4% | -4.91 | -4.24 | -5.62 | 75 |
| NO/2026-06-01 | 315 | 272 | 86.3% | 4.0 | 54.0% | 83.7% | 6.46 | 5.58 | 4.60 | 23 |
| NO/2026-06-02 | 1270 | 1033 | 81.3% | 4.1 | 56.2% | 85.2% | 3.04 | 2.48 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1019 | 82.7% | 4.1 | 53.0% | 78.9% | 3.24 | 2.68 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 652 | 77.7% | 4.7 | 50.3% | 77.0% | 0.08 | 0.07 | 0.14 | 72 |
| NO/2026-06-05 | 979 | 815 | 83.2% | 3.2 | 46.6% | 84.1% | -4.88 | -4.06 | -4.42 | 73 |
| NO/2026-06-06 | 1044 | 915 | 87.6% | 3.6 | 50.9% | 72.9% | 1.73 | 1.51 | 0.73 | 76 |
| NO/2026-06-07 | 1231 | 1066 | 86.6% | 4.7 | 40.3% | 73.3% | -8.59 | -7.44 | -8.03 | 95 |
| NO/2026-06-08 | 1128 | 944 | 83.7% | 3.8 | 50.4% | 75.5% | 0.49 | 0.41 | -0.21 | 96 |
| NO/2026-06-09 | 1039 | 884 | 85.1% | 3.8 | 44.5% | 78.1% | -4.29 | -3.65 | -4.34 | 96 |
| NO/2026-06-10 | 815 | 707 | 86.7% | 3.7 | 53.7% | 71.3% | 2.81 | 2.44 | 1.58 | 75 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 9892  double fills: 7501 (75.8%) across 782 windows
- mean pair cost: 0.9902  mean locked net per pair: 0.0098  total locked net: 73.373
- **FULL both-sides P&L (drift-neutral): -2.89c per quote point** over 9892 points (outcomes: {'double': 7501, 'yes_only': 943, 'none': 642, 'no_only': 806}; total net -286.24); positive days 0/10: {'2026-06-01': -2.441, '2026-06-02': -3.29, '2026-06-03': -3.254, '2026-06-04': -3.892, '2026-06-05': -3.108, '2026-06-06': -2.214, '2026-06-07': -2.723, '2026-06-08': -2.531, '2026-06-09': -3.25, '2026-06-10': -1.8}

## Verdict

- sides with POSITIVE conservative maker EV: []
- sides where maker(lower bound) beats taker: ['YES', 'NO']
- The conservative lower bound on maker EV is negative or under-sampled: trade-through fills are adversely selected and the spread saved did not cover the adverse selection measured this way. This does NOT prove maker entries lose (fills are undercounted and the counted ones are the worst subset) — resolving it needs trade prints or sub-second WS book data.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
