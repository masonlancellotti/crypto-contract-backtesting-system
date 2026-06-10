"""Uncertainty estimation for the conservative edge policy (pure stdlib).

Methods (all explicit; the edge policy reports which one produced a buffer):
  1. fixed conservative buffer (early-stage fallback),
  2. calibration-bucket uncertainty (Wilson interval on the realized YES rate),
  3. window bootstrap (optional; resamples DISTINCT windows, never overlapping rows),
  4. model-ensemble disagreement (dispersion across baselines).

Nothing here fabricates precision: low-sample buckets widen or reject, and a
missing interval is reported (not silently ignored).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from ...models import pure_ml


# --------------------------------------------------------------------------- #
# Normal quantile (Acklam) + Wilson interval — stdlib only
# --------------------------------------------------------------------------- #
def z_for_confidence(level: float) -> float:
    """Two-sided z for a confidence ``level`` (e.g. 0.80 -> ~1.2816)."""
    level = min(0.9999, max(0.50, float(level)))
    p = 1.0 - (1.0 - level) / 2.0   # upper tail
    return _norm_ppf(p)


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
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
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def wilson_interval(successes: int, n: int, *, confidence: float = 0.80) -> tuple:
    """Wilson score interval for a binomial proportion. Returns (low, high)."""
    if n <= 0:
        return (0.0, 1.0)
    z = z_for_confidence(confidence)
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z2 / (4 * n)) / n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# --------------------------------------------------------------------------- #
# Calibration-bucket uncertainty
# --------------------------------------------------------------------------- #
@dataclass
class CalibrationBucket:
    lo: float
    hi: float
    count: int
    mean_pred: float
    mean_actual: float
    wilson_low: float
    wilson_high: float

    @property
    def width(self) -> float:
        return self.wilson_high - self.wilson_low


def build_calibration_buckets(y: list, p: list, *, n_buckets: int = 10,
                              confidence: float = 0.80) -> list:
    """Reliability buckets with a Wilson interval on the realized YES rate.

    Reuses :func:`pure_ml.probability_buckets` for counts/means and adds numeric
    bounds + the binomial interval. Buckets are over the HELD-OUT (y, p)."""
    raw = pure_ml.probability_buckets(y, p, n_buckets=n_buckets)
    out = []
    for b in raw:
        # bucket label is "[lo,hi)" — recover numeric bounds from the mean as a fallback
        try:
            lo = float(b["bucket"].strip("[)").split(",")[0])
            hi = float(b["bucket"].strip("[)").split(",")[1])
        except Exception:  # noqa: BLE001
            lo, hi = 0.0, 1.0
        succ = int(round(b["mean_actual"] * b["count"]))
        wl, wh = wilson_interval(succ, b["count"], confidence=confidence)
        out.append(CalibrationBucket(lo=lo, hi=hi, count=b["count"], mean_pred=b["mean_pred"],
                                     mean_actual=b["mean_actual"], wilson_low=wl, wilson_high=wh))
    return out


def build_window_calibration_buckets(y: list, p: list, tickers: list, *, n_buckets: int = 10,
                                     confidence: float = 0.80) -> list:
    """Reliability buckets whose Wilson interval is over DISTINCT 15-minute WINDOWS, not rows.

    Rows inside one window are not independent, so row-based Wilson intervals are fake-tight.
    Here ``count`` = distinct windows in the bucket, ``mean_actual`` = the window YES rate, and
    the Wilson interval uses the window count (much smaller than the row count) → the interval is
    WIDER and the resulting downside buffer is never looser, only equal-or-MORE conservative.
    ``mean_pred`` stays the row-weighted predicted probability. Returns the same
    :class:`CalibrationBucket` type as :func:`build_calibration_buckets`, so the edge policy can
    consume it unchanged (report-only in this build; production stays row-based)."""
    by_bucket: dict = {}
    for i in range(len(p)):
        pi, yi = p[i], y[i]
        tk = tickers[i] if i < len(tickers) else None
        if pi is None or yi is None:
            continue
        b = min(n_buckets - 1, max(0, int(float(pi) * n_buckets)))
        d = by_bucket.setdefault(b, {"p_sum": 0.0, "row_n": 0, "win_label": {}})
        d["p_sum"] += float(pi)
        d["row_n"] += 1
        d["win_label"][tk] = int(yi)          # a window's label is constant; any row sets it
    out = []
    for b in sorted(by_bucket):
        d = by_bucket[b]
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        win_n = len(d["win_label"])
        yes_win = sum(1 for t in d["win_label"] if d["win_label"][t] == 1)
        mean_pred = (d["p_sum"] / d["row_n"]) if d["row_n"] else 0.0
        win_rate = (yes_win / win_n) if win_n else 0.0
        wl, wh = wilson_interval(yes_win, win_n, confidence=confidence)
        out.append(CalibrationBucket(lo=lo, hi=hi, count=win_n, mean_pred=mean_pred,
                                     mean_actual=win_rate, wilson_low=wl, wilson_high=wh))
    return out


def lookup_bucket(buckets: list, p: float) -> Optional[CalibrationBucket]:
    for b in buckets:
        if b.lo <= p < b.hi or (p >= b.hi and b.hi >= 1.0):
            return b
    return None


@dataclass
class CalibrationUncertainty:
    available: bool
    buffer: float = 0.0                # downside buffer (decimal), >= 0
    bucket_n: Optional[int] = None
    bucket_realized_rate: Optional[float] = None
    interval_low: Optional[float] = None
    interval_high: Optional[float] = None
    interval_width: Optional[float] = None
    reason: Optional[str] = None       # CALIBRATION_BUCKET_TOO_SMALL / _WIDE / OK / MISSING


def calibration_uncertainty(p_hat: float, side: str, buckets: list, *,
                            min_bucket_n: int = 30, max_width: float = 0.12,
                            confidence: float = 0.80) -> CalibrationUncertainty:
    """Downside calibration buffer for ``side`` at predicted prob ``p_hat``.

    For YES we fear realized-YES < predicted: buffer = mean_pred - wilson_low.
    For NO  we fear realized-YES > predicted: buffer = wilson_high - mean_pred.
    Low-sample or too-wide buckets are reported (caller may reject)."""
    b = lookup_bucket(buckets, p_hat)
    if b is None:
        return CalibrationUncertainty(False, reason="CALIBRATION_BUCKET_MISSING")
    if b.count < min_bucket_n:
        return CalibrationUncertainty(False, bucket_n=b.count, bucket_realized_rate=b.mean_actual,
                                      interval_low=b.wilson_low, interval_high=b.wilson_high,
                                      interval_width=b.width, reason="CALIBRATION_BUCKET_TOO_SMALL")
    if b.width > max_width:
        return CalibrationUncertainty(False, bucket_n=b.count, bucket_realized_rate=b.mean_actual,
                                      interval_low=b.wilson_low, interval_high=b.wilson_high,
                                      interval_width=b.width, reason="CALIBRATION_INTERVAL_TOO_WIDE")
    buf = max(0.0, b.mean_pred - b.wilson_low) if side == "YES" else max(0.0, b.wilson_high - b.mean_pred)
    return CalibrationUncertainty(True, buffer=buf, bucket_n=b.count, bucket_realized_rate=b.mean_actual,
                                  interval_low=b.wilson_low, interval_high=b.wilson_high,
                                  interval_width=b.width, reason="OK")


# --------------------------------------------------------------------------- #
# Ensemble disagreement
# --------------------------------------------------------------------------- #
@dataclass
class EnsembleDisagreement:
    available: bool
    probabilities: dict = field(default_factory=dict)
    mean: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    dispersion: Optional[float] = None      # population stdev
    buffer: float = 0.0                       # = dispersion (decimal)


def ensemble_disagreement(probs: dict) -> EnsembleDisagreement:
    vals = [v for v in (probs or {}).values() if isinstance(v, (int, float))]
    if len(vals) < 2:
        return EnsembleDisagreement(False, probabilities=dict(probs or {}))
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    sd = math.sqrt(var)
    return EnsembleDisagreement(True, probabilities=dict(probs), mean=mean, minimum=min(vals),
                                maximum=max(vals), dispersion=sd, buffer=sd)


# --------------------------------------------------------------------------- #
# Window bootstrap (optional; resamples DISTINCT windows, never overlapping rows)
# --------------------------------------------------------------------------- #
def window_bootstrap_edge(per_window_edges: dict, *, samples: int = 500,
                          confidence: float = 0.80, seed: int = 0) -> Optional[dict]:
    """Bootstrap the mean per-window edge by resampling WINDOWS (not rows).

    ``per_window_edges`` maps window_id -> representative edge (decimal). Returns
    lower/upper bounds on the mean edge, or None if too few windows."""
    keys = list(per_window_edges.keys())
    if len(keys) < 5:
        return None
    import random
    rng = random.Random(seed)
    means = []
    n = len(keys)
    for _ in range(max(50, int(samples))):
        s = [per_window_edges[keys[rng.randrange(n)]] for _ in range(n)]
        means.append(sum(s) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = means[int(alpha * len(means))]
    hi = means[min(len(means) - 1, int((1 - alpha) * len(means)))]
    return {"low": lo, "high": hi, "mean": sum(means) / len(means),
            "distinct_windows": n, "method": "window_bootstrap"}
