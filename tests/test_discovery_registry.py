"""Tests for the trial registry: cumulative multiple-testing budget across runs."""

from btc5m.discovery.registry import TrialRegistry


def test_cumulative_trials_sums_across_runs(tmp_path):
    reg = TrialRegistry(str(tmp_path / "reg.jsonl"))
    reg.log_run(data_fingerprint="abc", space_id="binary_v1", n_trials=100)
    reg.log_run(data_fingerprint="abc", space_id="binary_v1", n_trials=250)
    reg.log_run(data_fingerprint="abc", space_id="other", n_trials=999)
    assert reg.cumulative_trials(space_id="binary_v1") == 350
    assert reg.cumulative_trials(space_id="binary_v1", data_fingerprint="abc") == 350
    assert reg.cumulative_trials(space_id="binary_v1", data_fingerprint="zzz") == 0
    assert reg.cumulative_trials(space_id="other") == 999


def test_runs_roundtrip_and_candidates(tmp_path):
    reg = TrialRegistry(str(tmp_path / "reg.jsonl"))
    rec = reg.log_run(data_fingerprint="f1", space_id="s", n_trials=10,
                      candidates=[{"name": "c1", "dsr": 0.97}], meta={"note": "hi"})
    runs = reg.runs()
    assert len(runs) == 1
    assert runs[0]["candidates"][0]["name"] == "c1"
    assert runs[0]["meta"]["note"] == "hi"
    assert "run_id" in rec


def test_empty_registry_is_zero(tmp_path):
    reg = TrialRegistry(str(tmp_path / "none.jsonl"))
    assert reg.runs() == []
    assert reg.cumulative_trials(space_id="anything") == 0
