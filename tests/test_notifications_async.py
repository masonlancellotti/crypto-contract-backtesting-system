"""Latency-safe notifications + explanations.

Covers: bounded async queue (enqueue-fast / background send / Noop fallback /
timeout-safe / drop+coalesce / high-priority preserved / no secrets), hot-path
safety (decision functions never send / explanations are post-decision), the
explanation templates, and the ops commands. All offline; no network, no orders.
"""

import inspect
import json

from btc5m.config import load_config
from btc5m.notifications.base import Notification
from btc5m.notifications.noop import NoopNotifier
from btc5m.notifications.explanations import (
    EXPLANATION_BACKEND, DecisionExplanationInput, explain,
)
from btc5m.notifications.queue import (
    NotificationQueue, Priority, build_notification_queue, classify_priority,
)


def _cfg():
    return load_config(mode="paper")


class _FailNotifier(NoopNotifier):
    def send(self, note):  # simulates a Pushover timeout/exception path
        raise TimeoutError("simulated send timeout")


class _FalseNotifier(NoopNotifier):
    def send(self, note):
        return False


# --------------------------------------------------------------------------- #
# Queue: enqueue is fast and non-blocking
# --------------------------------------------------------------------------- #
def test_enqueue_is_fast_and_bounded():
    q = NotificationQueue(NoopNotifier(_cfg()), start_worker=False, maxsize=10_000,
                          coalesce_low=False)
    for i in range(2000):
        assert q.enqueue(Notification("PAPER_CANDIDATE", "t", f"b{i}"),
                         priority=Priority.HIGH) is True
    h = q.health()
    assert h["enqueue_latency_ms"]["n"] == 2000
    assert h["enqueue_latency_ms"]["p95"] < 1.0   # sub-millisecond enqueue
    q.close()


def test_background_worker_sends_via_noop():
    q = build_notification_queue(_cfg())  # Noop by default, async worker on
    assert q.enqueue(Notification("PAPER_CANDIDATE", "t", "BUY YES @ 0.57")) is True
    assert q.flush(timeout=3.0) is True
    h = q.health()
    assert h["sent"] >= 1 and h["failed"] == 0
    q.close()


def test_noop_fallback_when_pushover_missing():
    cfg = _cfg()
    assert not cfg.notifications.pushover_configured
    q = build_notification_queue(cfg)
    assert q.provider == "NoopNotifier"
    q.close()


def test_send_failure_is_safe_and_counted():
    # An exception inside send must never crash; it is recorded as a sanitized error.
    q = NotificationQueue(_FailNotifier(_cfg()), maxsize=50)
    q.enqueue(Notification("ERROR", "t", "boom"), priority=Priority.HIGH)
    q.flush(timeout=3.0)
    h = q.health()
    assert h["sent"] == 0 and h["failed"] >= 1
    assert h["last_error"] == "TimeoutError"   # type only — no payload/secret
    q.close()


def test_send_returning_false_counts_failed():
    q = NotificationQueue(_FalseNotifier(_cfg()))
    q.enqueue(Notification("PAPER_FILLED", "t", "x"), priority=Priority.HIGH)
    q.flush(timeout=3.0)
    assert q.health()["failed"] >= 1
    q.close()


def test_async_disabled_suppresses_without_blocking():
    q = NotificationQueue(NoopNotifier(_cfg()), async_enabled=False, start_worker=False)
    assert q.enqueue(Notification("WATCH", "t", "x")) is False
    assert q.health()["suppressed_async_disabled"] >= 1
    q.close()


# --------------------------------------------------------------------------- #
# Bounded behavior: drop low / coalesce / preserve high
# --------------------------------------------------------------------------- #
def test_full_queue_drops_low_priority():
    q = NotificationQueue(NoopNotifier(_cfg()), maxsize=3, coalesce_low=False,
                          drop_low_priority_when_full=True, start_worker=False)
    for i in range(3):
        assert q.enqueue(Notification("REJECTED", "t", f"r{i}"), priority=Priority.LOW)
    assert q.enqueue(Notification("REJECTED", "t", "overflow"), priority=Priority.LOW) is False
    assert q.health()["dropped_by_reason"]["low_full"] >= 1
    q.close()


def test_high_priority_preserved_by_evicting_low():
    q = NotificationQueue(NoopNotifier(_cfg()), maxsize=3, coalesce_low=False,
                          start_worker=False)
    for i in range(3):
        q.enqueue(Notification("REJECTED", "t", f"r{i}"), priority=Priority.LOW)
    assert q.enqueue(Notification("PAPER_CANDIDATE", "t", "important"),
                     priority=Priority.HIGH) is True
    assert len(q._high) >= 1                      # high retained
    assert q.health()["dropped_by_reason"]["low_evicted_for_high"] >= 1
    assert q.depth <= 3                           # still bounded
    q.close()


def test_low_priority_coalesced():
    q = NotificationQueue(NoopNotifier(_cfg()), maxsize=100, coalesce_low=True,
                          start_worker=False)
    for _ in range(10):
        q.enqueue(Notification("WATCH", "t", "same"), priority=Priority.LOW)
    h = q.health()
    assert h["coalesced"] == 9          # 1 queued, 9 folded into a count
    assert q.depth == 1
    q.close()


def test_priority_classification():
    assert classify_priority("PAPER_CANDIDATE") is Priority.HIGH
    assert classify_priority("WATCH") is Priority.LOW
    assert classify_priority("REJECTED") is Priority.LOW
    assert classify_priority("EOD_SUMMARY") is Priority.MEDIUM  # unmapped -> medium


def test_no_secrets_in_health_even_when_pushover_configured():
    cfg = _cfg()
    cfg.notifications.pushover_enabled = True
    cfg.notifications.pushover_app_token = "SECRET_TOKEN_123"
    cfg.notifications.pushover_user_key = "SECRET_USER_456"
    q = build_notification_queue(cfg, start_worker=False)
    blob = json.dumps(q.health(), default=str)
    assert "SECRET_TOKEN_123" not in blob and "SECRET_USER_456" not in blob
    q.close()


# --------------------------------------------------------------------------- #
# Explanations are background generation in the worker
# --------------------------------------------------------------------------- #
def test_worker_appends_explanation_to_body():
    captured = {}

    class _Capture(NoopNotifier):
        def send(self, note):
            captured["body"] = note.body
            return True

    q = NotificationQueue(_Capture(_cfg()), explain_fn=explain)
    q.enqueue(
        Notification("PAPER_CANDIDATE", "t", "BUY YES @ 0.57"),
        priority=Priority.HIGH,
        explanation_input={"decision_state": "PAPER_CANDIDATE", "side": "BUY_YES",
                           "net_edge": 0.032, "reason_codes": ["NET_EDGE_OK"]})
    q.flush(timeout=3.0)
    assert "Paper candidate" in captured.get("body", "")
    q.close()


# --------------------------------------------------------------------------- #
# Hot-path safety: decision functions never notify / explain
# --------------------------------------------------------------------------- #
def test_hot_decision_functions_do_not_send_or_explain():
    from btc5m.venues.kalshi.low_latency_runtime import evaluate_ev, build_decision_event
    from btc5m.venues.kalshi.paper import decide_kalshi
    src = (inspect.getsource(evaluate_ev) + inspect.getsource(build_decision_event)
           + inspect.getsource(decide_kalshi))
    for forbidden in ("build_notifier", "notifier", ".send(", ".enqueue(",
                      "NotificationQueue", "urlopen", "explain(", ".paper_candidate(", ".eod("):
        assert forbidden not in src, f"hot path must not contain {forbidden!r}"


def test_pure_decision_modules_do_not_import_notifications():
    from btc5m.venues.kalshi import policy, scorer, hotpath_state
    for mod in (policy, scorer, hotpath_state):
        assert "notifications" not in inspect.getsource(mod)


def test_explanation_is_post_decision_and_offline():
    # No LLM/API backend; explanation is template-only and flagged post-decision.
    assert EXPLANATION_BACKEND == "template"
    inp = DecisionExplanationInput(timestamp_ms=1, series="KXBTC15M",
                                   decision_state="PAPER_CANDIDATE")
    assert inp.generated_after_decision is True
    assert inp.live_submission_allowed is False
    # explain() requires a decided state to exist (i.e. runs after the decision).
    assert "Paper candidate" in explain(
        DecisionExplanationInput(timestamp_ms=1, series="KXBTC15M",
                                 decision_state="PAPER_CANDIDATE", selected_side="BUY_YES",
                                 net_edge=0.031))


# --------------------------------------------------------------------------- #
# Explanation templates
# --------------------------------------------------------------------------- #
def test_explanation_templates_from_reason_codes():
    def ex(state, reasons, **kw):
        return explain(DecisionExplanationInput(timestamp_ms=1, series="KXBTC15M",
                                                decision_state=state, reason_codes=reasons, **kw))

    assert "closed" in ex("SKIPPED", ["MARKET_CLOSED"]).lower()
    assert "pre-open" in ex("SKIPPED", ["OUTSIDE_DECISION_WINDOW"]).lower()
    assert "not open" in ex("SKIPPED", ["MARKET_NOT_OPEN"]).lower()
    assert "empty/incomplete" in ex("REJECTED", ["EMPTY_OR_INCOMPLETE_BOOK"]).lower()
    below = ex("WATCH", ["EDGE_BELOW_MIN(1.1c<2.0c)"], selected_side="BUY_YES",
               net_edge=0.011, min_net_edge_cents=2.0)
    assert "below" in below.lower() and "+1.1c" in below
    mr = ex("MANUAL_REVIEW", ["UNCALIBRATED_MODEL"], selected_side="BUY_YES", net_edge=0.032)
    assert "uncalibrated" in mr.lower()
    # Live submission disabled is always surfaced.
    assert "Live submission disabled." in ex("PAPER_CANDIDATE", ["NET_EDGE_OK"], net_edge=0.03)


def test_explanation_handles_missing_fields():
    # Empty/sparse input must not raise.
    assert isinstance(explain({}), str)
    assert isinstance(explain(DecisionExplanationInput(timestamp_ms=0, series="X")), str)
    assert "n/a" in explain(DecisionExplanationInput(
        timestamp_ms=0, series="X", decision_state="WATCH", reason_codes=["EDGE_BELOW_MIN"]))


# --------------------------------------------------------------------------- #
# Ops commands
# --------------------------------------------------------------------------- #
def test_notification_health_command(capsys):
    from btc5m.cli import _COMMANDS
    assert "notification-health" in _COMMANDS and "kalshi-notification-health" in _COMMANDS
    import argparse
    args = argparse.Namespace(samples=200, json=False)
    rc = _COMMANDS["notification-health"](_cfg(), args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "notification-health" in out and "enqueue latency" in out
    assert "blocking_prevented" in out


def test_latency_benchmark_includes_notify_enqueue():
    from btc5m.venues.kalshi.low_latency_runtime import run_latency_benchmark
    res = run_latency_benchmark(_cfg(), series="KXBTC15M", samples=200, emit=lambda *_: None)
    assert "notify_enqueue" in res["latency"]
    assert res["latency"]["notify_enqueue"]["count"] == 200
    assert "notify_enqueue_overhead_p99_ms" in res
