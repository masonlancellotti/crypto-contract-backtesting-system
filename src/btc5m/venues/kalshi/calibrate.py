"""Probability calibration (dependency-free).

Maps raw model probabilities to calibrated probabilities using a calibrator fit on
HELD-OUT validation windows (never the rows used to fit the model). Methods:
- ``identity``  — no calibration (uncalibrated baseline / reliability report).
- ``platt``     — 1-feature logistic (sigmoid) calibration (pure-Python LR).
- ``isotonic``  — monotone PAV isotonic regression (pure-Python).

No sklearn/numpy required. Calibrators trained below the gate or in diagnostic
mode are stamped NON_TRADABLE_DIAGNOSTIC_ONLY; a model is only usable by the
paper/live policy when it is gated, TRADABLE, AND has a valid calibrator — so
nothing here can unlock PAPER_CANDIDATE.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ...models import pure_ml
from .model_artifacts import (
    NON_TRADABLE, TRADABLE, _git_info, models_dir, staged_models_dir, tradable_status_for,
)


def isotonic_fit(x: list[float], y: list[float]) -> list[tuple]:
    """Pool-adjacent-violators isotonic regression. Returns ascending (xmax, value)."""
    pts = sorted(zip(x, y), key=lambda t: t[0])
    blocks: list[list] = []   # [sum_y, count, xmin, xmax]
    for xi, yi in pts:
        blocks.append([float(yi), 1.0, xi, xi])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) > (blocks[-1][0] / blocks[-1][1]):
            b2 = blocks.pop()
            b1 = blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], b1[2], b2[3]])
    return [(b[3], b[0] / b[1]) for b in blocks]


def isotonic_predict(thresh: list[tuple], p: float) -> float:
    if not thresh:
        return p
    for xmax, val in thresh:
        if p <= xmax:
            return max(0.0, min(1.0, val))
    return max(0.0, min(1.0, thresh[-1][1]))


@dataclass
class Calibrator:
    method: str = "identity"             # identity | platt | isotonic
    params: dict = field(default_factory=dict)

    def transform(self, probs: list[float]) -> list[float]:
        if self.method == "identity" or not self.params:
            return [max(0.0, min(1.0, p)) for p in probs]
        if self.method == "isotonic":
            thresh = [tuple(t) for t in self.params.get("thresh", [])]
            return [isotonic_predict(thresh, p) for p in probs]
        if self.method == "platt":
            w = self.params.get("w", 1.0)
            b = self.params.get("b", 0.0)
            mean = self.params.get("mean", 0.0)
            std = self.params.get("std", 1.0) or 1.0
            return [pure_ml.sigmoid(w * ((p - mean) / std) + b) for p in probs]
        return [max(0.0, min(1.0, p)) for p in probs]

    def to_dict(self) -> dict:
        return {"method": self.method, "params": self.params}

    @classmethod
    def from_dict(cls, d: dict) -> "Calibrator":
        return cls(method=d.get("method", "identity"), params=d.get("params", {}))


def fit_calibrator(method: str, p_cal: list[float], y_cal: list[int]) -> Calibrator:
    """Fit a calibrator on held-out (prob, label) pairs."""
    method = (method or "identity").lower()
    if method == "identity" or not p_cal:
        return Calibrator(method="identity", params={})
    if method == "isotonic":
        thresh = isotonic_fit(p_cal, [float(y) for y in y_cal])
        return Calibrator(method="isotonic", params={"thresh": [list(t) for t in thresh]})
    if method in ("platt", "sigmoid"):
        X = [[p] for p in p_cal]
        imp = pure_ml.StandardImputer().fit(X)
        lr = pure_ml.LogisticRegression(l2=0.0, lr=0.5, epochs=400).fit(imp.transform(X), list(y_cal))
        w = lr.w[0] if lr.w else 0.0
        return Calibrator(method="platt",
                          params={"w": w, "b": lr.b, "mean": imp.means[0], "std": imp.stds[0]})
    return Calibrator(method="identity", params={})


# --------------------------------------------------------------------------- #
# Artifact persistence
# --------------------------------------------------------------------------- #
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def build_calibrator_artifact(*, calibrator: Calibrator, method: str, model_name: str,
                              split_metadata: dict, metrics_before: dict, metrics_after: dict,
                              tradable: bool, gate_windows: int, notes: str = "",
                              is_staged: bool = True, created_by_command: Optional[str] = None,
                              series: Optional[str] = None, dataset_path: Optional[str] = None,
                              calibration_window_count: Optional[int] = None,
                              test_window_count: Optional[int] = None,
                              calibrator_backend: str = "pure_ml") -> dict:
    is_diagnostic = (not tradable)
    return {
        "artifact_type": "calibrator",
        "calibrator": calibrator.to_dict(),
        "calibrator_backend": calibrator_backend,
        "method": method,
        "model_name": model_name,
        "model_type": f"calibrator:{method}",
        "tradability": TRADABLE if tradable else NON_TRADABLE,
        "tradable": bool(tradable),
        "NON_TRADABLE_DIAGNOSTIC_ONLY": is_diagnostic,
        "calibration_status": "calibrated" if tradable else "diagnostic",
        # ----- lifecycle / staging safety (PART L) -----
        "is_diagnostic": is_diagnostic,
        "is_staged": bool(is_staged),
        "is_promoted": False,
        "promotion_required": True,
        "tradable_status": tradable_status_for(is_diagnostic=is_diagnostic, is_staged=is_staged,
                                               is_promoted=False),
        "live_approved": False,
        "created_by_command": created_by_command,
        "series": series,
        "dataset_path": dataset_path,
        "split_metadata": split_metadata,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "gate_windows": gate_windows,
        "calibration_window_count": calibration_window_count,
        "test_window_count": test_window_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        **_git_info(),
        "notes": notes,
    }


def save_calibrator(config, artifact: dict, *, stem: Optional[str] = None,
                    staged: bool = False) -> dict:
    """Persist a calibrator. ``staged=True`` -> data/models/staged/ (runtime-invisible)."""
    d = staged_models_dir(config) if staged else models_dir(config)
    stem = stem or f"kalshi_calibrator_{_ts()}"
    artifact = {**artifact, "is_staged": bool(staged),
                "tradable_status": tradable_status_for(
                    is_diagnostic=bool(artifact.get("is_diagnostic", not artifact.get("tradable"))),
                    is_staged=bool(staged), is_promoted=False)}
    pkl = d / f"{stem}.pkl"
    with pkl.open("wb") as fh:
        pickle.dump(artifact, fh)
    summary = {k: v for k, v in artifact.items()}
    js = d / f"{stem}.json"
    with js.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    return {"calibrator_file": str(pkl), "summary_file": str(js),
            "staged": bool(staged), "tradable_status": artifact["tradable_status"]}


def load_calibrator(path: str) -> dict:
    with open(path, "rb") as fh:
        return pickle.load(fh)


def latest_calibrator_path(config) -> Optional[str]:
    d = config.data_path() / "models"
    if not d.exists():
        return None
    files = sorted(d.glob("kalshi_calibrator_*.pkl"))
    return str(files[-1]) if files else None


def latest_staged_calibrator_path(config) -> Optional[str]:
    """Newest STAGED calibrator (data/models/staged/). For --staged backtests only;
    the runtime never scans this directory."""
    d = config.data_path() / "models" / "staged"
    if not d.exists():
        return None
    files = sorted(d.glob("kalshi_calibrator_*.pkl"))
    return str(files[-1]) if files else None
