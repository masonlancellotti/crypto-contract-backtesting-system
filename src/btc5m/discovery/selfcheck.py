"""Self-validation of the gauntlet — does the engine reject false positives and accept
true ones? This is milestone-1's deliverable: before we trust ANY discovery, prove the
machinery cannot be fooled by pure selection and is not so strict it rejects real edge.

  negative_control: N pure-noise strategies (true mean 0). The best-in-sample MUST fail the
                    Deflated Sharpe (its luck is exactly what E[maxSR] predicts) and PBO ~ 0.5.
  positive_control: N-1 noise + 1 genuine edge. The true strategy MUST pass DSR and PBO ~ 0.

Run via `kalshi-ade-selfcheck` or the tests in tests/test_discovery_selfcheck.py."""
from __future__ import annotations

import numpy as np

from . import gauntlet, metrics


def _trial_matrix(n_trials: int, n_obs: int, *, true_mu: float = 0.0,
                  true_idx: int | None = None, seed: int = 0) -> np.ndarray:
    """(n_obs x n_trials) per-observation returns; all noise N(0,1) except optionally one
    trial with a genuine mean `true_mu`."""
    rng = np.random.default_rng(seed)
    M = rng.standard_normal((n_obs, n_trials))
    if true_idx is not None:
        M[:, true_idx] += true_mu
    return M


def negative_control(*, n_trials: int = 300, n_obs: int = 500, seed: int = 11) -> dict:
    """Pick the in-sample-best of N noise strategies; the gauntlet must NOT bless it."""
    M = _trial_matrix(n_trials, n_obs, seed=seed)
    sharpes = [metrics.sharpe(M[:, j]) for j in range(n_trials)]
    best = int(np.nanargmax(sharpes))
    dsr = gauntlet.deflated_sharpe_ratio(M[:, best], n_trials=n_trials, trial_sharpes=sharpes)
    pbo = gauntlet.pbo_cscv(M, n_partitions=10)
    return {"kind": "negative_control", "best_trial": best,
            "best_raw_sharpe": sharpes[best], "dsr": dsr, "pbo": pbo.as_dict(),
            "rejected": (not dsr["significant"]) and (pbo.pbo != pbo.pbo or pbo.pbo >= 0.4),
            "expected": "reject (DSR<=0.95 AND PBO~0.5)"}


def positive_control(*, n_trials: int = 300, n_obs: int = 500, true_mu: float = 0.45,
                     seed: int = 23) -> dict:
    """One genuine edge among noise; the gauntlet must bless the true strategy."""
    true_idx = n_trials // 2
    M = _trial_matrix(n_trials, n_obs, true_mu=true_mu, true_idx=true_idx, seed=seed)
    sharpes = [metrics.sharpe(M[:, j]) for j in range(n_trials)]
    dsr = gauntlet.deflated_sharpe_ratio(M[:, true_idx], n_trials=n_trials, trial_sharpes=sharpes)
    pbo = gauntlet.pbo_cscv(M, n_partitions=10)
    is_best = int(np.nanargmax(sharpes)) == true_idx
    return {"kind": "positive_control", "true_idx": true_idx, "true_is_insample_best": is_best,
            "true_raw_sharpe": sharpes[true_idx], "dsr": dsr, "pbo": pbo.as_dict(),
            "accepted": dsr["significant"] and (pbo.pbo == pbo.pbo and pbo.pbo < 0.2),
            "expected": "accept (DSR>0.95 AND PBO~0)"}


def run_selfcheck() -> dict:
    neg = negative_control()
    pos = positive_control()
    ok = neg["rejected"] and pos["accepted"]
    return {"passed": ok, "negative_control": neg, "positive_control": pos}


def format_report(res: dict) -> str:
    n, p = res["negative_control"], res["positive_control"]
    lines = ["=== ADE gauntlet self-validation ===",
             f"OVERALL: {'PASS' if res['passed'] else 'FAIL'}", "",
             "negative control (N noise strategies, pick in-sample best):",
             f"  best raw Sharpe={n['best_raw_sharpe']:.3f}  "
             f"DSR={n['dsr']['deflated_sharpe_ratio']:.3f} (E[maxSR]={n['dsr']['expected_max_sharpe']:.3f})  "
             f"PBO={n['pbo']['pbo']:.2f}",
             f"  -> {'REJECTED (correct)' if n['rejected'] else 'BLESSED A FLUKE (BUG!)'}", "",
             "positive control (1 true edge among noise):",
             f"  true raw Sharpe={p['true_raw_sharpe']:.3f}  is_insample_best={p['true_is_insample_best']}  "
             f"DSR={p['dsr']['deflated_sharpe_ratio']:.3f}  PBO={p['pbo']['pbo']:.2f}",
             f"  -> {'ACCEPTED (correct)' if p['accepted'] else 'REJECTED A REAL EDGE (too strict!)'}"]
    return "\n".join(lines)
