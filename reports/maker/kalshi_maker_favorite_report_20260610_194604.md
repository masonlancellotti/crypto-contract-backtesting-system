# Kalshi deep-favorite maker validation — KXBTC15M

> READ-ONLY. Join-bid quotes in the favorite buckets only, REAL trade-print fills (through = certain, front = front-of-queue optimistic; truth between). Maker fee 0.00 (ASSUMED) vs 0.07 STRESS. Forward sample = windows on/after **20260610** (UTC). Never recommends paper/live; no orders.

- windows in scope: 788 (before/after end-date filter: 788/788)  forward boundary: 20260610  end: none

## YES/[80c,90c) — **verdict: needs_more_forward_data**

- forward sample too small (fills=54, days=1, windows=25)
- risk (through, fee 0): full max_dd=-8.34 streak=7; forward max_dd=-7.61 streak=7

## YES/[80c,90c) cohorts (model|sample|maker-fee)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| prints-through|full|fee0.00 | 746 | 645 | 86.5% | 3.8 | 85.1% | 100.0% | 0.38 | 0.33 | 0.12 | 286 |
| prints-through|full|fee0.07 | 746 | 645 | 86.5% | 3.8 | 85.1% | 100.0% | -0.89 | -0.77 | 0.12 | 286 |
| prints-through|forward|fee0.00 | 60 | 54 | 90.0% | 4.1 | 81.5% | 100.0% | -3.65 | -3.28 | -3.95 | 25 |
| prints-through|forward|fee0.07 | 60 | 54 | 90.0% | 4.1 | 81.5% | 100.0% | -4.85 | -4.37 | -3.95 | 25 |
| prints-front|full|fee0.00 | 746 | 721 | 96.6% | 0.3 | 86.7% | 100.0% | 1.97 | 1.90 | 0.12 | 310 |
| prints-front|full|fee0.07 | 746 | 721 | 96.6% | 0.3 | 86.7% | 100.0% | 0.69 | 0.67 | 0.12 | 310 |
| prints-front|forward|fee0.00 | 60 | 58 | 96.7% | 0.2 | 82.8% | 100.0% | -2.16 | -2.08 | -3.95 | 28 |
| prints-front|forward|fee0.07 | 60 | 58 | 96.7% | 0.2 | 82.8% | 100.0% | -3.40 | -3.28 | -3.95 | 28 |

## YES/[80c,90c) by UTC day (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-01 | 19 | 14 | 73.7% | 7.9 | 64.3% | 100.0% | -19.43 | -14.32 | -12.84 | 9 |
| 2026-06-02 | 70 | 62 | 88.6% | 3.7 | 88.7% | 100.0% | 3.65 | 3.23 | 2.65 | 30 |
| 2026-06-03 | 87 | 73 | 83.9% | 2.7 | 76.7% | 100.0% | -7.93 | -6.66 | -6.33 | 27 |
| 2026-06-04 | 62 | 48 | 77.4% | 3.2 | 85.4% | 100.0% | 0.98 | 0.76 | 1.65 | 24 |
| 2026-06-05 | 68 | 61 | 89.7% | 1.9 | 93.4% | 100.0% | 8.61 | 7.72 | 7.10 | 26 |
| 2026-06-06 | 92 | 79 | 85.9% | 3.4 | 81.0% | 100.0% | -3.63 | -3.12 | -3.08 | 34 |
| 2026-06-07 | 99 | 89 | 89.9% | 3.8 | 86.5% | 100.0% | 2.11 | 1.90 | 0.98 | 41 |
| 2026-06-08 | 88 | 75 | 85.2% | 7.0 | 94.7% | 100.0% | 9.83 | 8.38 | 8.37 | 33 |
| 2026-06-09 | 101 | 90 | 89.1% | 3.6 | 83.3% | 100.0% | -1.60 | -1.43 | -2.00 | 37 |
| 2026-06-10 | 60 | 54 | 90.0% | 4.1 | 81.5% | 100.0% | -3.65 | -3.28 | -3.95 | 25 |

## YES/[80c,90c) by seconds-to-close (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 180-420s | 264 | 222 | 84.1% | 3.1 | 86.5% | 100.0% | 1.26 | 1.06 | 1.17 | 154 |
| 420-660s | 322 | 286 | 88.8% | 5.3 | 87.1% | 100.0% | 2.70 | 2.39 | 1.82 | 166 |
| <180s | 100 | 85 | 85.0% | 1.3 | 81.2% | 100.0% | -3.88 | -3.30 | -3.25 | 70 |
| >=660s | 60 | 52 | 86.7% | 4.1 | 75.0% | 100.0% | -9.17 | -7.95 | -8.05 | 39 |

## YES/[90c,100c) — **verdict: needs_more_forward_data**

- forward sample too small (fills=62, days=1, windows=24)
- risk (through, fee 0): full max_dd=-3.739 streak=3; forward max_dd=-0.92 streak=1

## YES/[90c,100c) cohorts (model|sample|maker-fee)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| prints-through|full|fee0.00 | 1400 | 763 | 54.5% | 5.5 | 97.2% | 100.0% | 2.32 | 1.26 | 0.99 | 275 |
| prints-through|full|fee0.07 | 1400 | 763 | 54.5% | 5.5 | 97.2% | 100.0% | 1.32 | 0.72 | 0.99 | 275 |
| prints-through|forward|fee0.00 | 119 | 62 | 52.1% | 4.2 | 98.4% | 100.0% | 3.39 | 1.77 | 1.53 | 24 |
| prints-through|forward|fee0.07 | 119 | 62 | 52.1% | 4.2 | 98.4% | 100.0% | 2.39 | 1.24 | 1.53 | 24 |
| prints-front|full|fee0.00 | 1400 | 1289 | 92.1% | 0.6 | 98.4% | 100.0% | 2.20 | 2.02 | 0.99 | 325 |
| prints-front|full|fee0.07 | 1400 | 1289 | 92.1% | 0.6 | 98.4% | 100.0% | 1.20 | 1.10 | 0.99 | 325 |
| prints-front|forward|fee0.00 | 119 | 109 | 91.6% | 0.4 | 99.1% | 100.0% | 2.82 | 2.58 | 1.53 | 30 |
| prints-front|forward|fee0.07 | 119 | 109 | 91.6% | 0.4 | 99.1% | 100.0% | 1.82 | 1.66 | 1.53 | 30 |

## YES/[90c,100c) by UTC day (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-01 | 34 | 21 | 61.8% | 13.9 | 100.0% | 100.0% | 4.78 | 2.95 | 2.21 | 6 |
| 2026-06-02 | 156 | 84 | 53.8% | 6.1 | 100.0% | 100.0% | 5.28 | 2.85 | 2.71 | 28 |
| 2026-06-03 | 168 | 90 | 53.6% | 5.2 | 95.6% | 100.0% | 0.10 | 0.05 | -0.12 | 31 |
| 2026-06-04 | 143 | 63 | 44.1% | 4.6 | 95.2% | 100.0% | 0.40 | 0.17 | 0.13 | 27 |
| 2026-06-05 | 126 | 73 | 57.9% | 5.1 | 100.0% | 100.0% | 5.13 | 2.97 | 2.88 | 23 |
| 2026-06-06 | 130 | 70 | 53.8% | 6.5 | 92.9% | 100.0% | -1.98 | -1.07 | -1.51 | 28 |
| 2026-06-07 | 201 | 119 | 59.2% | 6.4 | 98.3% | 100.0% | 3.76 | 2.23 | 1.91 | 40 |
| 2026-06-08 | 188 | 102 | 54.3% | 5.5 | 97.1% | 100.0% | 1.77 | 0.96 | 0.62 | 38 |
| 2026-06-09 | 135 | 79 | 58.5% | 5.8 | 96.2% | 100.0% | 1.48 | 0.87 | 0.30 | 30 |
| 2026-06-10 | 119 | 62 | 52.1% | 4.2 | 98.4% | 100.0% | 3.39 | 1.77 | 1.53 | 24 |

## YES/[90c,100c) by seconds-to-close (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 180-420s | 579 | 386 | 66.7% | 6.4 | 98.7% | 100.0% | 3.91 | 2.61 | 2.46 | 199 |
| 420-660s | 163 | 143 | 87.7% | 4.9 | 97.2% | 100.0% | 3.92 | 3.44 | 2.91 | 81 |
| <180s | 652 | 229 | 35.1% | 4.7 | 94.8% | 100.0% | -1.51 | -0.53 | -0.86 | 159 |
| >=660s | 6 | 5 | 83.3% | 89.4 | 100.0% | 100.0% | 8.62 | 7.18 | 7.57 | 5 |

## NO/[80c,90c) — **verdict: needs_more_forward_data**

- forward sample too small (fills=68, days=1, windows=30)
- risk (through, fee 0): full max_dd=-19.29 streak=9; forward max_dd=-5.88 streak=3

## NO/[80c,90c) cohorts (model|sample|maker-fee)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| prints-through|full|fee0.00 | 921 | 816 | 88.6% | 3.3 | 85.2% | 100.0% | 0.47 | 0.42 | -0.13 | 361 |
| prints-through|full|fee0.07 | 921 | 816 | 88.6% | 3.3 | 85.2% | 100.0% | -0.80 | -0.71 | -0.13 | 361 |
| prints-through|forward|fee0.00 | 73 | 68 | 93.2% | 4.3 | 83.8% | 100.0% | -1.10 | -1.03 | -2.31 | 30 |
| prints-through|forward|fee0.07 | 73 | 68 | 93.2% | 4.3 | 83.8% | 100.0% | -2.37 | -2.21 | -2.31 | 30 |
| prints-front|full|fee0.00 | 921 | 897 | 97.4% | 0.3 | 86.5% | 100.0% | 1.77 | 1.73 | -0.13 | 384 |
| prints-front|full|fee0.07 | 921 | 897 | 97.4% | 0.3 | 86.5% | 100.0% | 0.51 | 0.49 | -0.13 | 384 |
| prints-front|forward|fee0.00 | 73 | 73 | 100.0% | 0.3 | 84.9% | None | -0.01 | -0.01 | -2.31 | 31 |
| prints-front|forward|fee0.07 | 73 | 73 | 100.0% | 0.3 | 84.9% | None | -1.27 | -1.27 | -2.31 | 31 |

## NO/[80c,90c) by UTC day (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-01 | 26 | 24 | 92.3% | 6.3 | 91.7% | 100.0% | 7.50 | 6.92 | 5.69 | 10 |
| 2026-06-02 | 121 | 102 | 84.3% | 3.5 | 92.2% | 100.0% | 7.86 | 6.63 | 6.62 | 46 |
| 2026-06-03 | 104 | 89 | 85.6% | 2.9 | 92.1% | 100.0% | 7.48 | 6.40 | 6.31 | 42 |
| 2026-06-04 | 66 | 50 | 75.8% | 2.1 | 90.0% | 100.0% | 4.86 | 3.68 | 5.08 | 34 |
| 2026-06-05 | 99 | 86 | 86.9% | 2.7 | 75.6% | 100.0% | -8.55 | -7.42 | -7.83 | 39 |
| 2026-06-06 | 97 | 87 | 89.7% | 3.4 | 86.2% | 100.0% | 1.62 | 1.45 | 0.88 | 35 |
| 2026-06-07 | 119 | 109 | 91.6% | 2.7 | 75.2% | 100.0% | -9.75 | -8.93 | -9.84 | 41 |
| 2026-06-08 | 116 | 108 | 93.1% | 4.1 | 95.4% | 100.0% | 10.31 | 9.60 | 8.50 | 43 |
| 2026-06-09 | 100 | 93 | 93.0% | 2.8 | 75.3% | 100.0% | -9.54 | -8.87 | -10.17 | 41 |
| 2026-06-10 | 73 | 68 | 93.2% | 4.3 | 83.8% | 100.0% | -1.10 | -1.03 | -2.31 | 30 |

## NO/[80c,90c) by seconds-to-close (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 180-420s | 356 | 312 | 87.6% | 2.7 | 85.6% | 100.0% | 0.32 | 0.28 | -0.16 | 211 |
| 420-660s | 378 | 334 | 88.4% | 4.7 | 86.5% | 100.0% | 2.22 | 1.96 | 1.48 | 202 |
| <180s | 97 | 88 | 90.7% | 1.1 | 75.0% | 100.0% | -10.09 | -9.15 | -10.08 | 75 |
| >=660s | 90 | 82 | 91.1% | 3.4 | 89.0% | 100.0% | 5.29 | 4.82 | 3.94 | 58 |

## NO/[90c,100c) — **verdict: dead**

- historical not positive at the conservative bound (through=-1.889071566731141, front=-0.33632530120481874)
- risk (through, fee 0): full max_dd=-23.446 streak=6; forward max_dd=-4.468 streak=4

## NO/[90c,100c) cohorts (model|sample|maker-fee)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| prints-through|full|fee0.00 | 1801 | 1034 | 57.4% | 6.9 | 93.1% | 100.0% | -1.89 | -1.08 | -1.39 | 366 |
| prints-through|full|fee0.07 | 1801 | 1034 | 57.4% | 6.9 | 93.1% | 100.0% | -2.89 | -1.66 | -1.39 | 366 |
| prints-through|forward|fee0.00 | 145 | 95 | 65.5% | 5.4 | 93.7% | 100.0% | -1.50 | -0.99 | -1.68 | 33 |
| prints-through|forward|fee0.07 | 145 | 95 | 65.5% | 5.4 | 93.7% | 100.0% | -2.50 | -1.64 | -1.68 | 33 |
| prints-front|full|fee0.00 | 1801 | 1660 | 92.2% | 0.6 | 95.7% | 100.0% | -0.34 | -0.31 | -1.39 | 404 |
| prints-front|full|fee0.07 | 1801 | 1660 | 92.2% | 0.6 | 95.7% | 100.0% | -1.34 | -1.23 | -1.39 | 404 |
| prints-front|forward|fee0.00 | 145 | 140 | 96.6% | 0.5 | 95.7% | 100.0% | -0.42 | -0.41 | -1.68 | 36 |
| prints-front|forward|fee0.07 | 145 | 140 | 96.6% | 0.5 | 95.7% | 100.0% | -1.42 | -1.37 | -1.68 | 36 |

## NO/[90c,100c) by UTC day (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-01 | 45 | 20 | 44.4% | 7.4 | 85.0% | 100.0% | -10.39 | -4.62 | -4.08 | 11 |
| 2026-06-02 | 270 | 153 | 56.7% | 8.0 | 97.4% | 100.0% | 2.28 | 1.29 | 0.98 | 52 |
| 2026-06-03 | 219 | 119 | 54.3% | 7.3 | 91.6% | 100.0% | -3.23 | -1.76 | -2.00 | 45 |
| 2026-06-04 | 216 | 125 | 57.9% | 11.1 | 92.8% | 100.0% | -2.96 | -1.71 | -2.04 | 40 |
| 2026-06-05 | 193 | 105 | 54.4% | 9.1 | 88.6% | 100.0% | -6.40 | -3.48 | -3.77 | 37 |
| 2026-06-06 | 134 | 83 | 61.9% | 4.5 | 98.8% | 100.0% | 3.70 | 2.29 | 1.73 | 30 |
| 2026-06-07 | 185 | 118 | 63.8% | 7.8 | 87.3% | 100.0% | -7.96 | -5.08 | -5.31 | 40 |
| 2026-06-08 | 211 | 113 | 53.6% | 3.8 | 97.3% | 100.0% | 2.87 | 1.54 | 1.28 | 42 |
| 2026-06-09 | 183 | 103 | 56.3% | 7.5 | 92.2% | 100.0% | -2.10 | -1.18 | -1.40 | 36 |
| 2026-06-10 | 145 | 95 | 65.5% | 5.4 | 93.7% | 100.0% | -1.50 | -0.99 | -1.68 | 33 |

## NO/[90c,100c) by seconds-to-close (through, fee 0, full)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| 180-420s | 769 | 532 | 69.2% | 7.3 | 93.0% | 100.0% | -1.78 | -1.23 | -1.46 | 265 |
| 420-660s | 207 | 171 | 82.6% | 8.4 | 92.4% | 100.0% | -0.73 | -0.60 | -0.83 | 91 |
| <180s | 814 | 322 | 39.6% | 5.7 | 93.5% | 100.0% | -2.98 | -1.18 | -1.58 | 222 |
| >=660s | 11 | 9 | 81.8% | 33.7 | 100.0% | 100.0% | 8.36 | 6.84 | 6.91 | 8 |

## Safety
- READ-ONLY validation; no orders, no paper, no promotion, no threshold/buffer changes; live_submission_allowed=false. A `shadow_candidate_later` verdict is NOT a paper/live recommendation — it only flags eligibility for a future, separately-gated shadow review.
