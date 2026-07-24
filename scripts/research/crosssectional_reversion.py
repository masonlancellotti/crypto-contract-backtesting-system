"""Cross-sectional reversion mine — fade an alt's idiosyncratic deviation from BTC. READ-ONLY.

The lead-lag test (#29) asked 'does the alt FOLLOW BTC?' This asks the opposite-structured
question: when an alt's own state has DEVIATED from the BTC factor, does it mean-revert? For
each alt window we attach BTC's concurrent state and form deviation features:
  dev_dist_z   = alt distance-z - BTC distance-z      (idiosyncratic dislocation)
  dev_ret_60s  = alt 60s return - BTC 60s return
  abs_dev_dist = |dev_dist_z|                           (magnitude of dislocation)
Pool the alts (rank-normalized) and run the gauntlet. The search tests both directions, so it
finds reversion (fade) OR continuation (follow), whichever clears cost."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")
from btc5m.discovery import crosscoin, engine, feature_factory, panel  # noqa: E402
from btc5m.venues.kalshi.fees import KalshiFeeModel  # noqa: E402

DEVF = ["dev_dist_z", "dev_ret_60s", "abs_dev_dist"]


def main():
    btc_clock = crosscoin.build_btc_clock(lead_seconds=180.0)
    pn_raw, fee = [], None
    for s in crosscoin.ALTS:
        pn, cfg = engine._build_panel(s, 180.0, 3.0)
        crosscoin.attach_concurrent(pn, btc_clock)
        fee = KalshiFeeModel.from_config(cfg)
        for o in pn:
            ad, bd = o.feats.get("distance_to_line_vol_normalized"), o.feats.get("btc_dist_z")
            ar, br = o.feats.get("spot_return_60s"), o.feats.get("btc_ret_60s")
            if ad is not None and bd is not None:
                o.feats["dev_dist_z"] = ad - bd
                o.feats["abs_dev_dist"] = abs(ad - bd)
            if ar is not None and br is not None:
                o.feats["dev_ret_60s"] = ar - br
        pn_raw.extend(pn)
    pn_all = panel.rank_normalize_per_asset(pn_raw)
    feat_list = feature_factory.feature_names() + DEVF
    engine.mine_prebuilt_panel(pn_all, fee, feat_list, space_id="xsect_rev",
                               label="cross-sectional reversion (alts vs BTC factor)",
                               force_features=DEVF)


if __name__ == "__main__":
    main()
