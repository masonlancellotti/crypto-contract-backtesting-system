from btc5m.config import load_config
from btc5m.execution.risk import RiskContext, RiskManager
from btc5m.schemas import BookLevel, ContractMeta, Order, OrderBook, OrderSide, Outcome
from btc5m.timeutils import now_ms


def _order(size=10):
    return Order(
        contract_id="C", outcome=Outcome.YES, side=OrderSide.BUY, price=0.5, size=size
    )


def _good_ctx():
    now = now_ms()
    book = OrderBook(
        contract_id="C",
        outcome=Outcome.YES,
        bids=[BookLevel(0.49, 100)],
        asks=[BookLevel(0.51, 100)],
        ts_ms=now,
        recv_ms=now,
    )
    meta = ContractMeta(
        contract_id="C", title="t", asset="BTC", line=60000.0, expiry_ms=now + 300_000
    )
    return RiskContext(
        book=book, meta=meta, calibration_ts_ms=now, clock_skew_ms=0, last_feed_event_ms=now
    )


def _permissive_config():
    cfg = load_config(mode="paper")
    cfg.kill_switch_enabled = False
    cfg.risk.max_order_size = 100
    cfg.risk.max_position_per_contract = 100
    cfg.risk.max_daily_loss = 1000
    cfg.risk.max_open_risk = 1000
    cfg.risk.max_trades_per_hour = 100
    return cfg


def test_kill_switch_blocks_by_default():
    cfg = load_config(mode="paper")  # kill switch on, limits unset
    rm = RiskManager(cfg)
    decision = rm.evaluate(_order(), _good_ctx())
    assert not decision.approved
    assert any("kill switch" in r for r in decision.reasons)


def test_all_clear_when_permissive_and_healthy():
    rm = RiskManager(_permissive_config())
    decision = rm.evaluate(_order(), _good_ctx())
    assert decision.approved, decision.reasons


def test_oversize_order_blocked():
    rm = RiskManager(_permissive_config())
    decision = rm.evaluate(_order(size=999), _good_ctx())
    assert not decision.approved
    assert any("order size" in r for r in decision.reasons)


def test_stale_quote_blocked():
    rm = RiskManager(_permissive_config())
    ctx = _good_ctx()
    ctx.book.ts_ms = now_ms() - 999_999  # very stale
    decision = rm.evaluate(_order(), ctx)
    assert not decision.approved
    assert any("stale quote" in r for r in decision.reasons)


def test_crossed_book_blocked():
    rm = RiskManager(_permissive_config())
    ctx = _good_ctx()
    ctx.book.bids = [BookLevel(0.60, 10)]
    ctx.book.asks = [BookLevel(0.59, 10)]
    decision = rm.evaluate(_order(), ctx)
    assert not decision.approved
    assert any("crossed" in r for r in decision.reasons)


def test_missing_calibration_blocked():
    rm = RiskManager(_permissive_config())
    ctx = _good_ctx()
    ctx.calibration_ts_ms = None
    decision = rm.evaluate(_order(), ctx)
    assert not decision.approved
    assert any("calibration" in r for r in decision.reasons)


def test_clock_skew_blocked():
    rm = RiskManager(_permissive_config())
    ctx = _good_ctx()
    ctx.clock_skew_ms = 999_999
    decision = rm.evaluate(_order(), ctx)
    assert not decision.approved
    assert any("clock skew" in r for r in decision.reasons)
