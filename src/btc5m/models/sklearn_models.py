"""Serious sklearn-backed training (OPTIONAL; degrades to pure_ml when absent).

Provides sklearn ``Pipeline`` builders (median imputation + standardization +
estimator) and a LightGBM challenger. Used by the Kalshi trainers when the serious
stack (numpy + pandas + scikit-learn) is installed; otherwise the callers fall back
to ``models.pure_ml`` and stamp results DIAGNOSTIC-ONLY. Missing values arrive as
``None`` from :func:`feature_schema.feature_vector` and are converted to ``np.nan``
for the imputer. ``predict_proba`` is clipped to [0, 1].

These pipelines are picklable, so a fitted pipeline is stored on the model artifact
(``artifact["sklearn_pipeline"]``) and reloaded by the executable backtest. Training
never trades, never promotes, and never enables live.
"""

from __future__ import annotations

from typing import Optional

try:
    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except Exception:  # noqa: BLE001
    SKLEARN_AVAILABLE = False

try:
    from lightgbm import LGBMClassifier

    LIGHTGBM_AVAILABLE = True
except Exception:  # noqa: BLE001
    LIGHTGBM_AVAILABLE = False


def serious_backend_available() -> bool:
    return SKLEARN_AVAILABLE


def _to_array(X: list[list[Optional[float]]]):
    """Convert a list-of-rows with None -> a float ndarray with np.nan for missing."""
    return np.array(
        [[(np.nan if v is None else float(v)) for v in row] for row in X],
        dtype=float,
    )


def build_logistic_pipeline(*, C: float = 1.0, max_iter: int = 1000) -> "Pipeline":
    """Median-impute + standardize + L2 logistic regression (probability output).

    ``keep_empty_features=True`` keeps all-missing columns (filled with 0) so the
    fitted feature width always matches ``feature_names`` (stable, warning-free)."""
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(C=C, max_iter=max_iter, solver="lbfgs")),
    ])


def build_lightgbm_pipeline(**kwargs) -> "Pipeline":
    """Median-impute + LightGBM classifier (trees: no scaling needed). Conservative."""
    params = dict(n_estimators=200, num_leaves=31, max_depth=-1, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                  min_child_samples=30, verbose=-1)
    params.update(kwargs)
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("clf", LGBMClassifier(**params)),
    ])


def fit_pipeline(kind: str, X: list[list[Optional[float]]], y: list[int]) -> "Pipeline":
    """Fit a sklearn pipeline. ``kind`` in {logistic, lightgbm}. Raises on single-class y."""
    arr = _to_array(X)
    yv = np.array([int(t) for t in y])
    if len(set(yv.tolist())) < 2:
        raise ValueError("training labels contain a single class; cannot fit a classifier")
    pipe = build_lightgbm_pipeline() if kind == "lightgbm" else build_logistic_pipeline()
    pipe.fit(arr, yv)
    return pipe


def predict_proba_pipeline(pipe: "Pipeline", X: list[list[Optional[float]]]) -> list[float]:
    """Predict calibrated-to-[0,1] P(YES) for each row (positive class = 1)."""
    if not X:
        return []
    import warnings
    arr = _to_array(X)
    with warnings.catch_warnings():
        # numpy arrays carry no feature names; the estimator was fit on the same
        # nameless arrays, so the sklearn/LightGBM "valid feature names" UserWarning
        # is cosmetic and safe to silence here.
        warnings.filterwarnings("ignore", message=".*feature names.*")
        proba = pipe.predict_proba(arr)
    # positive-class column (label 1)
    classes = list(getattr(pipe.named_steps["clf"], "classes_", [0, 1]))
    pos = classes.index(1) if 1 in classes else (proba.shape[1] - 1)
    return [float(max(0.0, min(1.0, row[pos]))) for row in proba]
