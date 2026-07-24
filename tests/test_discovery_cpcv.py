"""Tests for combinatorial purged CV: split counts, disjointness, and leakage-safety."""

from math import comb

from btc5m.discovery import cpcv


def test_split_count_matches_combinations():
    splits = list(cpcv.combinatorial_purged_splits(120, n_groups=6, k_test=2, embargo=1))
    assert len(splits) == comb(6, 2)
    assert cpcv.n_cpcv_splits(6, 2) == comb(6, 2)


def test_train_and_test_disjoint_and_embargoed():
    n = 120
    for train, test in cpcv.combinatorial_purged_splits(n, n_groups=6, k_test=2, embargo=2):
        ts = set(test)
        tr = set(train)
        assert not (ts & tr)                      # disjoint
        # no train index within the embargo of any test index (leakage-safety)
        for t in ts:
            for d in (-2, -1, 1, 2):
                assert (t + d) not in tr or not (0 <= t + d < n)
        # all indices accounted for as train, test, or embargoed-out
        assert ts.issubset(range(n)) and tr.issubset(range(n))


def test_embargo_actually_removes_neighbors():
    # with embargo=1 the windows immediately adjacent to a test block must be dropped
    splits = list(cpcv.combinatorial_purged_splits(60, n_groups=6, k_test=1, embargo=1))
    assert splits
    train, test = splits[0]
    lo, hi = min(test), max(test)
    assert (lo - 1) not in set(train)
    assert (hi + 1) not in set(train)


def test_walk_forward_is_causal():
    for train, test in cpcv.purged_walk_forward(100, n_splits=4, embargo=1):
        assert max(train) < min(test)             # train strictly precedes test
        assert min(test) - max(train) > 1         # embargo gap


def test_degenerate_inputs_yield_nothing():
    assert list(cpcv.combinatorial_purged_splits(3, n_groups=6, k_test=2)) == []
    assert list(cpcv.combinatorial_purged_splits(120, n_groups=2, k_test=2)) == []


def test_make_window_panel_groups_and_labels():
    rows = [
        {"ticker": "KXBTC15M-A", "close_ms": 2000, "label_yes_resolved": 1},
        {"ticker": "KXBTC15M-A", "close_ms": 2000, "label_yes_resolved": 1},
        {"ticker": "KXBTC15M-B", "close_ms": 1000, "label_yes_resolved": 0},
        {"ticker": "KXBTC15M-C", "close_ms": 3000},          # no label -> dropped
    ]
    panel = cpcv.make_window_panel(rows)
    assert [w["ticker"] for w in panel] == ["KXBTC15M-B", "KXBTC15M-A"]   # close-sorted
    assert panel[0]["label"] == 0 and panel[1]["label"] == 1
    assert len(panel[1]["rows"]) == 2
