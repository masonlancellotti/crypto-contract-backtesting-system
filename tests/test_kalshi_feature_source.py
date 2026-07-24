"""Second-level (sub-second / WS) feature-source abstraction (Strategy ⑤).

Covers the cadence/source selector, the joined-snapshot -> feature-row adapter,
source routing through the shared loader, config propagation, and that the REST
default path stays byte-identical. READ-ONLY; no orders, no live, no paper here.
"""

import gzip
import json
from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi import feature_source as fs
from btc5m.venues.kalshi.feature_schema import feature_vector, training_feature_names
from btc5m.venues.kalshi.readiness import feature_row_usable

TK = "KXBTC15M-26JUN141400-T100"


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    return load_config(mode="paper")


def _jrow(ticker, as_of, **over):
    r = dict(stream="hires_joined_snapshot", as_of_ms=as_of, market_ticker=ticker,
             seconds_to_close=300.0, reference_start_price=100000.0, close_ms=as_of + 300_000,
             yes_ask=52, no_ask=49, yes_ask_size=100, no_ask_size=80, kalshi_book_age_ms=120,
             coinbase_mid=100050.0, binance_mid=100055.0, coinbase_age_ms=80, binance_age_ms=40,
             basis=5.0, coinbase_stale=False, binance_stale=False, realized_vol_60s=2e-3,
             has_spot_feed=True, has_perp_feed=True,
             spot_return_5s=1e-4, spot_return_15s=3e-4, no_live_orders=True,
             live_submission_allowed=False)
    r.update(over)
    return r


def _write(path: Path, rows, gz=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    op = gzip.open if gz else open
    with op(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _write_feature_rows(cfg, rows):
    d = cfg.data_path() / "features"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "kalshi_feature_rows-20260614.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# --------------------------------------------------------------------------- #
# source normalization
# --------------------------------------------------------------------------- #
def test_normalize_source_aliases_and_default():
    assert fs.normalize_source("rest") == fs.REST
    assert fs.normalize_source("hires") == fs.HIRES
    assert fs.normalize_source("subsecond") == fs.HIRES
    assert fs.normalize_source("sub-second") == fs.HIRES
    assert fs.normalize_source("ws") == fs.HIRES
    assert fs.normalize_source("WEBSOCKET") == fs.HIRES
    assert fs.normalize_source(None) == fs.REST           # no config -> rest default


def test_normalize_source_reads_config():
    class _C:
        feature_source = "hires"
    assert fs.normalize_source(None, config=_C()) == fs.HIRES
    assert fs.normalize_source("rest", config=_C()) == fs.REST   # explicit overrides config


def test_normalize_source_rejects_unknown():
    with pytest.raises(ValueError):
        fs.normalize_source("orderbook")


# --------------------------------------------------------------------------- #
# joined -> feature-row adapter
# --------------------------------------------------------------------------- #
def test_adapter_maps_derivable_fields_and_is_usable():
    r = fs.joined_to_feature_row(_jrow(TK, 1_000_000))
    assert feature_row_usable(r) is True
    assert r["has_orderbook"] and r["has_underlying"] and r["has_start_reference"]
    assert r["yes_ask"] == 52 and r["no_ask"] == 49
    assert r["quote_age_ms"] == 120
    assert r["distance_to_start"] == pytest.approx(50.0)        # 100050 - 100000
    assert r["fraction_window_elapsed"] == pytest.approx((900 - 300) / 900)
    assert r["spot_perp_basis"] == 5.0
    assert r["realized_vol_60s"] == 2e-3
    assert r["series_ticker"] == "KXBTC15M"
    assert r["feature_source"] == "hires" and r["cadence"] == "subsecond"
    assert r["feature_set_version"] == 3


def test_adapter_nulls_nonderivable_and_excludes_deribit():
    r = fs.joined_to_feature_row(_jrow(TK, 1_000_000))
    # not carried by the WS join -> absent (read as None by consumers)
    for missing in ("yes_bid", "no_bid", "yes_spread", "depth_imbalance",
                    "binance_ofi_best", "perp_cvd_60s", "realized_vol_180s"):
        assert r.get(missing) is None
    # deribit explicitly excluded
    assert r["deribit_available"] is False and r["deribit_stale"] is True
    assert r["has_deribit"] is False


def test_adapter_is_read_only_safe():
    r = fs.joined_to_feature_row(_jrow(TK, 1_000_000))
    assert r["no_live_orders"] is True
    assert r["live_submission_allowed"] is False


def test_adapter_missing_book_or_feed_marks_unusable():
    no_book = fs.joined_to_feature_row(_jrow(TK, 1, yes_ask=None, no_ask=None))
    assert no_book["has_orderbook"] is False
    assert feature_row_usable(no_book) is False
    no_feed = fs.joined_to_feature_row(_jrow(TK, 1, has_spot_feed=False, has_perp_feed=False))
    assert no_feed["has_underlying"] is False
    assert feature_row_usable(no_feed) is False


def test_adapter_rows_vectorize_without_leakage():
    r = fs.joined_to_feature_row(_jrow(TK, 1_000_000))
    vec = feature_vector(r, training_feature_names())   # asserts no-leakage internally
    assert len(vec) == len(training_feature_names())
    assert any(x is not None for x in vec)              # derivable subset populated


# --------------------------------------------------------------------------- #
# loader routing (REST default never degraded; hires reads joined snapshots)
# --------------------------------------------------------------------------- #
def test_load_feature_rows_rest_default(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    _write_feature_rows(cfg, [{"market_ticker": TK, "as_of_ms": 5, "has_orderbook": True}])
    rows = fs.load_feature_rows(cfg)                    # no source -> rest default
    assert len(rows) == 1 and rows[0]["market_ticker"] == TK
    assert "feature_source" not in rows[0]              # untouched REST row


def test_load_feature_rows_hires_routes_to_joined(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    d = cfg.data_path() / "features" / "hires" / "20260614"
    _write(d / "kalshi_hires_joined_snapshots-20260614_010101_0007.jsonl",
           [_jrow(TK, 1_000_000), _jrow(TK, 1_000_500)])
    _write(d / "kalshi_hires_joined_snapshots-20260614_010110_0007.jsonl.gz",
           [_jrow(TK, 1_001_000)], gz=True)
    rows = fs.load_feature_rows(cfg, source="hires")
    assert len(rows) == 3
    assert all(r["feature_source"] == "hires" for r in rows)
    assert all(feature_row_usable(r) for r in rows)


def test_config_feature_source_propagates(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    assert cfg.feature_source == "rest"                 # field default
    d = cfg.data_path() / "features" / "hires" / "20260614"
    _write(d / "kalshi_hires_joined_snapshots-20260614_010101_0007.jsonl",
           [_jrow(TK, 1_000_000)])
    cfg.feature_source = "hires"
    rows = fs.load_feature_rows(cfg)                    # source=None -> config -> hires
    assert len(rows) == 1 and rows[0]["feature_source"] == "hires"


def test_latest_hires_feature_rows_freshest_per_ticker(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    d = cfg.data_path() / "features" / "hires" / "20260614"
    _write(d / "kalshi_hires_joined_snapshots-20260614_010101_0007.jsonl",
           [_jrow(TK, 1_000_000), _jrow(TK, 1_002_000)])
    rows = fs.latest_hires_feature_rows(cfg, series="KXBTC15M")
    assert len(rows) == 1
    assert rows[0]["as_of_ms"] == 1_002_000            # freshest kept


# --------------------------------------------------------------------------- #
# end-to-end: dataset + readiness run on the hires cadence via the abstraction
# --------------------------------------------------------------------------- #
def _seed_hires_with_labels(cfg, n_windows=3, rows_per=4):
    """Write joined snapshots across several windows + matching OFFICIAL labels."""
    d = cfg.data_path() / "features" / "hires" / "20260614"
    lab = cfg.data_path() / "labels"
    lab.mkdir(parents=True, exist_ok=True)
    label_rows = []
    base = 1_000_000_000
    for w in range(n_windows):
        tk = f"KXBTC15M-26JUN14{1400 + w:04d}-T100"
        start = base + w * 1_000_000
        snaps = [_jrow(tk, start + i * 1000, close_ms=start + 300_000) for i in range(rows_per)]
        _write(d / f"kalshi_hires_joined_snapshots-20260614_0101{w:02d}_0007.jsonl", snaps)
        label_rows.append({"market_ticker": tk, "label_source_status": "OFFICIAL",
                           "label_yes_resolved": w % 2, "reference_start_price": 100000.0,
                           "close_ms": start + 300_000, "created_at_ms": start})
    with (lab / "kalshi_settlement_labels-20260614.jsonl").open("w", encoding="utf-8") as fh:
        for r in label_rows:
            fh.write(json.dumps(r) + "\n")


def test_build_model_dataset_on_hires_source(tmp_path, monkeypatch):
    from btc5m.venues.kalshi.model_dataset import build_model_dataset
    cfg = _env(tmp_path, monkeypatch)
    _seed_hires_with_labels(cfg, n_windows=3, rows_per=4)
    out = build_model_dataset(cfg, series="KXBTC15M", source="hires")
    assert out["feature_source"] == "hires"
    assert out["counts"]["final_model_rows"] == 12        # 3 windows x 4 rows, all usable+labeled
    assert out["distinct_windows"] == 3
    assert out["deribit_included"] is False               # hires never carries deribit


def test_readiness_on_hires_source(tmp_path, monkeypatch):
    from btc5m.venues.kalshi.readiness import load_kalshi_readiness
    cfg = _env(tmp_path, monkeypatch)
    _seed_hires_with_labels(cfg, n_windows=3, rows_per=4)
    r = load_kalshi_readiness(cfg, source="hires")
    assert r["feature_backed_official_windows"] == 3
    # config-driven selection reaches readiness too
    cfg.feature_source = "hires"
    assert load_kalshi_readiness(cfg)["feature_backed_official_windows"] == 3
