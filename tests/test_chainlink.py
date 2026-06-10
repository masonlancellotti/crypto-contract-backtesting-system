"""Offline tests for the Chainlink Data Streams client (gated OFFICIAL source)."""

from btc5m.data.chainlink import ChainlinkStreamsClient


def test_not_configured_by_default(monkeypatch):
    for v in ("CHAINLINK_STREAMS_API_KEY", "CHAINLINK_STREAMS_API_SECRET", "CHAINLINK_BTC_FEED_ID"):
        monkeypatch.delenv(v, raising=False)
    cl = ChainlinkStreamsClient()
    assert not cl.is_configured
    assert "not configured" in cl.not_configured_reason()
    # price_at returns None (never fakes OFFICIAL) when unconfigured.
    price, detail = cl.price_at(1_700_000_000_000)
    assert price is None
    assert "not configured" in detail["reason"]


def test_is_configured_with_env(monkeypatch):
    monkeypatch.setenv("CHAINLINK_STREAMS_API_KEY", "k")
    monkeypatch.setenv("CHAINLINK_STREAMS_API_SECRET", "s")
    monkeypatch.setenv("CHAINLINK_BTC_FEED_ID", "0xfeed")
    assert ChainlinkStreamsClient().is_configured


def test_signature_is_deterministic_hmac():
    sig1 = ChainlinkStreamsClient.build_signature("GET", "/x", b"", "key", "secret", 1234)
    sig2 = ChainlinkStreamsClient.build_signature("GET", "/x", b"", "key", "secret", 1234)
    assert sig1 == sig2
    assert len(sig1) == 64  # hex sha256
    # Changing any input changes the signature.
    assert sig1 != ChainlinkStreamsClient.build_signature("GET", "/x", b"", "key", "secret", 1235)
    assert sig1 != ChainlinkStreamsClient.build_signature("GET", "/y", b"", "key", "secret", 1234)


def test_report_to_price_scaled_int():
    # 73850.5 * 1e18
    raw = {"report": {"benchmarkPrice": str(int(73850.5 * 10**18))}}
    assert abs(ChainlinkStreamsClient.report_to_price(raw) - 73850.5) < 1e-6


def test_report_to_price_hex():
    val = hex(int(60000 * 10**18))
    assert abs(ChainlinkStreamsClient.report_to_price({"price": val}) - 60000.0) < 1e-6


def test_report_to_price_none_when_absent():
    assert ChainlinkStreamsClient.report_to_price({"report": {}}) is None
