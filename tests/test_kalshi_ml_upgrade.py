"""ML-upgrade hardening: sklearn training path, artifact STAGING safety, parquet IO.

Verifies (offline) that: the serious sklearn pipeline trains + predicts in [0,1];
new model/calibrator artifacts are STAGED (data/models/staged/) and therefore
INVISIBLE to the runtime's active auto-selection; the dataset can be written as
parquet without touching the active latest pointers; and staging/lifecycle metadata
marks everything NON_PROMOTED + not live-approved. Nothing trades or promotes.
"""

import json

import pytest

from btc5m.config import load_config

WIN = 15 * 60 * 1000


def _frow(tk, *, as_of, close, yes):
    return {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
            "has_start_reference": True, "book_ok": True,
            "seconds_to_close": (close - as_of) / 1000.0, "as_of_ms": as_of, "close_ms": close,
            "feature_set_version": 3, "yes_ask": 0.42, "no_ask": 0.60,
            "yes_spread": 0.02, "no_spread": 0.02, "top_depth": 100.0,
            "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": 100,
            "reference_start_price": 70000.0, "reference_price": 70010.0,
            "distance_to_start": (50.0 if yes else -50.0), "spot_sigma_per_sqrt_s": 1e-4,
            "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
            "distance_to_line_vol_normalized": (0.5 if yes else -0.5),
            "spot_return_60s": (0.001 if yes else -0.001)}


def _write_fixture(tmp_path, n_windows=8, rows_per=6):
    feats = (tmp_path / "features"); feats.mkdir(parents=True)
    labels = (tmp_path / "labels"); labels.mkdir(parents=True)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(n_windows):
        close = base + (w + 1) * WIN
        yes = w % 2
        for i in range(rows_per):
            fr.append(_frow(f"KX-{w}", as_of=close - (200 - i * 10) * 1000, close=close, yes=yes))
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL",
                   "label_yes_resolved": yes})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fr) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lr) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# sklearn pipeline unit tests
# --------------------------------------------------------------------------- #
def test_sklearn_logistic_pipeline_probs_in_range():
    from btc5m.models import sklearn_models
    if not sklearn_models.SKLEARN_AVAILABLE:
        pytest.skip("sklearn not installed")
    X = [[float(i % 3), None, float(i)] for i in range(40)]   # None -> imputed
    y = [i % 2 for i in range(40)]
    pipe = sklearn_models.fit_pipeline("logistic", X, y)
    p = sklearn_models.predict_proba_pipeline(pipe, X)
    assert len(p) == 40 and all(0.0 <= v <= 1.0 for v in p)


def test_sklearn_lightgbm_challenger_trains_if_available():
    from btc5m.models import sklearn_models
    if not sklearn_models.LIGHTGBM_AVAILABLE:
        pytest.skip("lightgbm not installed (optional challenger)")
    X = [[float(i % 5), float((i * 7) % 3), None] for i in range(80)]
    y = [1 if (i * 7) % 3 == 0 else 0 for i in range(80)]
    pipe = sklearn_models.fit_pipeline("lightgbm", X, y)
    p = sklearn_models.predict_proba_pipeline(pipe, X)
    assert len(p) == 80 and all(0.0 <= v <= 1.0 for v in p)


def test_fit_pipeline_single_class_raises():
    from btc5m.models import sklearn_models
    if not sklearn_models.SKLEARN_AVAILABLE:
        pytest.skip("sklearn not installed")
    with pytest.raises(ValueError):
        sklearn_models.fit_pipeline("logistic", [[1.0], [2.0]], [1, 1])


# --------------------------------------------------------------------------- #
# Artifact STAGING safety — runtime cannot auto-select staged artifacts
# --------------------------------------------------------------------------- #
def test_train_artifacts_staged_and_invisible_to_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    from btc5m.venues.kalshi.executable_backtest import (
        latest_model_artifact_path, latest_staged_model_artifact_path,
    )
    from btc5m.venues.kalshi.train_baselines import run_train_baselines
    r = run_train_baselines(load_config(mode="paper"), series="KXBTC15M",
                            diagnostic_only=True, staged=True)
    assert r["staged"] is True and r["artifacts"]
    for a in r["artifacts"]:
        assert "/staged/" in a["artifact_file"].replace("\\", "/")
        assert a["tradable_status"] == "DIAGNOSTIC_ONLY"
    cfg = load_config(mode="paper")
    # The runtime selects from data/models/ (NON-recursive) -> never sees staged/.
    assert latest_model_artifact_path(cfg) is None
    assert latest_staged_model_artifact_path(cfg) is not None


def test_staged_artifact_metadata_and_scoreable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    from btc5m.models.sklearn_models import SKLEARN_AVAILABLE
    from btc5m.venues.kalshi.executable_backtest import predict_from_artifact
    from btc5m.venues.kalshi.model_artifacts import load_artifact
    from btc5m.venues.kalshi.train_baselines import run_train_baselines
    r = run_train_baselines(load_config(mode="paper"), series="KXBTC15M",
                            diagnostic_only=True, staged=True)
    art = load_artifact(r["artifacts"][0]["artifact_file"])
    assert art["is_staged"] is True and art["is_promoted"] is False
    assert art["promotion_required"] is True and art["live_approved"] is False
    assert art["tradable_status"] == "DIAGNOSTIC_ONLY"
    if SKLEARN_AVAILABLE:
        assert art["model_backend"] == "sklearn" and art.get("sklearn_pipeline") is not None
    # The executable backtest can still score the staged artifact (sklearn or pure).
    rows = [_frow("KX-0", as_of=1, close=2, yes=1)]
    p = predict_from_artifact(art, rows, [0])
    assert len(p) == 1 and 0.0 <= p[0] <= 1.0


# --------------------------------------------------------------------------- #
# Dataset parquet IO + staged/no-update-latest
# --------------------------------------------------------------------------- #
def test_dataset_parquet_staged_leaves_latest_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    pytest.importorskip("pyarrow")
    import pandas as pd
    from btc5m.venues.kalshi.model_dataset import build_model_dataset, write_dataset
    cfg = load_config(mode="paper")
    ds = build_model_dataset(cfg, series="KXBTC15M", feature_version="all")
    paths = write_dataset(cfg, ds, fmt="parquet", staged=True)
    assert paths["staged"] is True and paths["update_latest"] is False
    assert paths["latest_file"] is None
    assert paths["dataset_file"].endswith(".parquet")
    assert (tmp_path / "models" / "staged").exists()
    # active latest pointers + active schema are NOT created by a staged build
    assert not (tmp_path / "models" / "kalshi_model_dataset_latest.parquet").exists()
    assert not (tmp_path / "models" / "kalshi_feature_schema.json").exists()
    df = pd.read_parquet(paths["dataset_file"])
    assert len(df) == len(ds["rows"]) and "label_yes_resolved" in df.columns


def test_dataset_update_latest_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    from btc5m.venues.kalshi.model_dataset import build_model_dataset, write_dataset
    cfg = load_config(mode="paper")
    ds = build_model_dataset(cfg, series="KXBTC15M", feature_version="all")
    # no-update (the CLI default in this build): active latest pointers untouched
    p0 = write_dataset(cfg, ds, fmt="jsonl", update_latest=False)
    assert p0["update_latest"] is False and p0["latest_file"] is None
    assert not (tmp_path / "models" / "kalshi_model_dataset_latest.jsonl").exists()
    # explicit opt-in updates the active pointers
    p1 = write_dataset(cfg, ds, fmt="jsonl", update_latest=True)
    assert p1["update_latest"] is True and p1["latest_file"] is not None
    assert (tmp_path / "models" / "kalshi_model_dataset_latest.jsonl").exists()
    assert (tmp_path / "models" / "kalshi_feature_schema.json").exists()


# --------------------------------------------------------------------------- #
# Calibration: staged, held-out, overfit risk reported
# --------------------------------------------------------------------------- #
def test_calibrate_staged_non_promoted_and_overfit_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=10)
    from btc5m.venues.kalshi.calibrate import (
        latest_calibrator_path, latest_staged_calibrator_path, load_calibrator,
    )
    from btc5m.venues.kalshi.calibration_report import run_calibrate_model
    cfg = load_config(mode="paper")
    r = run_calibrate_model(cfg, series="KXBTC15M", method="isotonic",
                            diagnostic_only=True, staged=True)
    assert r.get("refused") is not True and r["staged"] is True
    assert "/staged/" in r["artifact"]["calibrator_file"].replace("\\", "/")
    art = load_calibrator(r["artifact"]["calibrator_file"])
    assert art["is_staged"] is True and art["is_promoted"] is False
    assert art["calibration_status"] == "diagnostic" and art["live_approved"] is False
    assert r["overfit"]["overfit_risk"] in ("low", "medium", "high")
    # runtime active calibrator selector does NOT see staged
    assert latest_calibrator_path(cfg) is None
    assert latest_staged_calibrator_path(cfg) is not None


def test_check_live_disabled_still_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from btc5m.cli import main
    assert main(["check-live-disabled"]) == 0
