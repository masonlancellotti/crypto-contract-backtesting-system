"""Maker-entry feasibility study (READ-ONLY research; never trades).

Every executable backtest in this repo pays the executable ASK (taker). The
bid-ask spread (~2-6c) plus the taker fee (~1-2c) is the same order as every
candidate edge this project has measured — and the residual-alpha verdict is
that no model stably beats the market-implied probability at the ask. The one
untested cost lever is the ENTRY SIDE: resting a limit buy (maker) instead of
crossing the spread.

From recorded normalized order books + OFFICIAL labels this module measures:

1. **Cost decomposition** — spread + taker-fee distribution (what crossing costs).
2. **Conservative passive-fill simulation** — a hypothetical resting YES (or NO)
   buy at the current best bid (``join``) or best bid + improve (``improve``) is
   counted FILLED only when a strictly LATER snapshot of the same window shows
   the same-side executable ask at or below the limit price (the market traded
   through the level). Real fills also happen when a market sell hits a standing
   bid without the quote crossing, so this UNDERCOUNTS fills — and the fills it
   does count are the most adverse subset (price passed through the level).
   Measured maker EV is therefore a CONSERVATIVE LOWER BOUND.
3. **Adverse selection** — realized side-win rate conditional on fill vs the
   limit price, by price/time/rest-horizon bucket:
   ``maker_ev = E[y_side | filled at L] - L - maker_fee(L)``.
4. **Maker-vs-taker comparison** at the same decision points, plus the
   **both-sides (quoting) double-fill** rate and locked-pair economics.

Fees: Kalshi historically charges trading fees to the TAKER; resting (maker)
orders in most series pay none. That is NOT verified here, so the maker fee
rate is a parameter (default 0.0, stamped ASSUMED_ZERO_MAKER_FEE) and the
report includes a sensitivity row where makers pay the full taker schedule.

Safety: read-only research. No orders, no paper, no promotion, no artifact or
manifest mutation. ``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .fees import KalshiFeeModel
from .labels_audit import dedup_labels, load_label_rows
from .readiness import _event, _load_glob

CLOSE_HORIZON = "close"  # sentinel: rest until window close


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _mean(xs: list) -> Optional[float]:
    vals = [x for x in xs if isinstance(x, (int, float))]
    return (sum(vals) / len(vals)) if vals else None


def _median(xs: list) -> Optional[float]:
    vals = sorted(x for x in xs if isinstance(x, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def _pct(x: Optional[float], nd: int = 1) -> str:
    return f"{x * 100.0:.{nd}f}%" if isinstance(x, (int, float)) else "None"


def _f(x: Optional[float], nd: int = 2) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _snapshot_valid(e: dict) -> bool:
    flags = e.get("book_validity_flags") or {}
    if not (flags.get("yes_side_present") and flags.get("no_side_present")):
        return False
    if flags.get("incomplete_book") or flags.get("yes_crossed") or flags.get("no_crossed"):
        return False
    for k in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
        if not isinstance(e.get(k), (int, float)):
            return False
    return True


def load_window_snapshots(config, *, series: str = "KXBTC15M") -> dict[str, list[dict]]:
    """Per-ticker, time-sorted, in-window, valid-book snapshots."""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for raw in _load_glob(config.data_path() / "normalized", "kalshi_orderbook*.jsonl"):
        e = _event(raw)
        tk = e.get("market_ticker")
        if not tk or not str(tk).startswith(series):
            continue
        recv = e.get("recv_ms")
        start = e.get("window_start_ms")
        close = e.get("close_ms")
        if not (isinstance(recv, (int, float)) and isinstance(close, (int, float))):
            continue
        if isinstance(start, (int, float)) and recv < start:
            continue  # pre-window quote: the policy never acts there
        if recv >= close:
            continue  # post-close
        if not _snapshot_valid(e):
            continue
        by_ticker[tk].append(e)
    for tk in by_ticker:
        by_ticker[tk].sort(key=lambda r: r["recv_ms"])
    return dict(by_ticker)


def _official_label_map(config) -> dict[str, int]:
    labels = dedup_labels(load_label_rows(config))
    return {tk: int(lr["label_yes_resolved"]) for tk, lr in labels.items()
            if lr.get("label_source_status") == "OFFICIAL"
            and lr.get("label_yes_resolved") is not None}


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #
def _decision_points(snaps: list[dict]) -> list[int]:
    """Indices of the first valid snapshot in each minute of the window."""
    seen: set[int] = set()
    idxs: list[int] = []
    for i, e in enumerate(snaps):
        start = e.get("window_start_ms") or snaps[0]["recv_ms"]
        minute = int((e["recv_ms"] - start) // 60_000)
        if minute not in seen:
            seen.add(minute)
            idxs.append(i)
    return idxs


def _first_trade_through(snaps: list[dict], from_idx: int, ask_key: str,
                         limit: float) -> Optional[int]:
    """recv_ms of the first strictly-later snapshot whose ask <= limit, else None."""
    for e in snaps[from_idx + 1:]:
        ask = e.get(ask_key)
        if isinstance(ask, (int, float)) and ask <= limit + 1e-9:
            return int(e["recv_ms"])
    return None


def _first_print_fill(prints: list[dict], t0: int, close_ms: Optional[float], side: str,
                      limit: float, *, queue: str) -> Optional[int]:
    """First REAL trade print that fills a resting ``side`` buy at ``limit``.

    Kalshi matching: a taker buying YES consumes resting NO bids and vice versa,
    so a resting YES bid is hit by ``taker_side == "no"`` prints (and NO bids by
    ``taker_side == "yes"``). The print's same-side price is the level reached:
    - ``queue="through"``: price strictly BELOW the limit — deeper levels traded,
      so every resting order at the limit was filled first (certain, queue-free).
    - ``queue="front"``: price at-or-below the limit — assumes front-of-queue at
      the level (optimistic). Truth lies between the two.
    """
    taker = "no" if side == "YES" else "yes"
    price_key = "yes_price" if side == "YES" else "no_price"
    eps = 1e-9
    for p in prints:
        ts = p["created_time_ms"]
        if ts <= t0:
            continue
        if close_ms is not None and ts >= close_ms:
            return None
        if p.get("taker_side") != taker:
            continue
        px = p.get(price_key)
        if not isinstance(px, (int, float)):
            continue
        if (queue == "through" and px < limit - 0.005) or \
           (queue == "front" and px <= limit + eps):
            return int(ts)
    return None


def simulate_maker_entries(config, *, series: str = "KXBTC15M",
                           improve_cents: int = 1,
                           rest_horizons: Optional[list] = None,
                           maker_fee_rate: float = 0.0,
                           fill_model: str = "quote") -> dict:
    """Run the maker-entry simulation over all labeled windows.

    ``fill_model``: "quote" (v1: fill when the quote crosses the limit —
    conservative lower bound), "prints-through" (REAL prints, certain fills:
    price traded strictly through the level), or "prints-front" (REAL prints,
    front-of-queue at the level — optimistic upper bound).
    """
    if fill_model not in ("quote", "prints-through", "prints-front"):
        raise ValueError(f"unknown fill_model: {fill_model!r}")
    horizons = rest_horizons or [60, 180, 300, CLOSE_HORIZON]
    snaps_by_tk = load_window_snapshots(config, series=series)
    labels = _official_label_map(config)
    prints_by_tk: dict[str, list[dict]] = {}
    if fill_model != "quote":
        from .backfill_trades import load_trade_prints
        prints_by_tk = load_trade_prints(config, series=series)
    taker_fees = KalshiFeeModel.from_config(config)
    maker_fees = KalshiFeeModel(rate=maker_fee_rate, status="ASSUMED_ZERO_MAKER_FEE"
                                if maker_fee_rate == 0.0 else "ASSUMED")
    improve = improve_cents / 100.0

    decisions: list[dict] = []   # one per (ticker, decision point, side, mode)
    spreads: list[float] = []
    taker_fee_samples: list[float] = []
    windows_used: set[str] = set()
    double_fill_pairs: list[dict] = []  # both-sides join quotes; per decision point

    for tk, snaps in snaps_by_tk.items():
        y = labels.get(tk)
        if y is None or not snaps:
            continue
        if fill_model != "quote" and not prints_by_tk.get(tk):
            continue  # print-based fills need the window's tape
        prs = prints_by_tk.get(tk, [])
        windows_used.add(tk)
        close_ms = snaps[0].get("close_ms")
        for i in _decision_points(snaps):
            e = snaps[i]
            t0 = int(e["recv_ms"])
            secs_to_close = max(0.0, (close_ms - t0) / 1000.0) if close_ms else None
            spreads.append(max(e["yes_ask"] - e["yes_bid"], e["no_ask"] - e["no_bid"]))
            taker_fee_samples.append(taker_fees.per_contract_fee(e["yes_ask"]))

            pair_fill_t: dict[str, Optional[int]] = {}
            for side, bid_key, ask_key in (("YES", "yes_bid", "yes_ask"),
                                           ("NO", "no_bid", "no_ask")):
                y_side = y if side == "YES" else 1 - y
                ask0 = e[ask_key]
                for mode in ("join", "improve"):
                    limit = e[bid_key] + (improve if mode == "improve" else 0.0)
                    rec = {"ticker": tk, "t0": t0, "day": _utc_day(t0), "side": side,
                           "mode": mode, "limit": round(limit, 4), "ask0": ask0,
                           "secs_to_close": secs_to_close, "y_side": y_side,
                           "would_cross": limit >= ask0 - 1e-9, "fill_ms": None}
                    if not rec["would_cross"] and 0.0 < limit < 1.0:
                        if fill_model == "quote":
                            rec["fill_ms"] = _first_trade_through(snaps, i, ask_key, limit)
                        else:
                            rec["fill_ms"] = _first_print_fill(
                                prs, t0, close_ms, side, limit,
                                queue="through" if fill_model == "prints-through" else "front")
                    decisions.append(rec)
                    if mode == "join":
                        pair_fill_t[side] = rec["fill_ms"] if not rec["would_cross"] else None
            if pair_fill_t.get("YES") is not None and pair_fill_t.get("NO") is not None:
                pair_cost = e["yes_bid"] + e["no_bid"]
                double_fill_pairs.append({
                    "ticker": tk, "t0": t0, "pair_cost": pair_cost,
                    "locked_gross": 1.0 - pair_cost,
                    "locked_net": 1.0 - pair_cost
                    - maker_fees.per_contract_fee(e["yes_bid"])
                    - maker_fees.per_contract_fee(e["no_bid"]),
                })

    return {
        "series": series,
        "n_windows_with_label_and_books": len(windows_used),
        "n_decision_points": len({(d["ticker"], d["t0"]) for d in decisions}),
        "n_decision_records": len(decisions),
        "spread_stats": {"mean": _mean(spreads), "median": _median(spreads),
                         "p90": (sorted(spreads)[int(0.9 * len(spreads))] if spreads else None)},
        "taker_fee_stats": {"mean": _mean(taker_fee_samples), "median": _median(taker_fee_samples)},
        "decisions": decisions,
        "double_fill_pairs": double_fill_pairs,
        "horizons": horizons,
        "fill_model": fill_model,
        "n_tickers_with_prints": len(prints_by_tk),
        "improve_cents": improve_cents,
        "maker_fee_rate": maker_fee_rate,
        "maker_fee_status": maker_fees.status,
        "taker_fee_rate": taker_fees.rate,
        "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _filled_within(rec: dict, horizon, close_grace_ms: int = 0) -> bool:
    if rec["fill_ms"] is None:
        return False
    if horizon == CLOSE_HORIZON:
        return True
    return rec["fill_ms"] <= rec["t0"] + float(horizon) * 1000.0 + close_grace_ms


def _bucket_secs(s: Optional[float]) -> str:
    if s is None:
        return "unknown"
    if s < 180:
        return "<180s"
    if s < 420:
        return "180-420s"
    if s < 660:
        return "420-660s"
    return ">=660s"


def _bucket_price(limit: float) -> str:
    lo = int(limit * 10) * 10
    return f"[{lo}c,{lo + 10}c)"


def _agg(records: list[dict], maker_fee: KalshiFeeModel, taker_fee: KalshiFeeModel,
         horizon) -> dict:
    """Aggregate one (side, mode, horizon) cohort."""
    eligible = [r for r in records if not r["would_cross"]]
    fills = [r for r in eligible if _filled_within(r, horizon)]
    no_fill = [r for r in eligible if not _filled_within(r, horizon)]
    maker_ev = [(r["y_side"] - r["limit"] - maker_fee.per_contract_fee(r["limit"]))
                for r in fills]
    taker_ev = [(r["y_side"] - r["ask0"] - taker_fee.per_contract_fee(r["ask0"]))
                for r in eligible]
    return {
        "decisions": len(records), "eligible": len(eligible),
        "would_cross": len(records) - len(eligible),
        "fills": len(fills),
        "fill_rate": (len(fills) / len(eligible)) if eligible else None,
        "distinct_fill_windows": len({r["ticker"] for r in fills}),
        "median_secs_to_fill": _median([(r["fill_ms"] - r["t0"]) / 1000.0 for r in fills]),
        "mean_limit": _mean([r["limit"] for r in fills]),
        "win_rate_given_fill": _mean([r["y_side"] for r in fills]),
        "win_rate_no_fill": _mean([r["y_side"] for r in no_fill]),
        "win_rate_all_eligible": _mean([r["y_side"] for r in eligible]),
        "maker_ev_cents_per_fill": (_mean(maker_ev) * 100.0) if maker_ev else None,
        "maker_ev_cents_per_decision": ((sum(maker_ev) / len(eligible)) * 100.0)
                                       if eligible and maker_ev else (0.0 if eligible else None),
        "taker_ev_cents_per_decision": (_mean(taker_ev) * 100.0) if taker_ev else None,
        "maker_net_pnl_total": sum(maker_ev) if maker_ev else 0.0,
    }


def analyze_maker_entries(sim: dict) -> dict:
    maker_fee = KalshiFeeModel(rate=sim["maker_fee_rate"], status=sim["maker_fee_status"])
    taker_fee = KalshiFeeModel(rate=sim["taker_fee_rate"], status="ASSUMED")
    taker_as_maker = KalshiFeeModel(rate=sim["taker_fee_rate"], status="SENSITIVITY")
    decisions = sim["decisions"]
    horizons = sim["horizons"]

    by_cohort: dict = {}
    for side in ("YES", "NO"):
        for mode in ("join", "improve"):
            recs = [d for d in decisions if d["side"] == side and d["mode"] == mode]
            for h in horizons:
                key = f"{side}/{mode}/{h}"
                by_cohort[key] = _agg(recs, maker_fee, taker_fee, h)

    # fee sensitivity: makers paying the full taker schedule (close horizon, join)
    fee_sensitivity: dict = {}
    for side in ("YES", "NO"):
        recs = [d for d in decisions if d["side"] == side and d["mode"] == "join"]
        fee_sensitivity[f"{side}/join/{CLOSE_HORIZON}"] = _agg(
            recs, taker_as_maker, taker_fee, CLOSE_HORIZON)

    # price buckets / time buckets / day (join, until close — the central cohort)
    by_price: dict = {}
    by_time: dict = {}
    by_day: dict = {}
    for side in ("YES", "NO"):
        join = [d for d in decisions if d["side"] == side and d["mode"] == "join"]
        for out, key_fn in ((by_price, lambda r: _bucket_price(r["limit"])),
                            (by_time, lambda r: _bucket_secs(r["secs_to_close"])),
                            (by_day, lambda r: r["day"])):
            groups: dict = defaultdict(list)
            for r in join:
                groups[key_fn(r)].append(r)
            for g, recs in sorted(groups.items()):
                out[f"{side}/{g}"] = _agg(recs, maker_fee, taker_fee, CLOSE_HORIZON)

    pairs = sim["double_fill_pairs"]
    join_points = {(d["ticker"], d["t0"]) for d in decisions
                   if d["mode"] == "join" and not d["would_cross"]}
    double_fill = {
        "n_quote_points": len(join_points),
        "n_double_fills": len(pairs),
        "double_fill_rate": (len(pairs) / len(join_points)) if join_points else None,
        "mean_pair_cost": _mean([p["pair_cost"] for p in pairs]),
        "mean_locked_net": _mean([p["locked_net"] for p in pairs]),
        "total_locked_net": sum(p["locked_net"] for p in pairs) if pairs else 0.0,
        "distinct_windows": len({p["ticker"] for p in pairs}),
    }

    # verdict: conservative lower bound per side at the central cohort
    central = {s: by_cohort[f"{s}/join/{CLOSE_HORIZON}"] for s in ("YES", "NO")}
    sides_positive = [s for s, a in central.items()
                      if (a["maker_ev_cents_per_fill"] or -999) > 0 and a["fills"] >= 30
                      and a["distinct_fill_windows"] >= 20]
    sides_better_than_taker = [
        s for s, a in central.items()
        if a["maker_ev_cents_per_fill"] is not None and a["taker_ev_cents_per_decision"] is not None
        and a["maker_ev_cents_per_fill"] > a["taker_ev_cents_per_decision"]]
    verdict = {
        "sides_with_positive_conservative_maker_ev": sides_positive,
        "sides_where_maker_beats_taker": sides_better_than_taker,
        "interpretation": (
            "POSITIVE lower bound: even counting only adverse trade-through fills, resting at the bid "
            "earned more than it cost on: " + ", ".join(sides_positive) + ". Worth a deeper study with "
            "real trade prints / WS book data before any paper or live step."
            if sides_positive else
            "The conservative lower bound on maker EV is negative or under-sampled: trade-through fills "
            "are adversely selected and the spread saved did not cover the adverse selection measured "
            "this way. This does NOT prove maker entries lose (fills are undercounted and the counted "
            "ones are the worst subset) — resolving it needs trade prints or sub-second WS book data."),
    }

    return {"by_cohort": by_cohort, "fee_sensitivity": fee_sensitivity, "by_price": by_price,
            "by_time": by_time, "by_day": by_day, "double_fill": double_fill,
            "verdict": verdict}


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _cohort_table(rows: dict, title: str) -> list[str]:
    out = [f"## {title}", "",
           "| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | "
           "maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, a in rows.items():
        out.append(
            f"| {key} | {a['eligible']} | {a['fills']} | {_pct(a['fill_rate'])} | "
            f"{_f(a['median_secs_to_fill'], 1)} | {_pct(a['win_rate_given_fill'])} | "
            f"{_pct(a['win_rate_no_fill'])} | {_f(a['maker_ev_cents_per_fill'])} | "
            f"{_f(a['maker_ev_cents_per_decision'])} | {_f(a['taker_ev_cents_per_decision'])} | "
            f"{a['distinct_fill_windows']} |")
    out.append("")
    return out


def write_maker_entry_report(config, sim: dict, analysis: dict) -> dict:
    ts = _ts()
    rep_dir = config.reports_path() / "maker"
    rep_dir.mkdir(parents=True, exist_ok=True)
    md_path = rep_dir / f"kalshi_maker_entry_study_{ts}.md"
    csv_path = rep_dir / f"kalshi_maker_entry_study_{ts}.csv"

    sp = sim["spread_stats"]
    tf = sim["taker_fee_stats"]
    df = analysis["double_fill"]
    v = analysis["verdict"]
    fm = sim.get("fill_model", "quote")
    fill_blurb = {
        "quote": ("Conservative QUOTE-crossing fill model: a resting bid is counted filled ONLY "
                  "when a later snapshot's same-side ask crosses to/below the limit, so fills are "
                  "undercounted AND adversely selected — every maker EV here is a LOWER BOUND."),
        "prints-through": ("REAL trade prints, CERTAIN fills only: a resting bid counts as filled "
                           "when the tape traded strictly THROUGH the level (queue-position-free). "
                           "Conservative on fill count, but fills/outcomes come from actual flow."),
        "prints-front": ("REAL trade prints, FRONT-OF-QUEUE assumption: a resting bid counts as "
                         "filled when the tape traded AT or through the level. OPTIMISTIC upper "
                         "bound — real queue position would forfeit some at-level fills."),
    }[fm]
    lines = [
        f"# Kalshi maker-entry feasibility study — {sim['series']} (fill model: {fm})", "",
        f"> READ-ONLY research. {fill_blurb} No orders, no paper, no promotion; live disabled.", "",
        f"- windows: {sim['n_windows_with_label_and_books']}  decision points: "
        f"{sim['n_decision_points']}  (one per market-minute; sides×modes per point)",
        f"- cost to cross today: spread mean/median/p90 = {_f(sp['mean'], 3)}/"
        f"{_f(sp['median'], 3)}/{_f(sp['p90'], 3)}  taker fee mean = {_f(tf['mean'], 4)}",
        f"- maker fee rate: {sim['maker_fee_rate']} ({sim['maker_fee_status']}); taker rate "
        f"{sim['taker_fee_rate']} (ASSUMED). Fee-sensitivity table below charges makers the "
        "full taker schedule.", "",
    ]
    lines += _cohort_table(analysis["by_cohort"], "Cohorts (side/mode/rest-horizon)")
    lines += _cohort_table(analysis["fee_sensitivity"],
                           "Fee sensitivity (maker pays FULL taker schedule)")
    lines += _cohort_table(analysis["by_price"], "By limit-price bucket (join, rest-to-close)")
    lines += _cohort_table(analysis["by_time"], "By seconds-to-close (join, rest-to-close)")
    lines += _cohort_table(analysis["by_day"], "By UTC day (join, rest-to-close)")
    lines += [
        "## Both-sides quoting (double fill of YES-join + NO-join)", "",
        f"- quote points: {df['n_quote_points']}  double fills: {df['n_double_fills']} "
        f"({_pct(df['double_fill_rate'])}) across {df['distinct_windows']} windows",
        f"- mean pair cost: {_f(df['mean_pair_cost'], 4)}  mean locked net per pair: "
        f"{_f(df['mean_locked_net'], 4)}  total locked net: {_f(df['total_locked_net'], 3)}", "",
        "## Verdict", "",
        f"- sides with POSITIVE conservative maker EV: {v['sides_with_positive_conservative_maker_ev']}",
        f"- sides where maker(lower bound) beats taker: {v['sides_where_maker_beats_taker']}",
        f"- {v['interpretation']}", "",
        "## Honest caveats", "",
        "- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills "
        "from sells into the bid are invisible (undercount), and counted fills are the most adverse "
        "subset (price traded through). Both biases make maker EV look WORSE than reality.",
        "- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical "
        "depth this is optimistic per-fill but does not change the conditional-outcome estimate.",
        "- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.",
        "- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade "
        "prints (public /trades) or authenticated WS book deltas.", "",
        "## Safety",
        "- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; "
        "live_submission_allowed=false.", "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "cohort", "eligible", "fills", "fill_rate", "median_secs_to_fill",
                    "win_rate_given_fill", "win_rate_no_fill", "maker_ev_cents_per_fill",
                    "maker_ev_cents_per_decision", "taker_ev_cents_per_decision",
                    "distinct_fill_windows"])
        for table in ("by_cohort", "fee_sensitivity", "by_price", "by_time", "by_day"):
            for key, a in analysis[table].items():
                w.writerow([table, key, a["eligible"], a["fills"], a["fill_rate"],
                            a["median_secs_to_fill"], a["win_rate_given_fill"],
                            a["win_rate_no_fill"], a["maker_ev_cents_per_fill"],
                            a["maker_ev_cents_per_decision"], a["taker_ev_cents_per_decision"],
                            a["distinct_fill_windows"]])
    return {"report_file": str(md_path), "csv_file": str(csv_path)}


def run_maker_entry_study(config, *, series: str = "KXBTC15M", improve_cents: int = 1,
                          maker_fee_rate: float = 0.0,
                          rest_horizons: Optional[list] = None,
                          fill_model: str = "quote") -> dict:
    sim = simulate_maker_entries(config, series=series, improve_cents=improve_cents,
                                 rest_horizons=rest_horizons, maker_fee_rate=maker_fee_rate,
                                 fill_model=fill_model)
    analysis = analyze_maker_entries(sim)
    files = write_maker_entry_report(config, sim, analysis)
    return {"series": series, "status": "OK", "fill_model": fill_model,
            "n_windows": sim["n_windows_with_label_and_books"],
            "n_decision_points": sim["n_decision_points"],
            "spread_stats": sim["spread_stats"], "taker_fee_stats": sim["taker_fee_stats"],
            "central_cohorts": {s: analysis["by_cohort"][f"{s}/join/{CLOSE_HORIZON}"]
                                for s in ("YES", "NO")},
            "double_fill": analysis["double_fill"], "verdict": analysis["verdict"],
            **files, "live_submission_allowed": False}
