"""Stage 2 — feature screening (leakage-safe, market-relative).

The decisive screen is predictivity of the MARKET RESIDUAL (y - mkt_p): a feature that
predicts the outcome but not what the market misses is already in the price and useless.
For each feature we report its pooled information coefficient vs the outcome and vs the
residual, plus sign-stability across purged walk-forward folds (a real signal keeps its
sign out-of-sample; an overfit one flips)."""
from __future__ import annotations

from . import cpcv, metrics


def _series(panel, name):
    return [(o.feats.get(name), o.y, o.mkt_p) for o in panel]


def screen_features(panel, feature_names, *, n_splits: int = 5, embargo: int = 1) -> list[dict]:
    n = len(panel)
    folds = list(cpcv.purged_walk_forward(n, n_splits=n_splits, embargo=embargo))
    out = []
    for name in feature_names:
        xs, ys, resid = [], [], []
        for o in panel:
            v = o.feats.get(name)
            if v is None:
                continue
            xs.append(v)
            ys.append(o.y)
            resid.append(o.y - o.mkt_p)
        cov = len(xs) / n if n else 0.0
        if len(xs) < 30:
            continue
        ic_y = metrics.spearman_ic(xs, ys)
        ic_r = metrics.spearman_ic(xs, resid)
        # sign-stability of the residual IC across OOS folds
        signs = []
        for _tr, te in folds:
            fx = [(panel[i].feats.get(name), panel[i].y - panel[i].mkt_p) for i in te]
            fx = [(a, b) for a, b in fx if a is not None]
            if len(fx) >= 15:
                ic = metrics.spearman_ic([a for a, _ in fx], [b for _, b in fx])
                if ic == ic:
                    signs.append(1 if ic > 0 else -1)
        if signs and ic_r == ic_r:
            ref = 1 if ic_r > 0 else -1
            stability = sum(1 for s in signs if s == ref) / len(signs)
        else:
            stability = float("nan")
        out.append({"feature": name, "coverage": cov, "ic_outcome": ic_y,
                    "ic_residual": ic_r, "abs_ic_residual": abs(ic_r) if ic_r == ic_r else 0.0,
                    "oos_sign_stability": stability, "n": len(xs)})
    out.sort(key=lambda d: d["abs_ic_residual"], reverse=True)
    return out
