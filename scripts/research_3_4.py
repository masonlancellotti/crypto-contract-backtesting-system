"""Read-only research helper for strategies ③ (order-flow side-selection) and
④ (time-to-close favorite entry) on KXBTC15M. No sklearn (avoids the WMI stall).

Methodology mirrors the validated studies: official labels only, executable ASK
prices (never midpoint), fee subtracted, one snapshot per (window, decision point)
so windows are the independent unit. EV is per-contract in dollars.
"""
import glob, json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from collections import defaultdict
from btc5m.config import load_config
from btc5m.venues.kalshi.maker_entry import _official_label_map

MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}

def window_date(tk):
    try:
        tok = tk.split("-")[1]            # 26JUN010430
        return f"2026-{MONTHS[tok[2:5]]:02d}-{int(tok[5:7]):02d}"
    except Exception:
        return "?"

def mean(xs): return sum(xs)/len(xs) if xs else float("nan")

cfg = load_config(mode="paper")
lbl = _official_label_map(cfg)
files = sorted(glob.glob("data/features/kalshi_feature_rows-*.jsonl"))

# Per-window selected snapshots:
#  ④: keyed (tk, ttc_bucket) -> nearest-to-center row
#  ③: keyed tk -> row nearest ttc target (450s) that has the OFI signal
TTC_BUCKETS = [(0,60,"0-60s"),(60,120,"60-120s"),(120,300,"120-300s"),(300,600,"300-600s"),(600,1000,"600-900s")]
def ttc_bucket(t):
    for lo,hi,name in TTC_BUCKETS:
        if lo <= t < hi: return name
    return None
def ttc_center(name):
    for lo,hi,n in TTC_BUCKETS:
        if n==name: return (lo+hi)/2
    return 0

four = {}      # (tk,bucket) -> (diff, row)
three = {}     # tk -> (diff, row)  decision snapshot for order-flow
TARGET3 = 450

rows_scanned = joinable = 0
for fp in files:
    with open(fp, encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: d=json.loads(line)
            except Exception: continue
            tk=d.get("market_ticker")
            if tk not in lbl: continue
            if not d.get("has_orderbook"): continue
            ya, na, ttc = d.get("yes_ask"), d.get("no_ask"), d.get("seconds_to_close")
            if ya is None or na is None or ttc is None: continue
            rows_scanned+=1
            fee = d.get("fee_estimate_per_contract") or 0.02
            rec = {
                "y": lbl[tk], "ya": ya, "na": na, "fee": fee, "ttc": ttc,
                "dist": d.get("distance_to_start"),
                "day": window_date(tk),
                "ofi": d.get("perp_signed_trade_imbalance_60s"),
                "ofib": d.get("binance_ofi_best"),
                "cvd": d.get("perp_cvd_60s"),
                "spotret": d.get("spot_return_since_window_start"),
            }
            joinable+=1
            # ④ selection
            b=ttc_bucket(ttc)
            if b is not None:
                diff=abs(ttc-ttc_center(b)); key=(tk,b)
                if key not in four or diff<four[key][0]: four[key]=(diff,rec)
            # ③ selection (needs OFI present)
            if rec["ofi"] is not None:
                diff=abs(ttc-TARGET3)
                if tk not in three or diff<three[tk][0]: three[tk]=(diff,rec)

print(f"# rows_scanned={rows_scanned} joinable={joinable} windows_with_ofi={len(three)} labels={len(lbl)}")

# ----------------------------------------------------------------------------- #
# ④  Time-to-close × favorite band: EV of buying the FAVORITE side after cost
# ----------------------------------------------------------------------------- #
print("\n================ ④ TIME-TO-CLOSE × FAVORITE BAND (BTC) ================")
print("EV = realized_payoff - executable_ask - fee, per contract ($). Favorite = side priced >50c.")
# bucket rows by ttc_bucket and yes-price band
PB = [(0.5,0.6),(0.6,0.7),(0.7,0.8),(0.8,0.9),(0.9,1.01)]
def pband(p):
    for lo,hi in PB:
        if lo<=p<hi: return f"{int(lo*100)}-{int(hi*100)}c"
    return None
# Favorite EV: if yes_ask>0.5 buy YES else buy NO. Express price band by favorite implied prob.
cells = defaultdict(list)   # (ttc_name, fav_band) -> list of (ev_fav, day, y, fav_side)
for (tk,b),(diff,r) in four.items():
    p = r["ya"]                     # yes implied (=mkt_implied_yes_from_ask)
    if p>0.5:
        fav_p=p; ev=r["y"]-r["ya"]-r["fee"]; side="YES"
    else:
        fav_p=1-p; ev=(1-r["y"])-r["na"]-r["fee"]; side="NO"
    band=pband(fav_p)
    if band: cells[(b,band)].append((ev,r["day"],r["y"],side))
order=[n for _,_,n in TTC_BUCKETS]
bands=[f"{int(lo*100)}-{int(hi*100)}c" for lo,hi in PB]
print(f"\n{'ttc':>10} | " + " | ".join(f"{bd:>16}" for bd in bands))
for tname in order:
    out=[]
    for bd in bands:
        v=cells.get((tname,bd))
        if v and len(v)>=15:
            out.append(f"{mean([x[0] for x in v])*100:+5.2f}c n{len(v):>4}")
        elif v:
            out.append(f"  ({len(v)})       ")
        else:
            out.append("      -         ")
    print(f"{tname:>10} | " + " | ".join(f"{o:>16}" for o in out))

# ④ regime split for the deep-favorite near-close cells (>=80c favorite, ttc<300)
print("\n-- ④ regime stability: deep-favorite (>=80c) by ttc, split by per-day window-direction --")
for tname in order:
    pos=[];  # ev for >=80c favorite cells
    for bd in ("80-90c","90-100c"):
        pos += cells.get((tname,bd),[])
    if len(pos)<15:
        print(f"  {tname:>10}: n={len(pos)} (thin)"); continue
    # group by day, day is up if that day's windows mostly resolved YES
    byday=defaultdict(list)
    for ev,day,y,side in pos: byday[day].append((ev,y,side))
    day_evs=[(d, mean([e for e,_,_ in v]), len(v)) for d,v in byday.items()]
    pos_days=sum(1 for _,e,_ in day_evs if e>0); tot=len(day_evs)
    print(f"  {tname:>10}: EV={mean([x[0] for x in pos])*100:+.2f}c n={len(pos)}  positive_days={pos_days}/{tot}")

# ④b  Favorite EV split by SIDE (YES-fav vs NO-fav) — regime-luck check
print("\n-- ④b favorite EV split by side (is a positive cell real, or just NO winning in a down sample?) --")
print(f"{'band':>10} | {'YES-fav EV':>11} {'n':>5} {'+days':>6} | {'NO-fav EV':>11} {'n':>5} {'+days':>6}")
for bd in bands:
    ys=[]; ns=[]
    for tname in order:
        for ev,day,y,side in cells.get((tname,bd),[]):
            (ys if side=="YES" else ns).append((ev,day))
    def fmt(lst):
        if len(lst)<15: return (f"thin({len(lst)})","","")
        byd=defaultdict(list)
        for ev,day in lst: byd[day].append(ev)
        pd=sum(1 for d in byd if mean(byd[d])>0)
        return (f"{mean([e for e,_ in lst])*100:+.2f}c", str(len(lst)), f"{pd}/{len(byd)}")
    ye=fmt(ys); ne=fmt(ns)
    print(f"{bd:>10} | {ye[0]:>11} {ye[1]:>5} {ye[2]:>6} | {ne[0]:>11} {ne[1]:>5} {ne[2]:>6}")

# ----------------------------------------------------------------------------- #
# ③  Order-flow side-selection (06-02..06-10 where OFI populated)
# ----------------------------------------------------------------------------- #
print("\n================ ③ ORDER-FLOW SIDE-SELECTION (BTC, mid-window ~450s) ================")
recs=[r for _,r in three.values()]
days=sorted({r["day"] for r in recs})
print(f"windows={len(recs)} days={days[0]}..{days[-1]} ({len(days)} days)")

# (a) Does OFI sign separate outcomes WITHIN a price band? (controls for the price)
print("\n-- (a) realized YES-rate by yes-price band, split on sign(OFI) -- (separation = signal)")
print(f"{'price':>10} | {'OFI>0 yes%':>12} {'n':>5} | {'OFI<0 yes%':>12} {'n':>5} | {'sep(pp)':>8}")
for lo,hi in [(0.3,0.45),(0.45,0.55),(0.55,0.7)]:
    pos=[r for r in recs if r["ofi"]>0 and lo<=r["ya"]<hi]
    neg=[r for r in recs if r["ofi"]<0 and lo<=r["ya"]<hi]
    if len(pos)>=10 and len(neg)>=10:
        pp=mean([r["y"] for r in pos]); nn=mean([r["y"] for r in neg])
        print(f"{int(lo*100)}-{int(hi*100)}c | {pp*100:>11.1f}% {len(pos):>5} | {nn*100:>11.1f}% {len(neg):>5} | {(pp-nn)*100:>+7.1f}")
    else:
        print(f"{int(lo*100)}-{int(hi*100)}c | thin ({len(pos)}/{len(neg)})")

# (b) By-side P&L: strategy 'buy the OFI-selected side at ask+fee' vs static YES/NO
def strat_ev(rec_list, picker):
    evs=[]
    for r in rec_list:
        side=picker(r)
        if side=="YES": evs.append(r["y"]-r["ya"]-r["fee"])
        elif side=="NO": evs.append((1-r["y"])-r["na"]-r["fee"])
    return evs
strategies={
    "OFI-sign (signed_imbalance)": lambda r: "YES" if r["ofi"]>0 else "NO",
    "binance_ofi_best sign":       lambda r: ("YES" if r["ofib"]>0 else "NO") if r["ofib"] is not None else None,
    "perp_cvd_60s sign":           lambda r: ("YES" if r["cvd"]>0 else "NO") if r["cvd"] is not None else None,
    "spot_return sign":            lambda r: ("YES" if (r["spotret"] or 0)>0 else "NO"),
    "static YES":                  lambda r: "YES",
    "static NO":                   lambda r: "NO",
}
print("\n-- (b) per-contract EV after ask+fee (taker), overall + per-day stability --")
print(f"{'strategy':>30} | {'EV':>8} {'n':>5} | {'pos_days':>9} | per-day EV(c)")
for name,pk in strategies.items():
    evs=strat_ev(recs,pk)
    if not evs: continue
    byday=defaultdict(list)
    for r in recs:
        s=pk(r)
        if s=="YES": byday[r["day"]].append(r["y"]-r["ya"]-r["fee"])
        elif s=="NO": byday[r["day"]].append((1-r["y"])-r["na"]-r["fee"])
    dayev=[(d,mean(v)) for d,v in sorted(byday.items())]
    posd=sum(1 for _,e in dayev if e>0)
    series=" ".join(f"{e*100:+.1f}" for _,e in dayev)
    print(f"{name:>30} | {mean(evs)*100:+7.2f}c {len(evs):>5} | {posd:>2}/{len(dayev):>2}    | {series}")
print("\nWin condition for ③: an OFI strategy with EV>0 AND positive across most days (both up & down).")
