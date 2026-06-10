"""Dependency-free ML primitives (stdlib only).

This project ships with NO numpy/sklearn/pandas (they are optional extras and are
not installed). To train honest baseline probability models *now* without adding
fragile dependencies, this module provides a small, well-tested toolkit:

- :class:`StandardImputer` — mean-impute missing (None) values, then standardize
  (fit on TRAIN only; transform train/val identically). No look-ahead.
- :class:`LogisticRegression` — L2-regularized binary logistic regression via
  full-batch gradient descent; ``predict_proba`` in [0, 1].
- metrics: accuracy, ROC-AUC (rank-based), Brier, log-loss, confusion matrix,
  probability-bucket calibration summary.

If sklearn/numpy are later installed, training can swap to them behind the same
interface; the artifacts stay portable because we persist plain Python floats.
"""

from __future__ import annotations

import math
from typing import Optional


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class StandardImputer:
    """Mean-imputation + standardization. ``fit`` uses only the training matrix."""

    def __init__(self) -> None:
        self.means: list[float] = []
        self.stds: list[float] = []
        self.n_features: int = 0

    def fit(self, X: list[list[Optional[float]]]) -> "StandardImputer":
        if not X:
            self.means, self.stds, self.n_features = [], [], 0
            return self
        self.n_features = len(X[0])
        self.means, self.stds = [], []
        for j in range(self.n_features):
            col = [row[j] for row in X if row[j] is not None]
            mean = (sum(col) / len(col)) if col else 0.0
            if len(col) > 1:
                var = sum((v - mean) ** 2 for v in col) / (len(col) - 1)
                std = math.sqrt(var) if var > 0 else 1.0
            else:
                std = 1.0
            self.means.append(mean)
            self.stds.append(std if std > 0 else 1.0)
        return self

    def transform(self, X: list[list[Optional[float]]]) -> list[list[float]]:
        out: list[list[float]] = []
        for row in X:
            out.append([
                ((row[j] if row[j] is not None else self.means[j]) - self.means[j]) / self.stds[j]
                for j in range(self.n_features)
            ])
        return out

    def to_dict(self) -> dict:
        return {"means": self.means, "stds": self.stds, "n_features": self.n_features}


class LogisticRegression:
    """Binary L2-regularized logistic regression (full-batch gradient descent)."""

    def __init__(self, l2: float = 1.0, lr: float = 0.5, epochs: int = 400, seed: int = 0) -> None:
        self.l2 = l2
        self.lr = lr
        self.epochs = epochs
        self.seed = seed
        self.w: list[float] = []
        self.b: float = 0.0

    def fit(self, X: list[list[float]], y: list[int]) -> "LogisticRegression":
        n = len(X)
        d = len(X[0]) if n else 0
        self.w = [0.0] * d
        self.b = 0.0
        if n == 0 or d == 0:
            return self
        for _ in range(self.epochs):
            gw = [0.0] * d
            gb = 0.0
            for i in range(n):
                xi = X[i]
                z = self.b + sum(self.w[j] * xi[j] for j in range(d))
                err = sigmoid(z) - y[i]
                for j in range(d):
                    gw[j] += err * xi[j]
                gb += err
            for j in range(d):
                self.w[j] -= self.lr * (gw[j] / n + self.l2 * self.w[j] / n)
            self.b -= self.lr * (gb / n)
        return self

    def predict_proba(self, X: list[list[float]]) -> list[float]:
        return [sigmoid(self.b + sum(self.w[j] * row[j] for j in range(len(self.w)))) for row in X]

    def to_dict(self) -> dict:
        return {"w": self.w, "b": self.b, "l2": self.l2, "lr": self.lr, "epochs": self.epochs}

    @classmethod
    def from_dict(cls, d: dict) -> "LogisticRegression":
        m = cls(l2=d.get("l2", 1.0), lr=d.get("lr", 0.5), epochs=d.get("epochs", 400))
        m.w = list(d.get("w", []))
        m.b = float(d.get("b", 0.0))
        return m


# --------------------------------------------------------------------------- #
# Metrics (all diagnostic; never a tradability claim)
# --------------------------------------------------------------------------- #
def _clip(p: float, eps: float = 1e-12) -> float:
    return min(1.0 - eps, max(eps, p))


def accuracy(y: list[int], pred_class: list[int]) -> Optional[float]:
    if not y:
        return None
    return sum(1 for a, b in zip(y, pred_class) if a == b) / len(y)


def roc_auc(y: list[int], p: list[float]) -> Optional[float]:
    """Rank-based ROC-AUC (Mann-Whitney). None if only one class present."""
    pos = [pi for pi, yi in zip(p, y) if yi == 1]
    neg = [pi for pi, yi in zip(p, y) if yi == 0]
    if not pos or not neg:
        return None
    order = sorted(range(len(p)), key=lambda i: p[i])
    ranks = [0.0] * len(p)
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and p[order[j + 1]] == p[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    sum_pos = sum(ranks[i] for i in range(len(p)) if y[i] == 1)
    n_pos, n_neg = len(pos), len(neg)
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def brier(y: list[int], p: list[float]) -> Optional[float]:
    if not y:
        return None
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y)


def log_loss(y: list[int], p: list[float]) -> Optional[float]:
    if not y:
        return None
    return -sum(yi * math.log(_clip(pi)) + (1 - yi) * math.log(1 - _clip(pi))
                for pi, yi in zip(p, y)) / len(y)


def confusion_matrix(y: list[int], pred_class: list[int]) -> dict:
    tp = sum(1 for a, b in zip(y, pred_class) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y, pred_class) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y, pred_class) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y, pred_class) if a == 1 and b == 0)
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def probability_buckets(y: list[int], p: list[float], n_buckets: int = 10) -> list[dict]:
    """Reliability table: predicted-probability bucket vs realized YES rate."""
    out: list[dict] = []
    for b in range(n_buckets):
        lo, hi = b / n_buckets, (b + 1) / n_buckets
        idx = [i for i in range(len(p)) if (p[i] >= lo and (p[i] < hi or (b == n_buckets - 1 and p[i] <= hi)))]
        if not idx:
            continue
        out.append({
            "bucket": f"[{lo:.1f},{hi:.1f})",
            "count": len(idx),
            "mean_pred": sum(p[i] for i in idx) / len(idx),
            "mean_actual": sum(y[i] for i in idx) / len(idx),
        })
    return out


def classify(p: list[float], threshold: float = 0.5) -> list[int]:
    return [1 if pi >= threshold else 0 for pi in p]
