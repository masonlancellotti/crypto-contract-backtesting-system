"""Hermetic tests for `btc5m live-pulse` (WS5).

The --fixture path must render the committed recorded fixture and NEVER touch the
network. We also assert the module cannot issue an order (read-only by design).
"""
import io
import json
import types
from contextlib import redirect_stdout
from pathlib import Path

from btc5m.venues.kalshi import live_pulse

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "sample_data" / "live_pulse_fixture.json"


def test_fixture_committed_and_valid():
    assert FIXTURE.exists(), "committed live-pulse fixture required for hermetic runs"
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    series = data["series"]
    assert len(series) >= 3
    for row in series:
        assert row["series_ticker"].startswith("KX")
        assert row["yes_bid"] is not None and row["yes_ask"] is not None
        assert 0.0 <= row["yes_bid"] <= 1.0


def test_live_pulse_fixture_renders_without_network(monkeypatch):
    # any attempt to construct the network client fails the test
    def _boom(*a, **k):  # noqa: ANN001
        raise AssertionError("live-pulse --fixture must not touch the network")

    monkeypatch.setattr(live_pulse, "_fetch_live", _boom)
    args = types.SimpleNamespace(fixture=True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = live_pulse.run_live_pulse(None, args)
    out = buf.getvalue()
    assert rc == 0
    assert "FIXTURE" in out and "NOT live" in out
    assert "KXBTC15M" in out
    assert "read-only" in out


def test_implied_yes_and_dollar_normalization():
    # cents -> dollars
    assert live_pulse._to_dollars(54) == 0.54
    assert live_pulse._to_dollars(0.54) == 0.54
    assert live_pulse._to_dollars(None) is None
    assert live_pulse._implied_yes({"yes_bid": 0.54, "yes_ask": 0.56}) == 0.55


def test_no_order_surface_exists():
    # the module exposes only read helpers; no submit/cancel/order symbol
    for name in dir(live_pulse):
        assert "submit" not in name.lower()
        assert "cancel" not in name.lower()
