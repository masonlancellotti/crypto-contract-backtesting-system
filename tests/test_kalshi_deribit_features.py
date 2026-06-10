"""Deribit native OPTIONAL source — config, enriched client snapshot, point-in-time
join, feature-row integration, train-dry-run reporting, source-health, recording.

All offline (no network): the public client's ``fetch_all`` is monkeypatched with
fixtures. Verifies Deribit never blocks the Kalshi pipeline and never invents data.
"""

import json

from btc5m.config import load_config
from btc5m.data.deribit_client import (
    DeribitClient, fetch_deribit_snapshot, normalize, summarize_options,
)
from btc5m.venues.kalshi.deribit_features import (
    DeribitState, annualized_vol_pct, deribit_feature_fields, regime_from_vol,
)
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.features import FEATURE_SET_VERSION
from btc5m.venues.kalshi.paper import build_feature_row


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _raw():
    return {
        "currency": "BTC",
        "index": {"result": {"index_price": 72000.0}, "usIn": 1_780_000_000_000_000},
        "dvol": {"result": {"data": [[1, 50, 51, 49, 55.0]]}},
        "historical_vol": {"result": [[1, 41.0]]},
        "book_summary": {"result": [
            {"instrument_name": "BTC-27JUN25-72000-C", "mark_iv": 50.0, "open_interest": 10, "volume": 5},
            {"instrument_name": "BTC-27JUN25-72000-P", "mark_iv": 54.0, "open_interest": 20, "volume": 7},
            {"instrument_name": "BTC-27JUN25-60000-C", "mark_iv": 80.0, "open_interest": 3, "volume": 1},
        ]},
    }


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_config_defaults_and_disabled(monkeypatch):
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    monkeypatch.delenv("DERIBIT_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("DERIBIT_STALE_THRESHOLD_SECONDS", raising=False)
    cfg = load_config(mode="paper")
    assert cfg.deribit.enabled is False
    assert cfg.deribit.poll_interval_seconds == 30
    assert cfg.deribit.stale_threshold_seconds == 180


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.setenv("DERIBIT_POLL_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("DERIBIT_STALE_THRESHOLD_SECONDS", "90")
    cfg = load_config(mode="paper")
    assert cfg.deribit.enabled is True
    assert cfg.deribit.poll_interval_seconds == 15
    assert cfg.deribit.stale_threshold_seconds == 90


def test_missing_credentials_do_not_break_public_config(monkeypatch):
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.delenv("DERIBIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("DERIBIT_CLIENT_SECRET", raising=False)
    cfg = load_config(mode="paper")
    assert cfg.deribit.client_id is None and cfg.deribit.client_secret is None
    assert DeribitClient(cfg).enabled is True  # public mode works with no creds


def _clear_deribit_env(monkeypatch):
    for k in ("DERIBIT_ENABLED", "DERIBIT_INCLUDE_IN_MODEL_FEATURES",
              "DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED",
              "DERIBIT_RECORD_RAW", "DERIBIT_RECORD_NORMALIZED"):
        monkeypatch.delenv(k, raising=False)


def test_include_in_model_features_defaults_false_and_record_toggles(monkeypatch):
    _clear_deribit_env(monkeypatch)
    d = load_config(mode="paper").deribit
    assert d.include_in_model_features is False         # SEPARATE control, default off
    assert d.allow_historical_features_when_disabled is False
    assert d.record_raw is True and d.record_normalized is True
    assert d.select_for_model_features is False         # disabled + not-included


def test_include_cannot_silently_select_while_disabled(monkeypatch):
    """DERIBIT_INCLUDE_IN_MODEL_FEATURES=true must NOT select while disabled
    unless DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED is also set."""
    _clear_deribit_env(monkeypatch)
    monkeypatch.setenv("DERIBIT_INCLUDE_IN_MODEL_FEATURES", "true")
    d = load_config(mode="paper").deribit
    assert d.enabled is False and d.include_in_model_features is True
    assert d.select_for_model_features is False          # not silently selected
    # explicit opt-in to historical-while-disabled flips selection on
    monkeypatch.setenv("DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED", "true")
    assert load_config(mode="paper").deribit.select_for_model_features is True


def test_enabled_plus_include_selects_for_model(monkeypatch):
    _clear_deribit_env(monkeypatch)
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.setenv("DERIBIT_INCLUDE_IN_MODEL_FEATURES", "true")
    assert load_config(mode="paper").deribit.select_for_model_features is True


# --------------------------------------------------------------------------- #
# Enriched client / parsers
# --------------------------------------------------------------------------- #
def test_summarize_options_call_put_split_and_atm():
    s = summarize_options(_raw()["book_summary"], index_price=72000.0)
    assert s["open_interest_total"] == 33 and s["volume_total"] == 13
    assert s["call_open_interest_total"] == 13   # 10 + 3
    assert s["put_open_interest_total"] == 20
    assert s["call_volume_total"] == 6 and s["put_volume_total"] == 7
    # ATM = strike nearest index (72000): mean of the 72000 C/P IVs = (50+54)/2
    assert abs(s["atm_iv"] - 52.0) < 1e-9


def test_normalize_full_snapshot_fields():
    n = normalize(_raw(), recv_ms=1_780_000_000_500)
    assert n["deribit_dvol"] == 55.0 and n["deribit_btc_iv_index"] == 55.0  # alias kept
    assert n["deribit_index_price"] == 72000.0
    assert n["deribit_atm_iv"] == 52.0
    assert n["deribit_call_open_interest_total"] == 13
    assert n["deribit_put_open_interest_total"] == 20
    assert abs(n["deribit_put_call_oi_ratio"] - (20 / 13)) < 1e-9
    assert n["source_ts_ms"] == 1_780_000_000_000  # usIn microseconds -> ms
    assert n["deribit_missing_reason"] is None
    assert n["deribit_endpoints"]["dvol"].startswith("/public/")


def test_put_call_ratio_handles_division_by_zero():
    book = {"result": [
        {"instrument_name": "BTC-27JUN25-72000-P", "mark_iv": 54.0, "open_interest": 20, "volume": 7},
    ]}  # puts only -> no calls -> ratios must be None, not a crash
    n = normalize({"currency": "BTC", "book_summary": book}, recv_ms=1)
    assert n["deribit_put_call_oi_ratio"] is None
    assert n["deribit_put_call_volume_ratio"] is None


def test_empty_payloads_none_with_missing_reason():
    n = normalize({"currency": "BTC"}, recv_ms=1)
    assert n["deribit_index_price"] is None and n["deribit_dvol"] is None
    assert n["deribit_atm_iv"] is None
    assert n["deribit_missing_reason"] is not None  # explicit, not invented


def test_fetch_snapshot_offline(monkeypatch):
    monkeypatch.setattr(DeribitClient, "fetch_all", lambda self: _raw())
    snap = fetch_deribit_snapshot(load_config(mode="paper"))
    assert snap["deribit_dvol"] == 55.0 and snap["deribit_atm_iv"] == 52.0


# --------------------------------------------------------------------------- #
# Point-in-time join (no look-ahead)
# --------------------------------------------------------------------------- #
def test_state_latest_at_or_before_no_lookahead():
    st = DeribitState()
    st.ingest({"recv_ms": 1000, "deribit_dvol": 50.0})
    st.ingest({"recv_ms": 2000, "deribit_dvol": 55.0})
    st.ingest({"recv_ms": 3000, "deribit_dvol": 60.0})
    # at t=2500 the latest at-or-before is the 2000 row (NEVER the 3000 future row)
    assert st.latest_at_or_before(2500)["deribit_dvol"] == 55.0
    assert st.latest_at_or_before(3000)["deribit_dvol"] == 60.0
    assert st.latest_at_or_before(500) is None  # nothing before t=500


def test_join_disabled_fields():
    f = deribit_feature_fields(snapshot=None, as_of_ms=10_000, enabled=False)
    assert f["deribit_enabled"] is False and f["deribit_available"] is False
    assert f["deribit_used"] is False
    assert f["deribit_missing_reason"] == "DERIBIT_DISABLED"
    assert f["deribit_dvol"] is None


def test_join_enabled_no_snapshot():
    f = deribit_feature_fields(snapshot=None, as_of_ms=10_000, enabled=True)
    assert f["deribit_enabled"] is True and f["deribit_available"] is False
    assert f["deribit_used"] is False
    assert f["deribit_missing_reason"] == "NO_DERIBIT_SNAPSHOT_AT_OR_BEFORE_ASOF"


def test_join_fresh_used_and_iv_minus_rv():
    snap = normalize(_raw(), recv_ms=100_000)
    f = deribit_feature_fields(
        snapshot=snap, as_of_ms=130_000, enabled=True, stale_threshold_ms=180_000,
        realized_vol_60s=8.9e-5, realized_vol_180s=None)
    assert f["deribit_available"] is True and f["deribit_used"] is True
    assert f["deribit_stale"] is False and f["deribit_age_ms"] == 30_000
    iv = snap["deribit_near_expiry_iv"]
    expected = iv - annualized_vol_pct(8.9e-5)
    assert abs(f["deribit_iv_minus_realized_vol_60s"] - expected) < 1e-9
    assert f["deribit_iv_minus_realized_vol_180s"] is None  # rv180 missing -> None
    assert f["deribit_regime"] == "normal_vol"  # DVOL 55 -> normal


def test_join_stale_snapshot_flagged_but_nonfatal():
    snap = normalize(_raw(), recv_ms=100_000)
    f = deribit_feature_fields(
        snapshot=snap, as_of_ms=400_000, enabled=True, stale_threshold_ms=180_000)
    assert f["deribit_available"] is True
    assert f["deribit_stale"] is True and f["deribit_used"] is False
    assert f["deribit_missing_reason"] == "STALE"


def test_regime_buckets():
    assert regime_from_vol(35.0, None) == "low_vol"
    assert regime_from_vol(55.0, None) == "normal_vol"
    assert regime_from_vol(80.0, None) == "high_vol"
    assert regime_from_vol(None, None) is None


# --------------------------------------------------------------------------- #
# Feature-row integration
# --------------------------------------------------------------------------- #
def _norm_ob():
    return {
        "market_ticker": "KXBTC15M-26JUN010345-45", "series_ticker": "KXBTC15M",
        "status": "active", "close_ms": 5_000_000 + 600_000,
        "yes_bid": 0.40, "yes_ask": 0.42, "no_bid": 0.58, "no_ask": 0.60,
        "yes_bid_size": 500.0, "no_bid_size": 300.0, "yes_ask_size": 300.0, "no_ask_size": 500.0,
        "book_validity_flags": {"yes_side_present": True, "no_side_present": True,
                                "incomplete_book": False, "yes_crossed": False,
                                "no_crossed": False, "prices_in_range": True},
    }


def test_feature_row_without_deribit_has_disabled_fields():
    row = build_feature_row(
        _norm_ob(), as_of_ms=5_000_000, reference_price=72000.0, sigma_per_sqrt_s=0.0005,
        start_reference=71900.0, fee_model=KalshiFeeModel())
    assert row["feature_set_version"] == FEATURE_SET_VERSION == 3
    assert row["deribit_enabled"] is False
    assert row["deribit_missing_reason"] == "DERIBIT_DISABLED"
    assert "deribit_dvol" in row and row["deribit_dvol"] is None  # key present, value None


def test_feature_row_merges_deribit_extra():
    snap = normalize(_raw(), recv_ms=4_900_000)
    de = deribit_feature_fields(snapshot=snap, as_of_ms=5_000_000, enabled=True)
    row = build_feature_row(
        _norm_ob(), as_of_ms=5_000_000, reference_price=72000.0, sigma_per_sqrt_s=0.0005,
        start_reference=71900.0, fee_model=KalshiFeeModel(), deribit_extra=de)
    assert row["deribit_enabled"] is True and row["deribit_used"] is True
    assert row["deribit_dvol"] == 55.0 and row["deribit_atm_iv"] == 52.0


# --------------------------------------------------------------------------- #
# Train dry-run reporting
# --------------------------------------------------------------------------- #
def _frow(tk, *, as_of, close, **extra):
    row = {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
           "has_start_reference": True, "seconds_to_close": 120, "book_ok": True,
           "as_of_ms": as_of, "close_ms": close, "yes_ask": 0.42, "no_ask": 0.60,
           "feature_set_version": 3}
    row.update(extra)
    return row


def test_train_dry_run_reports_deribit_and_still_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    # Candidate-feature inclusion now also requires the explicit include flag.
    monkeypatch.setenv("DERIBIT_INCLUDE_IN_MODEL_FEATURES", "true")
    from btc5m.venues.kalshi.train_prep import train_dry_run
    base = 1_780_000_000_000
    feats, labels = [], []
    for w in range(3):
        close = base + w * 15 * 60 * 1000 + 15 * 60 * 1000
        for i in range(4):
            feats.append(_frow(f"KX-{w}", as_of=close - (200 - i) * 1000, close=close,
                               deribit_available=True, deribit_used=True, deribit_stale=False,
                               deribit_dvol=55.0))
        labels.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL",
                       "label_yes_resolved": w % 2})
    (tmp_path / "features").mkdir()
    (tmp_path / "labels").mkdir()
    (tmp_path / "features" / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in feats) + "\n", encoding="utf-8")
    (tmp_path / "labels" / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in labels) + "\n", encoding="utf-8")

    r = train_dry_run(load_config(mode="paper"), series="KXBTC15M")
    assert r["trained"] is False and r["train_allowed"] is False  # gate still blocks
    de = r["deribit"]
    assert de["enabled_in_config"] is True
    assert de["include_in_model_features"] is True
    assert de["columns_present"] is True
    assert de["rows_with_deribit_used"] == 12
    assert de["selected_for_model_features"] is True
    assert de["will_be_in_candidate_feature_group"] is True
    assert de["candidate_feature_group_status"] == "INCLUDED"
    assert de["selected_candidate_feature_count"] > 0
    assert "deribit_dvol" in de["missingness_by_deribit_column"]
    assert "3" in r["feature_version_counts"]
    assert "deribit_dvol" in r["column_missingness"]


# --------------------------------------------------------------------------- #
# Source health
# --------------------------------------------------------------------------- #
def _write_deribit_norm(tmp_path, recv_ms):
    from datetime import datetime, timezone
    norm = tmp_path / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    row = {"stream": "deribit_btc",
           "event": {"source": "deribit", "recv_ms": recv_ms, "deribit_index_price": 72000.0,
                     "deribit_dvol": 55.0, "deribit_near_expiry_iv": 52.0}}
    (norm / f"deribit_btc-{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_source_health_deribit_disabled_optional(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    from btc5m.venues.kalshi.source_health import assess_source_health
    de = next(s for s in assess_source_health(load_config(mode="paper"))["sources"]
              if s["source"] == "deribit")
    assert de["enabled"] is False and de["required"] is False
    assert de["enabled_by_config"] is False and de["implemented"] is True
    assert de["optional"] is True
    assert de["status"] == "disabled"                       # no rows in this tmp dir
    assert de["historical_rows_present"] is False
    assert de["disabled_by_config_but_rows_present"] is False
    assert de["selected_for_model_features"] is False
    assert "disabled" in de["recommendation"].lower()


def test_source_health_deribit_uses_loose_stale_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    from btc5m.timeutils import now_ms
    # 120s old: would be "stale" at the 60s generic threshold, but Deribit's
    # threshold is 180s, so it must NOT be stale.
    _write_deribit_norm(tmp_path, now_ms() - 120_000)
    from btc5m.venues.kalshi.source_health import assess_source_health
    de = next(s for s in assess_source_health(load_config(mode="paper"))["sources"]
              if s["source"] == "deribit")
    assert de["stale_threshold_ms"] == 180_000
    assert de["stale"] is False
    assert de["status"] == "implemented"
    assert de["joined_into_feature_rows"] is True
    assert de["historical_rows_present"] is True
    assert de["latest_values"].get("deribit_dvol") == 55.0
    assert "fresh" in de["recommendation"]


def test_source_health_disabled_but_historical_rows_present(tmp_path, monkeypatch):
    """The original contradiction: DISABLED yet rows present must read clearly."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    from btc5m.timeutils import now_ms
    _write_deribit_norm(tmp_path, now_ms() - 30_000)   # fresh-ish but DISABLED
    from btc5m.venues.kalshi.source_health import assess_source_health
    de = next(s for s in assess_source_health(load_config(mode="paper"))["sources"]
              if s["source"] == "deribit")
    assert de["enabled_by_config"] is False and de["implemented"] is True
    assert de["historical_rows_present"] is True
    assert de["disabled_by_config_but_rows_present"] is True
    assert de["status"] == "disabled_historical_rows_present"
    assert de["selected_for_model_features"] is False
    assert de["joined_into_feature_rows"] is False
    assert "historical" in de["recommendation"].lower()


def test_source_health_enabled_but_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    from btc5m.timeutils import now_ms
    _write_deribit_norm(tmp_path, now_ms() - 400_000)  # > 180s -> stale
    from btc5m.venues.kalshi.source_health import assess_source_health
    de = next(s for s in assess_source_health(load_config(mode="paper"))["sources"]
              if s["source"] == "deribit")
    assert de["enabled_by_config"] is True
    assert de["stale"] is True
    assert de["status"] == "enabled_stale"
    assert de["missing_reason"] == "DERIBIT_STALE"
    assert "continues without Deribit" in de["recommendation"]


# --------------------------------------------------------------------------- #
# Recording (read-only, mocked client; no live credentials)
# --------------------------------------------------------------------------- #
def test_record_deribit_writes_raw_and_normalized(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.setattr(DeribitClient, "fetch_all", lambda self: _raw())
    from btc5m.cli import main
    assert main(["record-deribit", "--currency", "BTC", "--seconds", "0"]) == 0
    raw = list((tmp_path / "raw").glob("deribit_btc-*.jsonl"))
    norm = list((tmp_path / "normalized").glob("deribit_btc-*.jsonl"))
    assert raw and norm, "record-deribit must write raw + normalized files"
    ev = json.loads(norm[0].read_text(encoding="utf-8").splitlines()[0])["event"]
    assert ev["deribit_dvol"] == 55.0 and ev["deribit_atm_iv"] == 52.0


def test_record_deribit_honors_record_toggles(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.setenv("DERIBIT_RECORD_RAW", "false")        # suppress raw...
    monkeypatch.setenv("DERIBIT_RECORD_NORMALIZED", "true")  # ...keep normalized
    monkeypatch.setattr(DeribitClient, "fetch_all", lambda self: _raw())
    from btc5m.cli import main
    assert main(["record-deribit", "--currency", "BTC", "--seconds", "0"]) == 0
    assert not list((tmp_path / "raw").glob("deribit_btc-*.jsonl"))         # raw suppressed
    assert list((tmp_path / "normalized").glob("deribit_btc-*.jsonl"))     # normalized written


# --------------------------------------------------------------------------- #
# Model dataset: column presence vs candidate-feature SELECTION
# --------------------------------------------------------------------------- #
def _write_dataset_fixture(tmp_path):
    base = 1_780_000_000_000
    feats, labels = [], []
    for w in range(3):
        close = base + w * 15 * 60 * 1000 + 15 * 60 * 1000
        for i in range(4):
            feats.append(_frow(f"KX-{w}", as_of=close - (200 - i) * 1000, close=close,
                               deribit_available=True, deribit_used=True, deribit_stale=False,
                               deribit_dvol=55.0))
        labels.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL",
                       "label_yes_resolved": w % 2})
    (tmp_path / "features").mkdir()
    (tmp_path / "labels").mkdir()
    (tmp_path / "features" / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in feats) + "\n", encoding="utf-8")
    (tmp_path / "labels" / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in labels) + "\n", encoding="utf-8")


def test_dataset_columns_present_but_excluded_when_not_included(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")                          # enabled source...
    monkeypatch.delenv("DERIBIT_INCLUDE_IN_MODEL_FEATURES", raising=False)  # ...but NOT included
    _write_dataset_fixture(tmp_path)
    from btc5m.venues.kalshi.model_dataset import build_model_dataset
    ds = build_model_dataset(load_config(mode="paper"), series="KXBTC15M", feature_version="all")
    de = ds["deribit"]
    assert de["columns_present"] is True
    assert de["enabled_in_config"] is True
    assert de["include_in_model_features"] is False
    assert de["selected_for_model_features"] is False
    assert ds["deribit_included"] is False
    assert de["candidate_feature_group_status"] == "EXCLUDED_BY_CONFIG"
    # Deribit candidate columns are DROPPED from the training feature list (not silent).
    assert "deribit_dvol" not in ds["training_features"]
    # ...and the gate is unaffected by Deribit (3 windows present either way).
    assert ds["distinct_windows"] == 3


def test_dataset_included_when_enabled_and_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DERIBIT_ENABLED", "true")
    monkeypatch.setenv("DERIBIT_INCLUDE_IN_MODEL_FEATURES", "true")
    _write_dataset_fixture(tmp_path)
    from btc5m.venues.kalshi.model_dataset import build_model_dataset
    ds = build_model_dataset(load_config(mode="paper"), series="KXBTC15M", feature_version="all")
    de = ds["deribit"]
    assert ds["deribit_included"] is True
    assert de["selected_for_model_features"] is True
    assert de["candidate_feature_group_status"] == "INCLUDED"
    assert de["selected_candidate_feature_count"] > 0
    assert "deribit_dvol" in ds["training_features"]


def test_dataset_disabled_does_not_block_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DERIBIT_ENABLED", raising=False)
    _write_dataset_fixture(tmp_path)
    from btc5m.venues.kalshi.model_dataset import build_model_dataset
    ds = build_model_dataset(load_config(mode="paper"), series="KXBTC15M", feature_version="all")
    assert ds["deribit"]["candidate_feature_group_status"] == "EXCLUDED_BY_CONFIG"
    assert ds["distinct_windows"] == 3        # Deribit disabled never reduces the gate
