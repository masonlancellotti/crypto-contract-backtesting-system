from btc5m.labels.settlement import resolve_settlement
from btc5m.schemas import ContractMeta
from btc5m.timeutils import now_ms


def _meta(line=60000.0, expiry_ms=None):
    return ContractMeta(
        contract_id="C",
        title="BTC above 60000",
        asset="BTC",
        line=line,
        expiry_ms=expiry_ms if expiry_ms is not None else now_ms() + 300_000,
        resolution_source="idx",
    )


def test_yes_resolves_true_above_line():
    assert resolve_settlement(_meta(), 60050.0) == 1


def test_no_resolves_false_below_line():
    assert resolve_settlement(_meta(), 59950.0) == 0


def test_missing_metadata_returns_none():
    bad = _meta(line=None)
    assert resolve_settlement(bad, 60050.0) is None


def test_missing_price_returns_none():
    assert resolve_settlement(_meta(), None) is None
