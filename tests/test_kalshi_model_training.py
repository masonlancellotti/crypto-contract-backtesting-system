"""Kalshi model dataset + training pipeline — schema, dataset, splits, pure-ML
baselines, gates, artifacts, and safety. All offline; stdlib only; no orders.
"""

import json

from btc5m.config import load_config
from btc5m.models import pure_ml
from btc5m.venues.kalshi import feature_schema as fs
from btc5m.venues.kalshi.model_artifacts import (
    NON_TRADABLE, TRADABLE, build_artifact, is_tradable, load_artifact, save_artifact,
)
from btc5m.venues.kalshi.model_dataset import build_model_dataset
from btc5m.venues.kalshi.splits import chronological_split, group_windows, split_indices
from btc5m.venues.kalshi.train_baselines import run_train_baselines, run_train_model

WIN = 15 * 60 * 1000


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _frow(tk, *, as_of, close, fsv=2, **extra):
    row = {"market_ticker": tk, "series_ticker": "KXBTC15M", "has_orderbook": True,
           "has_underlying": True, "has_start_reference": True, "book_ok": True,
           "seconds_to_close": (close - as_of) / 1000.0, "as_of_ms": as_of, "close_ms": close,
           "feature_set_version": fsv, "yes_ask": 0.42, "no_ask": 0.60,
           "reference_start_price": 70000.0, "reference_price": 70010.0,
           "distance_to_start": 10.0, "spot_sigma_per_sqrt_s": 1e-4,
           "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
           "distance_to_line_vol_normalized": 0.3}
    row.update(extra)
    return row


def _label(tk, yes):
    return {"market_ticker": tk, "label_source_status": "OFFICIAL", "label_yes_resolved": yes}


def _write_fixture(tmp_path, n_windows=5, rows_per=6, with_orphan=True):
    feats = (tmp_path / "features"); feats.mkdir(parents=True)
    labels = (tmp_path / "labels"); labels.mkdir(parents=True)
    base = 1_780_000_000_000
    frows, lrows = [], []
    for w in range(n_windows):
        close = base + (w + 1) * WIN
        # label correlated with distance so models can learn something
        yes = w % 2
        for i in range(rows_per):
            frows.append(_frow(f"KX-{w}", as_of=close - (250 - i * 10) * 1000, close=close,
                               distance_to_start=(50.0 if yes else -50.0),
                               spot_return_60s=(0.001 if yes else -0.001)))
        lrows.append(_label(f"KX-{w}", yes))
    if with_orphan:
        lrows.append(_label("KX-ORPHAN", 1))   # official label with NO feature rows
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in frows) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lrows) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Feature schema
# --------------------------------------------------------------------------- #
def test_schema_excludes_leakage_and_declares_groups():
    names = fs.training_feature_names()
    assert "label_yes_resolved" not in names and "result" not in names
    assert "reference_price" not in names           # non-stationary level excluded
    assert "seconds_to_close" in names and "distance_to_start" in names
    # leakage guard raises
    import pytest
    with pytest.raises(ValueError):
        fs.assert_no_leakage(["seconds_to_close", "label_yes_resolved"])
    sj = fs.schema_json()
    assert sj["hard_class_field"] == "hard_class_prediction"
    assert set(sj["groups"]) >= {"A", "B", "C", "D", "E", "F", "G"}


def test_feature_vector_encodes_types():
    row = {"seconds_to_close": 120.0, "deribit_available": True, "binance_queue_imbalance": None}
    vec = fs.feature_vector(row, ["seconds_to_close", "deribit_available", "binance_queue_imbalance"])
    assert vec == [120.0, 1.0, None]


# --------------------------------------------------------------------------- #
# Dataset builder
# --------------------------------------------------------------------------- #
def test_dataset_joins_official_excludes_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=5, rows_per=6, with_orphan=True)
    ds = build_model_dataset(load_config(mode="paper"), series="KXBTC15M")
    assert ds["distinct_windows"] == 5                   # orphan window excluded
    assert all(r["label_source"] == "OFFICIAL" for r in ds["rows"])
    assert all("KX-ORPHAN" != r["ticker"] for r in ds["rows"])
    # leakage columns never appear in the declared training feature set
    fs.assert_no_leakage(ds["training_features"])
    # preserves timestamps + reports missingness
    assert all(r["as_of_ts_ms"] is not None and r["market_close_ts_ms"] is not None for r in ds["rows"])
    assert "seconds_to_close" in ds["missingness"]
    assert ds["gate"]["status"] == "NOT_TRAINING_READY"  # 5 << 150


def test_dataset_no_lookahead_and_version_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=3, rows_per=4, with_orphan=False)
    # latest(v3)-only filter drops the v2 fixture rows -> empty, reported (not crash)
    ds = build_model_dataset(load_config(mode="paper"), series="KXBTC15M", feature_version="latest")
    assert ds["counts"]["rows_rejected_old_feature_version"] > 0
    assert ds["distinct_windows"] == 0


# --------------------------------------------------------------------------- #
# Splits
# --------------------------------------------------------------------------- #
def test_split_by_window_not_row_with_embargo(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=6, rows_per=5, with_orphan=False)
    rows = build_model_dataset(load_config(mode="paper"), series="KXBTC15M")["rows"]
    sp = chronological_split(rows, embargo_windows=1)
    assert sp["applied"] and sp["embargoed_windows"] == 1
    assert sp["train_windows"] + sp["val_windows"] + sp["embargoed_windows"] == sp["n_windows"]
    assert sp["no_leak"] is True
    # every val row belongs to a window not in train (window-level split)
    train_idx, val_idx = split_indices(rows, embargo_windows=1)
    train_w = {rows[i]["ticker"] for i in train_idx}
    val_w = {rows[i]["ticker"] for i in val_idx}
    assert train_w.isdisjoint(val_w)


def test_split_blocks_when_too_few_windows():
    rows = [{"ticker": "A", "close_ms": 1, "label_yes_resolved": 1}]
    sp = chronological_split(rows, embargo_windows=1)
    assert sp["applied"] is False and "need" in sp["reason"]


# --------------------------------------------------------------------------- #
# Pure-ML primitives
# --------------------------------------------------------------------------- #
def test_pure_logistic_fits_and_bounds_probabilities():
    X = [[float(i)] for i in range(-20, 20)]
    y = [1 if i >= 0 else 0 for i in range(-20, 20)]
    imp = pure_ml.StandardImputer().fit(X)
    model = pure_ml.LogisticRegression(epochs=300).fit(imp.transform(X), y)
    p = model.predict_proba(imp.transform(X))
    assert all(0.0 <= pi <= 1.0 for pi in p)
    assert pure_ml.roc_auc(y, p) > 0.9
    assert pure_ml.brier(y, p) < 0.2


def test_imputer_handles_missing():
    imp = pure_ml.StandardImputer().fit([[1.0], [3.0], [None]])
    out = imp.transform([[None]])
    assert out[0][0] == 0.0   # None -> column mean -> standardized 0


# --------------------------------------------------------------------------- #
# Training gates + baselines
# --------------------------------------------------------------------------- #
def test_train_baselines_refuses_below_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=5, rows_per=6, with_orphan=False)
    r = run_train_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=False)
    assert r.get("refused") is True and r["trained"] is False and not r["artifacts"]


def test_train_baselines_diagnostic_only_marks_non_tradable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=6, rows_per=6, with_orphan=False)
    r = run_train_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=True)
    assert r["trained"] is True and r["tradable"] is False
    assert r["artifacts"], "diagnostic training should still write artifacts"
    for a in r["artifacts"]:
        assert a["tradability"] == NON_TRADABLE
        art = load_artifact(a["artifact_file"])
        assert is_tradable(art) is False                      # NON_TRADABLE + uncalibrated
        assert art["feature_names"] and art["split_metadata"]
        # serious sklearn artifacts carry a fitted pipeline (imputer is inside it);
        # the pure_ml fallback carries an imputer dict instead.
        assert art.get("sklearn_pipeline") is not None or art.get("imputer")
        assert art["tradable_status"] == "DIAGNOSTIC_ONLY" and art["is_staged"] is True
    # market-implied + both logistic baselines present, probabilities valid
    mi = r["models"]["market_implied"]
    assert mi["n"] > 0 and 0.0 <= mi["brier"] <= 1.0
    for name in ("distance_time_vol", "microstructure_logistic"):
        assert "accuracy" in r["models"][name]


def test_train_model_lightgbm_gated_or_blocked(tmp_path, monkeypatch):
    """LightGBM challenger: gated like the others when installed; clear dependency
    block when absent. Either way it never fakes results and never promotes."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=4, rows_per=5, with_orphan=False)
    from btc5m.models.sklearn_models import LIGHTGBM_AVAILABLE
    r = run_train_model(load_config(mode="paper"), series="KXBTC15M", model="lightgbm")
    assert r["refused"] is True
    if LIGHTGBM_AVAILABLE:
        # installed -> blocked by the GATE (4 << 150), not the dependency
        assert r["status"] == "NOT_TRAINING_READY" and r.get("dependency_available") is True
    else:
        assert r["status"] == "BLOCKED_DEPENDENCY" and r["dependency_available"] is False


def test_train_model_logistic_refuses_below_gate_without_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=5, rows_per=5, with_orphan=False)
    r = run_train_model(load_config(mode="paper"), series="KXBTC15M", model="logistic")
    assert r.get("refused") is True and r["trained"] is False


# --------------------------------------------------------------------------- #
# Artifacts + tradability
# --------------------------------------------------------------------------- #
def test_artifact_tradability_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    base = dict(model_name="t", model_obj_dict={"w": [0.0], "b": 0.0}, feature_names=["x"],
                imputer_dict={"means": [0.0], "stds": [1.0]}, split_metadata={"train_windows": 1},
                training_config={}, metrics={}, model_schema_version=1)
    diag = build_artifact(**base, tradable=False)
    uncal = build_artifact(**base, tradable=True, calibration_status="uncalibrated")
    cal = build_artifact(**base, tradable=True, calibration_status="calibrated")
    assert diag["tradability"] == NON_TRADABLE and is_tradable(diag) is False
    assert uncal["tradability"] == TRADABLE and is_tradable(uncal) is False  # needs calibration
    assert is_tradable(cal) is True
    paths = save_artifact(cfg, diag, stem="art_test")
    assert is_tradable(load_artifact(paths["artifact_file"])) is False


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_no_paper_candidate_and_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=6, rows_per=6, with_orphan=False)
    r = run_train_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=True)
    # No trained artifact is usable by policy (all uncalibrated/NON_TRADABLE).
    assert all(not is_tradable(load_artifact(a["artifact_file"])) for a in r["artifacts"])
    from btc5m.cli import main
    assert main(["check-live-disabled"]) == 0
