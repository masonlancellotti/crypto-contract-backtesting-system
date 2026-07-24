"""The overfitting / multiple-testing gauntlet — the heart of the engine.

Implements the Bailey & López de Prado machinery that tells you whether a discovered
strategy is real or a selection artifact:

  * Probabilistic Sharpe Ratio (PSR)      — significance of a Sharpe vs a benchmark,
                                             skew/kurtosis-adjusted.
  * Expected maximum Sharpe under N trials — the benchmark a "best of N" must clear.
  * Deflated Sharpe Ratio (DSR)           — PSR against that expected-max benchmark;
                                             DSR > 0.95 == survives multiple testing.
  * Probability of Backtest Overfitting   — CSCV: does the in-sample-best strategy stay
    (PBO)                                   above the OOS median? PBO -> 0 good, -> 0.5 overfit.
  * parameter_plateau                     — is the best parameter a robust plateau or a spike?

References: Bailey & López de Prado, "The Deflated Sharpe Ratio" (2014); "The Probability
of Backtest Overfitting" (2015). No trading; pure measurement."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from . import metrics

GAMMA = metrics.EULER_MASCHERONI
E = math.e


# --------------------------------------------------------------------------- #
# Probabilistic & Deflated Sharpe Ratio
# --------------------------------------------------------------------------- #
def probabilistic_sharpe_ratio(sr: float, n_obs: int, skew: float, kurt: float,
                               sr_benchmark: float = 0.0) -> float:
    """PSR(sr*) = Φ[ ((sr - sr*)·sqrt(n-1)) / sqrt(1 - skew·sr + ((kurt-1)/4)·sr²) ].

    `sr` is the per-observation (non-annualized) Sharpe. `kurt` is non-excess
    (normal == 3). Returns a probability in (0,1): the confidence that the true
    Sharpe exceeds `sr_benchmark`."""
    if n_obs < 2 or sr != sr:
        return float("nan")
    denom_var = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom_var <= 0:
        denom_var = 1e-12
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom_var)
    return metrics.norm_cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max Sharpe] across `n_trials` independent strategies with cross-trial Sharpe
    variance `sr_variance` (Bailey-LdP). The Sharpe a 'best of N' search must beat by
    chance alone. sr_variance is the variance of the trial Sharpes (the selection breadth)."""
    if n_trials < 1 or sr_variance is None or sr_variance < 0:
        return float("nan")
    if n_trials == 1 or sr_variance == 0:
        return 0.0
    sigma = math.sqrt(sr_variance)
    a = metrics.norm_ppf(1.0 - 1.0 / n_trials)
    b = metrics.norm_ppf(1.0 - 1.0 / (n_trials * E))
    return sigma * ((1.0 - GAMMA) * a + GAMMA * b)


def deflated_sharpe_ratio(returns: Sequence[float], *, n_trials: int,
                          sr_variance: Optional[float] = None,
                          trial_sharpes: Optional[Sequence[float]] = None) -> dict:
    """DSR of the SELECTED strategy's `returns`, deflated for `n_trials` searched.

    Provide the selection breadth either as `sr_variance` (variance of all trial
    Sharpes) or `trial_sharpes` (the list, from which variance is computed). DSR > 0.95
    == the Sharpe survives the fact that it is the best of `n_trials`."""
    rs = list(returns)
    sr = metrics.sharpe(rs)
    n = len(rs)
    sk = metrics.skewness(rs)
    ku = metrics.kurtosis(rs)
    if sr_variance is None:
        if trial_sharpes is not None:
            finite = [s for s in trial_sharpes if s == s]
            sr_variance = metrics.stdev(finite) ** 2 if len(finite) >= 2 else 0.0
        else:
            sr_variance = 0.0
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    dsr = probabilistic_sharpe_ratio(sr, n, sk, ku, sr_benchmark=sr0)
    return {"sharpe": sr, "n_obs": n, "skew": sk, "kurtosis": ku,
            "n_trials": n_trials, "sr_variance": sr_variance,
            "expected_max_sharpe": sr0, "deflated_sharpe_ratio": dsr,
            "psr_vs_zero": probabilistic_sharpe_ratio(sr, n, sk, ku, 0.0),
            "significant": (dsr == dsr and dsr > 0.95)}


# --------------------------------------------------------------------------- #
# Probability of Backtest Overfitting (CSCV)
# --------------------------------------------------------------------------- #
@dataclass
class PBOResult:
    pbo: float                       # P(in-sample-best below OOS median)
    n_splits: int
    n_trials: int
    logits: list = field(default_factory=list)
    median_oos_rank: float = float("nan")
    note: str = ""

    def as_dict(self) -> dict:
        return {"pbo": self.pbo, "n_splits": self.n_splits, "n_trials": self.n_trials,
                "median_oos_rank": self.median_oos_rank, "note": self.note}


def _perf(col: np.ndarray) -> float:
    """Per-trial performance over a row subset = Sharpe (mean/std)."""
    if col.size < 2:
        return float("nan")
    sd = col.std(ddof=1)
    if not (sd > 0):
        return col.mean() * 1e6 if col.mean() != 0 else 0.0  # degenerate: rank by mean
    return col.mean() / sd


def pbo_cscv(M, *, n_partitions: int = 10, max_combos: int = 2000) -> PBOResult:
    """Probability of Backtest Overfitting via Combinatorially Symmetric CV.

    `M` is a (T observations × N trials) matrix of per-observation returns. Partition the
    T rows into `n_partitions` (S, even) equal blocks; over all C(S, S/2) ways to pick half
    as IS (complement OOS): take the IS-best trial, find its OOS rank, logit it. PBO =
    fraction of combinations where the IS-best lands below the OOS median (logit < 0)."""
    M = np.asarray(M, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        return PBOResult(float("nan"), 0, 0 if M.ndim != 2 else M.shape[1], note="need >=2 trials")
    T, N = M.shape
    S = n_partitions - (n_partitions % 2)
    if S < 2:
        S = 2
    while S > 2 and T // S < 8:        # require >=~8 obs per block
        S -= 2
    if T // S < 4:
        return PBOResult(float("nan"), 0, N, note=f"too few obs ({T}) for CSCV")
    # contiguous blocks preserve time ordering within IS/OOS
    bounds = [round(i * T / S) for i in range(S + 1)]
    blocks = [list(range(bounds[i], bounds[i + 1])) for i in range(S)]
    half = S // 2
    combos = list(itertools.combinations(range(S), half))
    if len(combos) > max_combos:
        rng = np.random.default_rng(12345)
        idx = rng.choice(len(combos), size=max_combos, replace=False)
        combos = [combos[i] for i in idx]
    logits = []
    oos_ranks = []
    for cis in combos:
        is_rows = [r for b in cis for r in blocks[b]]
        oos_set = set(range(S)) - set(cis)
        oos_rows = [r for b in oos_set for r in blocks[b]]
        is_perf = np.array([_perf(M[is_rows, n]) for n in range(N)])
        oos_perf = np.array([_perf(M[oos_rows, n]) for n in range(N)])
        if np.all(np.isnan(is_perf)):
            continue
        n_star = int(np.nanargmax(is_perf))
        # OOS relative rank of n_star (1=worst..N=best); ties broken by averaging
        order = oos_perf.argsort()       # ascending
        rank = float(np.where(order == n_star)[0][0]) + 1.0
        omega = rank / (N + 1.0)
        omega = min(1 - 1e-9, max(1e-9, omega))
        logits.append(math.log(omega / (1.0 - omega)))
        oos_ranks.append(rank)
    if not logits:
        return PBOResult(float("nan"), 0, N, note="no valid CSCV combinations")
    pbo = sum(1 for lam in logits if lam < 0) / len(logits)
    return PBOResult(pbo=pbo, n_splits=len(logits), n_trials=N, logits=logits,
                     median_oos_rank=float(np.median(oos_ranks)))


# --------------------------------------------------------------------------- #
# parameter robustness
# --------------------------------------------------------------------------- #
def parameter_plateau(param_scores: dict) -> dict:
    """Given {param_value: oos_score}, is the best a robust PLATEAU or a fragile SPIKE?

    plateau_ratio = mean(neighbour scores) / best score (around the argmax, by sorted
    param order). ~1 == plateau (robust); << 1 (or negative) == spike (overfit-prone)."""
    items = sorted(param_scores.items(), key=lambda kv: kv[0])
    if len(items) < 3:
        return {"plateau_ratio": float("nan"), "is_spike": None, "note": "need >=3 params"}
    vals = [v for _, v in items]
    bi = max(range(len(vals)), key=lambda i: vals[i])
    best = vals[bi]
    nbrs = [vals[i] for i in (bi - 1, bi + 1) if 0 <= i < len(vals)]
    if not nbrs or best == 0:
        return {"plateau_ratio": float("nan"), "is_spike": None, "note": "degenerate"}
    ratio = (sum(nbrs) / len(nbrs)) / best
    return {"plateau_ratio": ratio, "best_param": items[bi][0], "best_score": best,
            "is_spike": ratio < 0.5}


# --------------------------------------------------------------------------- #
# combined verdict
# --------------------------------------------------------------------------- #
def verdict(dsr_result: dict, pbo_result: Optional[PBOResult] = None,
            *, plateau: Optional[dict] = None,
            replication_assets: Optional[int] = None,
            replication_required: int = 3) -> dict:
    """Combine the gauntlet outputs into a single PASS/FAIL with reasons. A candidate must
    clear EVERY active gate: DSR>0.95, PBO<0.5, plateau (not a spike), cross-asset
    replication (if provided)."""
    reasons = []
    ok = True
    if not dsr_result.get("significant"):
        ok = False
        reasons.append(f"DSR={dsr_result.get('deflated_sharpe_ratio'):.3f} <= 0.95 "
                       f"(needs to beat E[maxSR]={dsr_result.get('expected_max_sharpe'):.3f})")
    if pbo_result is not None and pbo_result.pbo == pbo_result.pbo:
        if pbo_result.pbo >= 0.5:
            ok = False
            reasons.append(f"PBO={pbo_result.pbo:.2f} >= 0.50 (overfit)")
    if plateau is not None and plateau.get("is_spike"):
        ok = False
        reasons.append(f"parameter SPIKE (plateau_ratio={plateau.get('plateau_ratio'):.2f})")
    if replication_assets is not None and replication_assets < replication_required:
        ok = False
        reasons.append(f"replicates on {replication_assets}/{replication_required}+ assets")
    return {"passed": ok, "reasons": reasons,
            "dsr": dsr_result.get("deflated_sharpe_ratio"),
            "pbo": (pbo_result.pbo if pbo_result else None)}
