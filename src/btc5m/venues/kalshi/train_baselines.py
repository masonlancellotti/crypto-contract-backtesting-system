"""Kalshi baseline training orchestration (gated; pure-stdlib models).

Builds the model dataset, makes a purged/embargoed chronological split, and fits
honest baselines that estimate P(YES): a no-fit market-implied benchmark, a
distance/time/vol logistic, and a microstructure logistic (pure-Python LR with
mean-imputation + standardization; no numpy/sklearn required). REAL training is
refused below the authoritative window gate unless ``diagnostic_only=True``, and
any artifact produced below the gate / in diagnostic mode is stamped
NON_TRADABLE_DIAGNOSTIC_ONLY. Every model stays UNCALIBRATED → never tradable by
the paper/live policy here. No P&L, no trading, no live orders.
"""

from __future__ import annotations

from ...models import pure_ml, sklearn_models
from .feature_schema import (
    DISTANCE_TIME_VOL_FEATURES, MICROSTRUCTURE_FEATURES, MODEL_SCHEMA_VERSION,
    assert_no_leakage, feature_vector,
)
from .model_artifacts import build_artifact, save_artifact, write_model_card
from .model_dataset import build_model_dataset
from .readiness import MIN_TRAIN_ROWS, MIN_TRAIN_WINDOWS
from .splits import chronological_split, split_indices, walk_forward_splits


def _fit_for_artifact(rows, feature_names, train_idx, eval_idx, *, kind: str = "logistic"):
    """Fit a model to SAVE: sklearn pipeline when available, else pure_ml (diagnostic).

    Returns ``{"metrics", "payload"}`` (payload feeds build_artifact + carries the
    fitted estimator/backend), ``{"error": ...}``, or ``None`` (no train rows).
    Leakage-safe: estimator fit on ``train_idx`` only; eval on ``eval_idx`` (held-out
    val) or train (in-sample diagnostic) when no val windows exist.
    """
    assert_no_leakage(feature_names)
    if not train_idx:
        return None
    use_eval = eval_idx if eval_idx else train_idx
    in_sample = not eval_idx
    ytr = [int(rows[i]["label_yes_resolved"]) for i in train_idx]
    yev = [int(rows[i]["label_yes_resolved"]) for i in use_eval]
    eval_label = "in_sample(train; no validation windows)" if in_sample else "validation"

    if sklearn_models.serious_backend_available():
        Xtr = [feature_vector(rows[i], feature_names) for i in train_idx]
        Xev = [feature_vector(rows[i], feature_names) for i in use_eval]
        try:
            pipe = sklearn_models.fit_pipeline(kind, Xtr, ytr)
            pev = sklearn_models.predict_proba_pipeline(pipe, Xev)
            metrics = _metrics(yev, pev)
            metrics["evaluation"] = eval_label
            metrics["backend"] = "sklearn"
            return {"metrics": metrics, "payload": {
                "model_backend": "sklearn", "sklearn_pipeline": pipe,
                "model_obj_dict": None, "imputer_dict": None,
                "trainer": f"sklearn:{kind}"}}
        except Exception as exc:  # noqa: BLE001 — single-class split / fit error
            if kind == "lightgbm":
                return {"error": f"lightgbm fit failed: {type(exc).__name__}: {exc}"}
            # logistic: fall through to the pure diagnostic path

    if kind == "lightgbm":
        return {"error": "lightgbm requires the serious sklearn stack (not available)"}
    fit = _fit_logistic(rows, feature_names, train_idx, eval_idx)
    if fit is None:
        return None
    metrics = fit["metrics"]
    metrics["backend"] = "pure_ml"
    return {"metrics": metrics, "payload": {
        "model_backend": "pure_ml", "sklearn_pipeline": None,
        "model_obj_dict": fit["model"].to_dict(), "imputer_dict": fit["imputer"].to_dict(),
        "trainer": "pure_ml.LogisticRegression"}}


def _save_model_artifact(config, *, name, feature_names, payload, metrics, split, gate,
                         training_ready, diagnostic_only, tradable_stamp, staged,
                         created_by_command, series, notes):
    """Build + (staged) save a model artifact with full staging/provenance metadata."""
    art = build_artifact(
        model_name=name, model_obj_dict=payload["model_obj_dict"], feature_names=feature_names,
        imputer_dict=payload["imputer_dict"],
        split_metadata={**{k: split.get(k) for k in (
            "train_windows", "val_windows", "embargoed_windows", "train_rows", "val_rows",
            "embargo_windows", "no_leak")},
            "gate_windows": gate["gate_windows"], "training_ready": training_ready},
        training_config={"trainer": payload["trainer"], "backend": payload["model_backend"],
                         "diagnostic_only": diagnostic_only},
        metrics=metrics, tradable=tradable_stamp, model_schema_version=MODEL_SCHEMA_VERSION,
        artifact_type="model", model_type=f"{name}:{payload['model_backend']}", series=series,
        dataset_path="(in-memory build_model_dataset)",
        train_window_count=split.get("train_windows"), test_window_count=split.get("val_windows"),
        is_diagnostic=(not tradable_stamp), is_staged=staged,
        created_by_command=created_by_command, notes=notes)
    art["model_backend"] = payload["model_backend"]
    if payload["model_backend"] == "sklearn":
        art["sklearn_pipeline"] = payload["sklearn_pipeline"]
    paths = save_artifact(config, art, staged=staged)
    card = write_model_card(config, art, stem=f"kalshi_model_card_{name}")
    return {**paths, "model_card": card, "tradability": art["tradability"],
            "backend": payload["model_backend"]}


def _metrics(y: list[int], p: list[float]) -> dict:
    cls = pure_ml.classify(p)
    return {
        "n": len(y),
        "label_balance": {"YES": sum(y), "NO": len(y) - sum(y)},
        "accuracy": pure_ml.accuracy(y, cls),
        "roc_auc": pure_ml.roc_auc(y, p),
        "brier": pure_ml.brier(y, p),
        "log_loss": pure_ml.log_loss(y, p),
        "confusion_matrix": pure_ml.confusion_matrix(y, cls),
        "probability_buckets": pure_ml.probability_buckets(y, p),
        "calibration_status": "uncalibrated",
    }


def fit_predict_logistic(rows, feature_names, train_idx, eval_idx):
    """Fit a pure-Python logistic on ``train_idx``; return (probs_for_eval, model_dict,
    imputer_dict). Leakage-safe: scaler/imputer/model fit on train only."""
    assert_no_leakage(feature_names)
    if not train_idx:
        return [], None, None
    Xtr = [feature_vector(rows[i], feature_names) for i in train_idx]
    ytr = [int(rows[i]["label_yes_resolved"]) for i in train_idx]
    imp = pure_ml.StandardImputer().fit(Xtr)
    model = pure_ml.LogisticRegression(l2=1.0, lr=0.5, epochs=300).fit(imp.transform(Xtr), ytr)
    Xev = [feature_vector(rows[i], feature_names) for i in eval_idx]
    probs = model.predict_proba(imp.transform(Xev)) if eval_idx else []
    return probs, model.to_dict(), imp.to_dict()


def _fit_logistic(rows, feature_names, train_idx, val_idx):
    """Fit a pure-Python logistic on the train split; eval on val (or train)."""
    assert_no_leakage(feature_names)
    if not train_idx:
        return None
    Xtr_raw = [feature_vector(rows[i], feature_names) for i in train_idx]
    ytr = [int(rows[i]["label_yes_resolved"]) for i in train_idx]
    imp = pure_ml.StandardImputer().fit(Xtr_raw)
    Xtr = imp.transform(Xtr_raw)
    model = pure_ml.LogisticRegression(l2=1.0, lr=0.5, epochs=300).fit(Xtr, ytr)

    eval_idx = val_idx if val_idx else train_idx
    in_sample = not val_idx
    Xev_raw = [feature_vector(rows[i], feature_names) for i in eval_idx]
    yev = [int(rows[i]["label_yes_resolved"]) for i in eval_idx]
    pev = model.predict_proba(imp.transform(Xev_raw))
    metrics = _metrics(yev, pev)
    metrics["evaluation"] = "in_sample(train; no validation windows)" if in_sample else "validation"
    return {"model": model, "imputer": imp, "metrics": metrics,
            "feature_names": feature_names}


def _market_implied(rows, idx) -> dict:
    """No-fit benchmark: implied P(YES) from executable asks (normalized)."""
    y, p = [], []
    for i in idx:
        r = rows[i]
        ya, na = r.get("yes_ask"), r.get("no_ask")
        if ya is None:
            continue
        implied = (ya / (ya + na)) if (na is not None and (ya + na) > 0) else ya
        p.append(max(0.0, min(1.0, implied)))
        y.append(int(r["label_yes_resolved"]))
    m = _metrics(y, p) if y else {"n": 0, "note": "no rows with executable asks"}
    m["evaluation"] = "validation" if idx else "none"
    return m


def run_train_baselines(config, *, series: str = "KXBTC15M", diagnostic_only: bool = False,
                        embargo_windows: int = 1, staged: bool = True,
                        created_by_command: str = "kalshi-train-baselines") -> dict:
    """Build dataset, split, and fit the baselines (gated). Returns a report dict.

    Saved model artifacts use the sklearn pipeline when the serious stack is present
    (else pure_ml, stamped diagnostic). ``staged=True`` (default) writes artifacts to
    ``data/models/staged/`` so the runtime cannot auto-select them.
    """
    ds = build_model_dataset(config, series=series, include_deribit="auto")
    rows = ds["rows"]
    gate = ds["gate"]
    training_ready = gate["training_ready"]
    backend = "sklearn" if sklearn_models.serious_backend_available() else "pure_ml (DIAGNOSTIC-ONLY)"

    report = {
        "series": series, "diagnostic_only": diagnostic_only,
        "gate": gate, "n_rows": len(rows), "distinct_windows": ds["distinct_windows"],
        "trained": False, "tradable": False, "artifacts": [], "models": {},
        "blockers": [], "calibration_status": "uncalibrated",
        "training_backend": backend, "staged": bool(staged),
        "status": gate["status"],
    }

    if not training_ready and not diagnostic_only:
        report["blockers"].append(
            f"distinct gate windows={gate['gate_windows']} < train threshold {MIN_TRAIN_WINDOWS} "
            f"and/or rows={len(rows)} < {MIN_TRAIN_ROWS}. Pass --diagnostic-only to fit "
            "NON-TRADABLE toy baselines for sanity checks.")
        report["refused"] = True
        return report

    split = chronological_split(rows, embargo_windows=embargo_windows)
    train_idx, val_idx = split_indices(rows, embargo_windows=embargo_windows)
    report["split"] = split
    report["walk_forward"] = walk_forward_splits(rows, n_splits=3, embargo_windows=embargo_windows)

    tradable_stamp = bool(training_ready and not diagnostic_only)
    notes = ("trained below gate / diagnostic-only" if not tradable_stamp
             else "trained at/above gate (still UNCALIBRATED -> not usable by policy)")

    # Baseline 1: market-implied benchmark (no fit; never tradable).
    mi = _market_implied(rows, val_idx if val_idx else list(range(len(rows))))
    report["models"]["market_implied"] = mi

    # Baselines 2 & 3: fitted logistic models (sklearn when available, else pure_ml).
    for name, feats in (("distance_time_vol", DISTANCE_TIME_VOL_FEATURES),
                        ("microstructure_logistic", MICROSTRUCTURE_FEATURES)):
        res = _fit_for_artifact(rows, feats, train_idx, val_idx, kind="logistic")
        if res is None:
            report["models"][name] = {"error": "no training rows"}
            continue
        if res.get("error"):
            report["models"][name] = {"error": res["error"]}
            continue
        report["models"][name] = res["metrics"]
        art_info = _save_model_artifact(
            config, name=name, feature_names=feats, payload=res["payload"], metrics=res["metrics"],
            split=split, gate=gate, training_ready=training_ready, diagnostic_only=diagnostic_only,
            tradable_stamp=tradable_stamp, staged=staged, created_by_command=created_by_command,
            series=series, notes=notes)
        report["artifacts"].append(art_info)

    report["trained"] = bool(report["artifacts"])
    report["tradable"] = False  # uncalibrated => never usable by policy in this prompt
    return report


def run_train_model(config, *, series: str = "KXBTC15M", model: str = "logistic",
                    diagnostic_only: bool = False, embargo_windows: int = 1,
                    staged: bool = True, created_by_command: str = "kalshi-train-model") -> dict:
    """Train a single named model. ``logistic`` uses sklearn (else pure_ml diagnostic);
    ``lightgbm`` is the optional challenger — it blocks clearly when LightGBM is absent,
    and is gated/staged like the others. Never promotes; never fakes results."""
    model_l = model.lower()
    if model_l in ("xgboost",):
        return {"series": series, "model": model, "trained": False, "refused": True,
                "blockers": [f"{model} is not implemented/installed; this build will not fake results."],
                "dependency_available": False, "status": "BLOCKED_DEPENDENCY"}
    if model_l == "lightgbm" and not sklearn_models.LIGHTGBM_AVAILABLE:
        return {"series": series, "model": model, "trained": False, "refused": True,
                "blockers": ["lightgbm is not installed (optional challenger). Install it "
                             "(pip install lightgbm) AND reach the window gate; not faked."],
                "dependency_available": False, "status": "BLOCKED_DEPENDENCY"}

    ds = build_model_dataset(config, series=series, include_deribit="auto")
    gate = ds["gate"]
    if not gate["training_ready"] and not diagnostic_only:
        return {"series": series, "model": model, "trained": False, "refused": True,
                "gate": gate, "status": gate["status"],
                "dependency_available": (model_l != "lightgbm" or sklearn_models.LIGHTGBM_AVAILABLE),
                "blockers": [f"gate_windows={gate['gate_windows']} < {MIN_TRAIN_WINDOWS}; "
                             "pass --diagnostic-only for a NON-TRADABLE sanity fit."]}

    rows = ds["rows"]
    train_idx, val_idx = split_indices(rows, embargo_windows=embargo_windows)
    split = chronological_split(rows, embargo_windows=embargo_windows)
    kind = "lightgbm" if model_l == "lightgbm" else "logistic"
    feats = (DISTANCE_TIME_VOL_FEATURES if model_l in ("distance_time_vol", "distance")
             else MICROSTRUCTURE_FEATURES)
    res = _fit_for_artifact(rows, feats, train_idx, val_idx, kind=kind)
    if res is None:
        return {"series": series, "model": model, "trained": False,
                "blockers": ["no training rows"], "gate": gate, "status": gate["status"]}
    if res.get("error"):
        return {"series": series, "model": model, "trained": False, "refused": True,
                "status": "FIT_ERROR", "gate": gate, "blockers": [res["error"]]}
    tradable_stamp = bool(gate["training_ready"] and not diagnostic_only)
    notes = ("diagnostic-only" if not tradable_stamp else "uncalibrated (not policy-usable)")
    art_info = _save_model_artifact(
        config, name=f"{model_l}_model", feature_names=feats, payload=res["payload"],
        metrics=res["metrics"], split=split, gate=gate, training_ready=gate["training_ready"],
        diagnostic_only=diagnostic_only, tradable_stamp=tradable_stamp, staged=staged,
        created_by_command=created_by_command, series=series, notes=notes)
    return {"series": series, "model": model, "trained": True, "tradable": False,
            "gate": gate, "status": gate["status"], "metrics": res["metrics"],
            "training_backend": res["payload"]["model_backend"], "staged": bool(staged),
            "dependency_available": True, "artifacts": [art_info]}
