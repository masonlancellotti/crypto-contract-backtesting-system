"""Tests for the sealed holdout vault: disjointness, forward block, fingerprint, round-trip."""

import pytest

from btc5m.discovery import holdout


def _windows(n=80):
    return [{"ticker": f"KXBTC15M-{i:03d}", "close_ms": 1000 + i * 100, "label": i % 2}
            for i in range(n)]


def test_search_and_holdout_disjoint_and_cover():
    wins = _windows(80)
    v = holdout.HoldoutVault.build(wins, holdout_fraction=0.25, seed=1)
    s, h = set(v.search_keys), set(v.holdout_keys)
    assert not (s & h)                                  # disjoint
    assert v.counts["n_search"] + v.counts["n_holdout"] + v.counts["n_embargoed_out"] == 80


def test_forward_block_is_most_recent():
    wins = _windows(80)
    v = holdout.HoldoutVault.build(wins, holdout_fraction=0.25, forward_share=1.0, seed=1)
    # with forward_share=1.0 the entire holdout is the most-recent block
    recent = {f"KXBTC15M-{i:03d}" for i in range(80 - v.counts["n_forward"], 80)}
    assert recent.issubset(set(v.holdout_keys))


def test_fingerprint_detects_data_shift():
    wins = _windows(80)
    v = holdout.HoldoutVault.build(wins, seed=1)
    assert v.verify(wins)
    shifted = _windows(80)
    shifted[0]["label"] = 1 - shifted[0]["label"]       # flip one label
    assert not v.verify(shifted)


def test_save_load_roundtrip(tmp_path):
    wins = _windows(80)
    v = holdout.HoldoutVault.build(wins, seed=3)
    p = str(tmp_path / "vault" / "v.json")
    v.save(p)
    v2 = holdout.HoldoutVault.load(p)
    assert v2.fingerprint == v.fingerprint
    assert v2.search_keys == v.search_keys
    assert v2.holdout_keys == v.holdout_keys


def test_split_rows_routes_to_correct_set():
    wins = _windows(80)
    v = holdout.HoldoutVault.build(wins, seed=1)
    rows = [{"ticker": w["ticker"], "x": 1} for w in wins]
    s_rows = v.split_rows(rows, which="search")
    h_rows = v.split_rows(rows, which="holdout")
    assert {r["ticker"] for r in s_rows} <= set(v.search_keys)
    assert {r["ticker"] for r in h_rows} <= set(v.holdout_keys)
    assert not ({r["ticker"] for r in s_rows} & {r["ticker"] for r in h_rows})


def test_too_few_windows_raises():
    with pytest.raises(ValueError):
        holdout.HoldoutVault.build(_windows(10))
