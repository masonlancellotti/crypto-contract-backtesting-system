from btc5m.labels.settlement import (
    ReasonCode,
    label_final_above_strike,
    label_yes_resolved,
    parse_line,
    resolve_settlement,
    settlement_distance,
    validate_expiry,
)
from btc5m.schemas import Comparison, ContractMeta, MarketType
from btc5m.timeutils import now_ms


def _meta(line=60000.0, expiry_ms=None, comparison=Comparison.GT, market_type=MarketType.ABOVE_STRIKE):
    return ContractMeta(
        contract_id="C",
        title="BTC above 60000",
        asset="BTC",
        line=line,
        expiry_ms=expiry_ms if expiry_ms is not None else now_ms() + 300_000,
        resolution_source="https://data.chain.link/streams/btc-usd",
        comparison=comparison,
        market_type=market_type,
    )


# ----- helpers --------------------------------------------------------------
def test_parse_line_valid_and_invalid():
    assert parse_line(60000)[0] == 60000.0
    assert parse_line("60000.5")[0] == 60000.5
    assert parse_line(None) == (None, ReasonCode.MISSING_LINE)
    assert parse_line("abc") == (None, ReasonCode.INVALID_LINE)
    assert parse_line(float("nan"))[1] == ReasonCode.INVALID_LINE
    assert parse_line(float("inf"))[1] == ReasonCode.INVALID_LINE


def test_validate_expiry():
    assert validate_expiry(now_ms() + 1000)
    assert not validate_expiry(0)
    assert not validate_expiry(-5)
    assert not validate_expiry(None)
    assert not validate_expiry("nope")


def test_settlement_distance():
    assert settlement_distance(60050.0, 60000.0) == 50.0
    assert settlement_distance(59950.0, 60000.0) == -50.0


def test_label_final_above_strike_operators():
    # strict GT: tie does NOT clear
    assert label_final_above_strike(60001, 60000, Comparison.GT) is True
    assert label_final_above_strike(60000, 60000, Comparison.GT) is False
    # GTE: tie clears (Polymarket up/down rule)
    assert label_final_above_strike(60000, 60000, Comparison.GTE) is True
    assert label_final_above_strike(59999, 60000, Comparison.GTE) is False


# ----- main resolution ------------------------------------------------------
def test_yes_resolves_true_above_line():
    r = label_yes_resolved(_meta(), 60050.0)
    assert r.yes_resolved == 1
    assert r.reason is ReasonCode.OK
    assert r.settlement_distance == 50.0
    assert r.final_above_strike is True


def test_no_resolves_false_below_line_strict():
    r = label_yes_resolved(_meta(comparison=Comparison.GT), 59950.0)
    assert r.yes_resolved == 0
    assert r.reason is ReasonCode.OK


def test_tie_resolves_per_rule():
    # GT: tie -> NO
    assert label_yes_resolved(_meta(comparison=Comparison.GT), 60000.0).yes_resolved == 0
    # GTE (up/down): tie -> YES (Up)
    up_down = _meta(comparison=Comparison.GTE, market_type=MarketType.UP_DOWN)
    assert label_yes_resolved(up_down, 60000.0).yes_resolved == 1


def test_missing_line_returns_unknown_not_guess():
    r = label_yes_resolved(_meta(line=None), 60050.0)
    assert r.yes_resolved is None
    assert r.reason is ReasonCode.MISSING_LINE


def test_missing_expiry_returns_unknown():
    r = label_yes_resolved(_meta(expiry_ms=0), 60050.0)
    assert r.yes_resolved is None
    assert r.reason is ReasonCode.MISSING_EXPIRY


def test_missing_settlement_price_returns_unknown():
    r = label_yes_resolved(_meta(), None)
    assert r.yes_resolved is None
    assert r.reason is ReasonCode.MISSING_SETTLEMENT_PRICE


def test_explicit_comparison_override():
    # Even if meta says GT, an explicit GTE override flips the tie outcome.
    r = label_yes_resolved(_meta(comparison=Comparison.GT), 60000.0, comparison=Comparison.GTE)
    assert r.yes_resolved == 1


# ----- backward-compatible wrapper -----------------------------------------
def test_resolve_settlement_wrapper():
    assert resolve_settlement(_meta(), 60050.0) == 1
    assert resolve_settlement(_meta(), 59950.0) == 0
    assert resolve_settlement(_meta(line=None), 60050.0) is None
    assert resolve_settlement(_meta(), None) is None
