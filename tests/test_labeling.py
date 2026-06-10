import pytest

from btc5m.labels.labeling import LabeledSample, purge_embargo_indices


def _s(as_of, end):
    return LabeledSample(as_of_ms=as_of, label_end_ms=end)


def test_purges_overlapping_samples():
    # Test window [1000, 2000]. 5-min-ish windows of width 300.
    samples = [
        _s(100, 400),     # fully before -> keep
        _s(900, 1200),    # overlaps start of test -> purge
        _s(1400, 1700),   # inside test -> purge
        _s(1900, 2200),   # overlaps end of test -> purge
        _s(2500, 2800),   # fully after, no embargo -> keep
    ]
    safe = purge_embargo_indices(samples, 1000, 2000, embargo_ms=0)
    assert safe == [0, 4]


def test_embargo_drops_samples_just_after_test():
    samples = [
        _s(2100, 2400),   # within embargo (test_end=2000, embargo=500 -> <=2500) -> purge
        _s(2600, 2900),   # just past embargo -> keep
    ]
    safe = purge_embargo_indices(samples, 1000, 2000, embargo_ms=500)
    assert safe == [1]


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        purge_embargo_indices([], 2000, 1000)  # end < start
    with pytest.raises(ValueError):
        purge_embargo_indices([], 1000, 2000, embargo_ms=-1)
    with pytest.raises(ValueError):
        purge_embargo_indices([_s(500, 400)], 1000, 2000)  # label_end before as_of
