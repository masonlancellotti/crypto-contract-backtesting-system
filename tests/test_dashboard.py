"""Route + chart-data tests for the keyless research dashboard.

Skipped cleanly when FastAPI is not installed (core stdlib suite stays green);
CI installs the `dashboard`/`dev` extras so these run there. Hermetic: the app
reads committed artifacts only — no network, no keys.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from btc5m.dashboard.app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_all_api_routes_ok(client):
    for path in ["/api/health", "/api/overview", "/api/ledger",
                 "/api/calibration", "/api/backtest", "/api/replay"]:
        assert client.get(path).status_code == 200, path


def test_static_frontend_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/styles.css").status_code == 200
    assert "app.js" in client.get("/").text
    assert client.get("/app.js").status_code == 200


def test_overview_tiles_and_verdicts(client):
    j = client.get("/api/overview").json()
    assert len(j["tiles"]) >= 6
    assert all(t.get("source") for t in j["tiles"])
    assert sum(v["count"] for v in j["verdict_breakdown"]) == 38
    assert j["fees_kill_alpha"]["sample_backtest"]


def test_ledger_endpoint_has_38_legs(client):
    j = client.get("/api/ledger").json()
    assert len(j["legs"]) == 38
    assert j["source_doc"] == "docs/RESEARCH_LEDGER.md"


def test_calibration_market_reliability_is_computed_live(client):
    j = client.get("/api/calibration").json()
    mr = j["market_reliability"]
    assert mr["n"] > 0, "market reliability must be computed from committed sample rows"
    assert 3 <= len(mr["points"]) <= 10
    # market-implied is the best-calibrated series on the sample backtest
    ece = {m["model"]: m["ece"] for m in j["backtest_calibration"]}
    assert ece["market_implied"] == min(ece.values())


def test_backtest_fee_decomposition(client):
    j = client.get("/api/backtest").json()
    models = {m["model"]: m for m in j["models"]}
    assert "distance_time_vol" in models and "microstructure" in models
    # every trained baseline is net-negative after fees; the fee burden is positive
    for name in ("distance_time_vol", "microstructure"):
        assert models[name]["net_pnl"] < 0
        assert models[name]["fee_burden"] > 0
    assert j["source"].endswith("kalshi_baseline_backtest.md")


def test_replay_window_is_a_real_settled_window(client):
    j = client.get("/api/replay").json()
    frames = j["frames"]
    assert len(frames) > 100, "replay needs a dense, animatable window"
    # time is monotonic and ends at/after settlement
    times = [f["t_ms"] for f in frames]
    assert times == sorted(times)
    assert any(f["phase"] == "settled" for f in frames)
    assert j["meta"]["official_result"] in ("yes", "no")
    # probabilities live in [0,1]
    for f in frames:
        for k in ("p_market", "p_model"):
            if f[k] is not None:
                assert 0.0 <= f[k] <= 1.0
