"""Per-observation scoring primitives for the discovery engine.

All scores operate on a sequence of per-WINDOW observations (one independent 15m
window = one observation; never per-row, which leaks). The fundamental object the
gauntlet consumes is a per-window NET return series (after real Kalshi fees), from
which Sharpe / PSR / PBO are computed.

Pure stdlib + math (no scipy import at module load — keeps the engine import-light and
dodges the Windows WMI/sklearn import stall documented in the project notes)."""
from __future__ import annotations

import math
from typing import Sequence

EULER_MASCHERONI = 0.5772156649015329


# --------------------------------------------------------------------------- #
# normal cdf / inverse-cdf (local, accurate enough for DSR/PSR)
# --------------------------------------------------------------------------- #
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam), |err| < 1.2e-9 on (0,1)."""
    if not (0.0 < p < 1.0):
        if p <= 0.0:
            return -math.inf
        if p >= 1.0:
            return math.inf
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# --------------------------------------------------------------------------- #
# moments
# --------------------------------------------------------------------------- #
def mean(xs: Sequence[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def stdev(xs: Sequence[float], *, ddof: int = 1) -> float:
    xs = list(xs)
    n = len(xs)
    if n - ddof <= 0:
        return float("nan")
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def skewness(xs: Sequence[float]) -> float:
    """Population skew (Fisher). Returns 0.0 for degenerate variance."""
    xs = list(xs)
    n = len(xs)
    if n < 3:
        return 0.0
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 3 for x in xs) / n


def kurtosis(xs: Sequence[float]) -> float:
    """Non-excess kurtosis (normal == 3.0). Returns 3.0 for degenerate variance."""
    xs = list(xs)
    n = len(xs)
    if n < 4:
        return 3.0
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if s == 0:
        return 3.0
    return sum(((x - m) / s) ** 4 for x in xs) / n


# --------------------------------------------------------------------------- #
# Sharpe (per-observation; annualization left to the caller — for a binary
# prediction market the natural unit is per-window, so Sharpe is unit-free)
# --------------------------------------------------------------------------- #
def sharpe(returns: Sequence[float], *, ddof: int = 1) -> float:
    """Per-observation Sharpe = mean / stdev. NaN if <2 obs or zero variance."""
    returns = list(returns)
    if len(returns) < 2:
        return float("nan")
    sd = stdev(returns, ddof=ddof)
    if not (sd > 0) or sd != sd:
        return float("nan")
    return mean(returns) / sd


def tstat(returns: Sequence[float]) -> float:
    """t-statistic of mean(returns) != 0 = Sharpe * sqrt(n)."""
    returns = list(returns)
    n = len(returns)
    sr = sharpe(returns)
    return sr * math.sqrt(n) if sr == sr else float("nan")


# --------------------------------------------------------------------------- #
# calibration scores (for prediction-quality screening vs the market)
# --------------------------------------------------------------------------- #
def brier(ps: Sequence[float], ys: Sequence[int]) -> float:
    ps, ys = list(ps), list(ys)
    return mean([(p - y) ** 2 for p, y in zip(ps, ys)]) if ps else float("nan")


def brier_skill(ps: Sequence[float], ys: Sequence[int], ps_ref: Sequence[float]) -> float:
    """Brier skill score vs a reference forecast (the MARKET). >0 means better than market."""
    b = brier(ps, ys)
    b_ref = brier(ps_ref, ys)
    return (1.0 - b / b_ref) if (b_ref and b_ref == b_ref and b_ref > 0) else float("nan")


def spearman_ic(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation (information coefficient). NaN if degenerate."""
    xs, ys = list(xs), list(ys)
    n = len(xs)
    if n < 5:
        return float("nan")

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (num / den) if den > 0 else float("nan")
