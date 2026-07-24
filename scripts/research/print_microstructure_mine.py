"""Print-level microstructure mine — finer than the aggregate CVD we already used. READ-ONLY.

From the BTC trade tape (created_time_ms, count=size, taker_side), compute per window — over
the 120s before the decision snapshot — large-print / sweep / order-flow-toxicity signals:
  p_intensity     prints per second
  p_signed_imb    net signed volume (taker YES=+, NO=-) / total volume
  p_max_size      largest single print (whale)
  p_large_signed  signed volume of LARGE prints only (>= global 90th pct) / their volume
  p_sweep         longest run of consecutive same-side prints (aggressive sweep)
Then run the full gauntlet. The question: does print-level toxicity predict the 15m residual
the aggregate flow features missed?"""
from __future__ import annotations

import sys
import numpy as np

sys.path.insert(0, "src")
from btc5m.discovery import engine, feature_factory  # noqa: E402
from btc5m.venues.kalshi.backfill_trades import load_trade_prints  # noqa: E402
from btc5m.venues.kalshi.fees import KalshiFeeModel  # noqa: E402

W_MS = 120_000
PFEATS = ["p_intensity", "p_signed_imb", "p_max_size", "p_large_signed", "p_sweep"]


def main():
    pn, cfg = engine._build_panel("KXBTC15M", 180.0, 3.0)
    fee = KalshiFeeModel.from_config(cfg)
    prints = load_trade_prints(cfg, series="KXBTC15M")
    # global large-print threshold = 90th pct of all counts
    allc = [p.get("count") for ps in prints.values() for p in ps if p.get("count")]
    large_thr = float(np.quantile(allc, 0.90)) if allc else 0.0
    print(f"loaded prints for {len(prints)} windows; large-print threshold (90th pct count) = {large_thr:.0f}")

    kept = 0
    for o in pn:
        ps = prints.get(o.ticker)
        if not ps or o.t0_ms is None:
            continue
        seg = [p for p in ps if o.t0_ms - W_MS <= p["created_time_ms"] <= o.t0_ms]
        if len(seg) < 5:
            continue
        sizes = [(p.get("count") or 0) for p in seg]
        signs = [(1 if p.get("taker_side") == "yes" else -1) for p in seg]
        tot = sum(sizes) or 1.0
        o.feats["p_intensity"] = len(seg) / (W_MS / 1000.0)
        o.feats["p_signed_imb"] = sum(s * g for s, g in zip(sizes, signs)) / tot
        o.feats["p_max_size"] = max(sizes) if sizes else 0.0
        lv = [(s, g) for s, g in zip(sizes, signs) if s >= large_thr]
        ltot = sum(s for s, _ in lv) or 1.0
        o.feats["p_large_signed"] = sum(s * g for s, g in lv) / ltot if lv else 0.0
        # longest same-side run (sweep)
        best = run = 1
        for i in range(1, len(signs)):
            run = run + 1 if signs[i] == signs[i - 1] else 1
            best = max(best, run)
        o.feats["p_sweep"] = float(best)
        kept += 1
    print(f"windows with print-microstructure features: {kept}")
    feat_list = feature_factory.feature_names() + PFEATS
    engine.mine_prebuilt_panel(pn, fee, feat_list, space_id="print_micro",
                               label="print-level microstructure (BTC)", force_features=PFEATS)


if __name__ == "__main__":
    main()
