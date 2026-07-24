"""The milestone-1 deliverable: the gauntlet rejects pure selection and accepts real edge."""

from btc5m.discovery import selfcheck


def test_negative_control_rejects_lucky_noise():
    neg = selfcheck.negative_control()
    assert neg["rejected"]
    assert neg["dsr"]["deflated_sharpe_ratio"] < 0.95     # best-of-N noise is not significant
    assert neg["pbo"]["pbo"] >= 0.4                       # ~ coin flip OOS


def test_positive_control_accepts_real_edge():
    pos = selfcheck.positive_control()
    assert pos["accepted"]
    assert pos["dsr"]["deflated_sharpe_ratio"] > 0.95
    assert pos["pbo"]["pbo"] < 0.2


def test_run_selfcheck_overall_passes():
    res = selfcheck.run_selfcheck()
    assert res["passed"]
    assert "ADE gauntlet self-validation" in selfcheck.format_report(res)
