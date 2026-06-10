from btc5m.config import load_config
from btc5m.execution.live_kalshi import LiveKalshiExecutionAdapter
from btc5m.notifications import build_notifier
from btc5m.notifications.noop import NoopNotifier
from btc5m.schemas import Order, OrderSide, Outcome


def _order():
    return Order(contract_id="C", outcome=Outcome.YES, side=OrderSide.BUY, price=0.5, size=10)


def test_live_adapter_refuses_by_default():
    cfg = load_config(mode="paper")  # not live, kill switch on, no creds
    adapter = LiveKalshiExecutionAdapter(cfg)
    fill = adapter.submit(_order(), None)
    assert fill.get("status") == "rejected"
    assert fill.get("live_submission_allowed") is False


def test_live_blockers_listed():
    cfg = load_config(mode="paper")
    adapter = LiveKalshiExecutionAdapter(cfg)
    blockers = adapter.preflight(_order(), None)
    assert blockers  # must be non-empty with safe defaults


def test_notifier_falls_back_to_noop_without_pushover():
    cfg = load_config(mode="paper")
    # No Pushover creds / not enabled by default.
    assert not cfg.notifications.pushover_configured
    notifier = build_notifier(cfg)
    assert isinstance(notifier, NoopNotifier)
    assert notifier.watch("test message") is True
    assert notifier.paper_candidate("BUY YES @ 0.57 | model 0.63 | net edge +3.5c") is True
    assert notifier.eod("42 signals | 9 paper fills | net +$12.40 paper | hit 56%") is True


def test_pushover_not_configured_unless_enabled_and_creds_present():
    cfg = load_config(mode="paper")
    n = cfg.notifications
    # token+key but NOT enabled -> still not configured
    n.pushover_enabled = False
    n.pushover_app_token = "tok"
    n.pushover_user_key = "usr"
    assert not n.pushover_configured
    # enabled but missing a cred -> not configured
    n.pushover_enabled = True
    n.pushover_user_key = None
    assert not n.pushover_configured
    # enabled + both creds -> configured, and build_notifier returns PushoverNotifier
    n.pushover_user_key = "usr"
    assert n.pushover_configured
    from btc5m.notifications.pushover import PushoverNotifier

    assert isinstance(build_notifier(cfg), PushoverNotifier)


def test_no_active_pusher_symbols_remain():
    import btc5m.notifications as notif
    import btc5m.config as cfgmod

    assert not hasattr(notif, "PusherNotifier")
    # NotificationConfig no longer exposes pusher_* fields.
    fields = cfgmod.NotificationConfig().__dict__
    assert not any(k.startswith("pusher_") or k.startswith("beams_") for k in fields)
    assert "pushover_app_token" in fields


def test_config_live_not_permitted_by_default():
    cfg = load_config(mode="paper")
    assert not cfg.live_permitted
    assert cfg.live_blockers()
