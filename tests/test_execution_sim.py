from btc5m.backtest.execution_sim import simulate_fill, to_fill
from btc5m.execution.base import ExecutionContext
from btc5m.execution.paper import PaperExecutionAdapter
from btc5m.config import load_config
from btc5m.schemas import BookLevel, Order, OrderSide, Outcome, RiskDecision


def _asks():
    return [BookLevel(0.57, 100), BookLevel(0.58, 200)]


def _order(size=100):
    return Order(
        contract_id="C", outcome=Outcome.YES, side=OrderSide.BUY, price=0.57, size=size
    )


def test_fill_never_assumes_midpoint():
    # Taker BUY consuming the asks pays the ask, not the (lower) midpoint.
    res = simulate_fill(_order(100), _asks())
    assert res.fully_filled
    assert res.avg_price == 0.57  # best ask, above any midpoint


def test_walks_book_for_large_order():
    res = simulate_fill(_order(150), _asks())
    # 100 @ 0.57 + 50 @ 0.58 = 57 + 29 = 86 over 150
    assert abs(res.avg_price - (86.0 / 150.0)) < 1e-9
    assert res.fully_filled


def test_partial_fill_when_thin():
    res = simulate_fill(_order(1000), _asks())
    assert not res.fully_filled
    assert res.filled_size == 300


def test_fees_charged():
    res = simulate_fill(_order(100), _asks(), taker_fee_bps=10)
    assert res.fees > 0


def test_paper_adapter_rejects_when_risk_blocked():
    cfg = load_config(mode="paper")
    adapter = PaperExecutionAdapter(cfg)
    ctx = ExecutionContext(levels=_asks(), risk_decision=RiskDecision.blocked("test block"))
    fill = adapter.submit(_order(), ctx)
    assert fill.status == "rejected"
    assert fill.filled_size == 0


def test_paper_adapter_fills_when_approved():
    cfg = load_config(mode="paper")
    adapter = PaperExecutionAdapter(cfg)
    start = adapter.bankroll
    ctx = ExecutionContext(levels=_asks(), risk_decision=RiskDecision.ok())
    fill = adapter.submit(_order(), ctx)
    assert fill.filled_size == 100
    assert fill.is_paper
    assert adapter.bankroll < start  # cash spent on a BUY
