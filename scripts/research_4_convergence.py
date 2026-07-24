"""④-DEEP: late-window convergence edge on KXBTC15M (read-only, no sklearn).

Hypothesis: within the 15m window there is a time after which the eventual
winner is NOT yet priced ~$1.00 but its TRUE P(win) is already very high, so you
can buy the favorite below fair value and it converges to $1.00 at settlement.

Units: prices in dollars (0-1). Favorite defined by mid = (yes_bid+yes_ask)/2.
Costs: taker pays the favorite ASK + fee; maker estimate = taker + 1.8c (the
ledger's measured real-fill maker saving), with the adverse-selection caveat.
Outcome = official label. One snapshot per (window, time bucket); window is the
independent unit. distance_to_start is a Coinbase/Binance proxy for the BRTI
settlement distance (noisy near close).
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
        t=tk.split("-")[1]; return f"2026-{MONTHS[t[2:5]]:02d}-{int(t[5:7]):02d}"
    except Exception: return "?"
def mean(xs): return sum(xs)/len(xs) if xs else float("nan")
MAKER_CREDIT = 0.018  # ledger: maker saves ~1.8c/fill vs taker (real fills)

cfg = load_config(mode="paper")
lbl = _official_label_map(cfg)
# per-day YES rate (regime classifier), computed from the FULL official label set
day_lab=defaultdict(list)
for tk,y in lbl.items(): day_lab[window_date(tk)].append(y)
day_yesrate={d:mean(v) for d,v in day_lab.items()}
def regime(day): return "up" if day_yesrate.get(day,0.5)>0.5 else "down"
def week(day):
    return "W1" if day<="2026-06-07" else "W2"

# Fine 60s time buckets, one snapshot per (window, bucket): nearest to bucket center
FINE=[(lo,lo+60) for lo in range(0,900,60)]
def fbucket(t):
    for lo,hi in FINE:
        if lo<=t<hi: return lo
    return None
store=defaultdict(dict)   # tk -> {bucket_lo: rec}
files=sorted(glob.glob("data/features/kalshi_feature_rows-*.jsonl"))
scanned=0
for fp in files:
    with open(fp,encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: d=json.loads(line)
            except Exception: continue
            tk=d.get("market_ticker")
            if tk not in lbl or not d.get("has_orderbook"): continue
            ya,na,ttc=d.get("yes_ask"),d.get("no_ask"),d.get("seconds_to_close")
            yb,nb=d.get("yes_bid"),d.get("no_bid")
            if ya is None or na is None or ttc is None: continue
            b=fbucket(ttc)
            if b is None: continue
            scanned+=1
            mid_yes=((yb+ya)/2) if (yb is not None) else ya
            fav = "YES" if mid_yes>=0.5 else "NO"
            fav_mid = mid_yes if fav=="YES" else 1-mid_yes
            fav_ask = ya if fav=="YES" else na
            fav_bid = (yb if fav=="YES" else nb)
            y=lbl[tk]; win = (y==1) if fav=="YES" else (y==0)
            rec={"ttc":ttc,"fav":fav,"mid":fav_mid,"ask":fav_ask,"bid":fav_bid,
                 "win":1 if win else 0,"fee":d.get("fee_estimate_per_contract") or 0.02,
                 "dist":d.get("distance_to_start"),"day":window_date(tk),"tk":tk,
                 "sig":d.get("spot_sigma_per_sqrt_s"),"spot":d.get("reference_price")}
            cur=store[tk].get(b)
            center=b+30
            if cur is None or abs(ttc-center)<abs(cur["ttc"]-center): store[tk][b]=rec
print(f"# rows_scanned={scanned} windows={len(store)} labels={len(lbl)} "
      f"days={min(day_yesrate)}..{max(day_yesrate)} up_days={sum(1 for d in day_yesrate if regime(d)=='up')} "
      f"down_days={sum(1 for d in day_yesrate if regime(d)=='down')}")

# flatten to list of recs
import math
recs=[r for w in store.values() for r in w.values()]
# vol-normalized determinism z = (spot-start) / (sigma_ret * sqrt(ttc) * spot)  [# of sigmas]
_zs=[]
for r in recs:
    z=None
    if r["dist"] is not None and r["sig"] and r["sig"]>0 and r["spot"] and r["ttc"]>0:
        em = r["sig"]*math.sqrt(r["ttc"])*r["spot"]   # expected $ move over remaining ttc
        if em>0: z=r["dist"]/em
    r["z"]=z
    if z is not None: _zs.append(abs(z))
_zs.sort()
def _q(p): return _zs[int(p*(len(_zs)-1))] if _zs else float("nan")
print(f"# |z| coverage={len(_zs)}/{len(recs)}  |z| quantiles p10={_q(.1):.2f} p50={_q(.5):.2f} "
      f"p90={_q(.9):.2f} p99={_q(.99):.2f}")

# =========================================================================== #
# (1)+(2) CONVERGENCE CURVE / CALIBRATION BY TIME-TO-CLOSE × FAVORITE BAND
# gap_gross = empirical settle-rate - favorite MID price  (miscalibration)
# gap_net   = empirical settle-rate - favorite ASK - fee  (taker tradable edge)
# =========================================================================== #
PB=[(0.50,0.60),(0.60,0.70),(0.70,0.80),(0.80,0.85),(0.85,0.90),(0.90,0.95),(0.95,0.99),(0.99,1.001)]
def pbname(lo,hi): return f"{int(lo*100)}-{int(round(hi*100))}"
TB=[(0,60,"0-60"),(60,120,"60-120"),(120,240,"120-240"),(240,480,"240-480"),(480,900,"480-900")]
def tbname(t):
    for lo,hi,nm in TB:
        if lo<=t<hi: return nm
    return None
def band(p):
    for lo,hi in PB:
        if lo<=p<hi: return pbname(lo,hi)
    return None

cell=defaultdict(list)   # (tb,pb) -> recs
for r in recs:
    tb=tbname(r["ttc"]); pb=band(r["mid"])
    if tb and pb: cell[(tb,pb)].append(r)

print("\n========== (1) CALIBRATION GAP = empirical_settle_rate - favorite_MID (cents) ==========")
print("   (positive = market UNDERPRICES the favorite; n in parens; '.' = thin <25)")
hdr=[pbname(lo,hi) for lo,hi in PB]
print(f"{'ttc(s)':>8} | " + " | ".join(f"{h:>11}" for h in hdr))
for lo,hi,tb in TB:
    out=[]
    for lo2,hi2 in PB:
        pb=pbname(lo2,hi2); v=cell.get((tb,pb))
        if v and len(v)>=25:
            g=(mean([x["win"] for x in v])-mean([x["mid"] for x in v]))*100
            out.append(f"{g:+5.1f} ({len(v)})")
        else:
            out.append(f"  . ({len(v) if v else 0})")
    print(f"{tb:>8} | " + " | ".join(f"{o:>11}" for o in out))

print("\n========== (1b) NET TAKER EDGE = settle_rate - favorite_ASK - fee (cents) ==========")
print(f"{'ttc(s)':>8} | " + " | ".join(f"{h:>11}" for h in hdr))
for lo,hi,tb in TB:
    out=[]
    for lo2,hi2 in PB:
        pb=pbname(lo2,hi2); v=cell.get((tb,pb))
        if v and len(v)>=25:
            g=(mean([x["win"] for x in v])-mean([x["ask"] for x in v])-mean([x["fee"] for x in v]))*100
            out.append(f"{g:+5.1f} ({len(v)})")
        else:
            out.append(f"  . ({len(v) if v else 0})")
    print(f"{tb:>8} | " + " | ".join(f"{o:>11}" for o in out))

# =========================================================================== #
# (5) MECHANISM: does the gap GROW as ttc->0 WITHIN a fixed favorite band?
# (incremental late-window convergence) vs flat (just the favorite-band/leg-15 bias)
# =========================================================================== #
print("\n========== (5) MECHANISM: gross gap vs ttc, WITHIN fixed favorite bands ==========")
print("   (if gap grows as ttc->0 => real late convergence; if flat => just favorite-band bias)")
for lo2,hi2 in [(0.85,0.90),(0.90,0.95),(0.95,0.99)]:
    pb=pbname(lo2,hi2); row=[]
    for lo,hi,tb in TB:
        v=cell.get((tb,pb))
        if v and len(v)>=25:
            g=(mean([x["win"] for x in v])-mean([x["mid"] for x in v]))*100
            row.append(f"{tb}:{g:+.1f}({len(v)})")
        else: row.append(f"{tb}:.")
    print(f"  band {pb}c | " + "  ".join(row))

# =========================================================================== #
# (3) ENTRY-RULE BACKTEST SWEEP + (4) ROBUSTNESS SPLITS
# Rule: enter favorite at the FIRST snapshot with ttc<T AND mid in [lo,hi] AND |dist|>X
#       (one entry per window). Net EV taker & maker(+1.8c). Per-day, per-side, per-regime, per-week.
# =========================================================================== #
def entries(T, lo, hi, X):
    out=[]
    for tk,bk in store.items():
        # snapshots with ttc<T, in decreasing ttc (enter as soon as crossing T)
        cand=sorted([r for r in bk.values() if r["ttc"]<T], key=lambda r:-r["ttc"])
        for r in cand:
            if lo<=r["mid"]<hi and (X<=0 or (r["dist"] is not None and abs(r["dist"])>X)):
                out.append(r); break
    return out
def ev_taker(r): return r["win"]-r["ask"]-r["fee"]
def summarize(es):
    if not es: return None
    evt=[ev_taker(r) for r in es]
    byday=defaultdict(list)
    for r in es: byday[r["day"]].append(ev_taker(r))
    dayev={d:mean(v) for d,v in byday.items()}
    posd=sum(1 for e in dayev.values() if e>0)
    yes=[ev_taker(r) for r in es if r["fav"]=="YES"]; no=[ev_taker(r) for r in es if r["fav"]=="NO"]
    up=[ev_taker(r) for r in es if regime(r["day"])=="up"]; dn=[ev_taker(r) for r in es if regime(r["day"])=="down"]
    w1=[ev_taker(r) for r in es if week(r["day"])=="W1"]; w2=[ev_taker(r) for r in es if week(r["day"])=="W2"]
    return dict(n=len(es),hit=mean([r["win"] for r in es]),evt=mean(evt),evm=mean(evt)+MAKER_CREDIT,
                posd=posd,nd=len(dayev),
                yes=(mean(yes)if yes else None,len(yes)),no=(mean(no)if no else None,len(no)),
                up=(mean(up)if up else None,len(up)),dn=(mean(dn)if dn else None,len(dn)),
                w1=(mean(w1)if w1 else None,len(w1)),w2=(mean(w2)if w2 else None,len(w2)))

print("\n========== (3) ENTRY-RULE SWEEP: net EV after cost (taker / maker+1.8c) ==========")
print(f"{'T<':>4} {'band':>9} {'|d|>':>5} | {'n':>4} {'hit':>6} {'EVtak':>7} {'EVmak':>7} {'+days':>7} | "
      f"{'YESev/n':>11} {'NOev/n':>11} | {'UPev':>6} {'DNev':>6} | {'W1':>6} {'W2':>6}")
SWEEP=[]
for T in (60,120,180,300):
    for lo,hi in [(0.80,0.90),(0.85,0.95),(0.90,0.98),(0.95,0.995)]:
        for X in (0,30,75):
            s=summarize(entries(T,lo,hi,X))
            if not s or s["n"]<20: continue
            SWEEP.append((T,lo,hi,X,s))
            def pr(t):
                v,n=t; return f"{v*100:+5.1f}/{n:<4}" if v is not None else f"  -/{n:<4}"
            def p1(t):
                v,_=t; return f"{v*100:+5.1f}" if v is not None else "   - "
            print(f"{T:>4} {pbname(lo,hi):>9} {X:>5} | {s['n']:>4} {s['hit']*100:>5.1f}% "
                  f"{s['evt']*100:>+6.1f} {s['evm']*100:>+6.1f} {s['posd']:>3}/{s['nd']:<3} | "
                  f"{pr(s['yes'])} {pr(s['no'])} | {p1(s['up'])} {p1(s['dn'])} | {p1(s['w1'])} {p1(s['w2'])}")

# =========================================================================== #
# (4) ROBUST CELL FILTER: positive taker EV AND positive on BOTH fav sides AND
#     both regimes AND both weeks AND >=55% positive days
# =========================================================================== #
print("\n========== (4) ROBUST CELLS (taker EV>0 AND both sides>0 AND both regimes>0 AND both weeks>0) ==========")
robust=[]
for T,lo,hi,X,s in SWEEP:
    def ok(t): return t[0] is not None and t[0]>0 and t[1]>=8
    if (s["evt"]>0 and ok(s["yes"]) and ok(s["no"]) and ok(s["up"]) and ok(s["dn"])
            and ok(s["w1"]) and ok(s["w2"]) and s["posd"]/max(s["nd"],1)>=0.55):
        robust.append((T,lo,hi,X,s))
if robust:
    for T,lo,hi,X,s in sorted(robust,key=lambda z:-z[4]["evt"]):
        print(f"  ROBUST: T<{T} band {pbname(lo,hi)}c |d|>{X}: EV_taker {s['evt']*100:+.1f}c "
              f"EV_maker {s['evm']*100:+.1f}c n={s['n']} hit={s['hit']*100:.1f}% days {s['posd']}/{s['nd']} "
              f"YES{s['yes'][0]*100:+.1f}/NO{s['no'][0]*100:+.1f} UP{s['up'][0]*100:+.1f}/DN{s['dn'][0]*100:+.1f} "
              f"W1{s['w1'][0]*100:+.1f}/W2{s['w2'][0]*100:+.1f}")
else:
    print("  NONE. No swept cell is positive across both favorite sides AND both regimes AND both weeks.")
print(f"\n# swept {len(SWEEP)} cells (multiple-comparison risk); robust survivors: {len(robust)}")

# =========================================================================== #
# (6) MECHANISM CUT: within a fixed favorite band, does |spot-start| (determinism)
#     drive the underpricing? And is it incremental to the band AND to the YES side?
#     Uses ALL snapshots in band (any ttc) so it isolates determinism, not time.
# =========================================================================== #
DB=[(0,25),(25,50),(50,75),(75,150),(150,1e9)]
def dbn(lo,hi): return f"{int(lo)}-{int(hi) if hi<1e8 else 999}"
for blo,bhi in [(0.85,0.95),(0.90,0.98)]:
    print(f"\n========== (6) DETERMINISM CUT within favorite band {pbname(blo,bhi)}c "
          f"(|spot-start| $ buckets) ==========")
    print(f"{'|dist|$':>9} | {'n':>5} {'meanPx':>7} {'settle%':>8} {'grossGap':>9} {'netTaker':>9} "
          f"| {'YESgap/n':>11} {'NOgap/n':>11}")
    inband=[r for r in recs if blo<=r["mid"]<bhi and r["dist"] is not None]
    for lo,hi in DB:
        v=[r for r in inband if lo<=abs(r["dist"])<hi]
        if len(v)<20:
            print(f"{dbn(lo,hi):>9} | {len(v):>5} (thin)"); continue
        sr=mean([r["win"] for r in v]); px=mean([r["mid"] for r in v])
        gg=(sr-px)*100; nt=(sr-mean([r["ask"] for r in v])-mean([r["fee"] for r in v]))*100
        ys=[r for r in v if r["fav"]=="YES"]; ns=[r for r in v if r["fav"]=="NO"]
        yg=(mean([r["win"] for r in ys])-mean([r["mid"] for r in ys]))*100 if len(ys)>=10 else None
        ng=(mean([r["win"] for r in ns])-mean([r["mid"] for r in ns]))*100 if len(ns)>=10 else None
        ys_s=f"{yg:+.1f}/{len(ys):<4}" if yg is not None else f"  -/{len(ys):<4}"
        ns_s=f"{ng:+.1f}/{len(ns):<4}" if ng is not None else f"  -/{len(ns):<4}"
        print(f"{dbn(lo,hi):>9} | {len(v):>5} {px*100:>6.1f}c {sr*100:>7.1f}% {gg:>+8.1f} {nt:>+8.1f} "
              f"| {ys_s:>11} {ns_s:>11}")

# =========================================================================== #
# (A) FORWARD-ONLY OUT-OF-SAMPLE test of the credible cell
#     rule: enter favorite when ttc<180 AND mid in [0.85,0.95) AND |dist|>$75
#     in-sample = day <= cutoff ; forward = day > cutoff  (last night's post-06-11 boundary)
# =========================================================================== #
CUT="2026-06-11"
def entries_dt(T,lo,hi,X,pred):
    out=[]
    for tk,bk in store.items():
        if not pred(window_date(tk)): continue
        for r in sorted([r for r in bk.values() if r["ttc"]<T], key=lambda r:-r["ttc"]):
            if lo<=r["mid"]<hi and (X<=0 or (r["dist"] is not None and abs(r["dist"])>X)):
                out.append(r); break
    return out
print("\n========== (A) FORWARD-ONLY OOS: rule T<180, 85-95c, |dist|>$75 (cutoff "+CUT+") ==========")
ins=summarize(entries_dt(180,0.85,0.95,75,lambda d:d<=CUT))
fwd_e=entries_dt(180,0.85,0.95,75,lambda d:d>CUT)
fwd=summarize(fwd_e)
def line(tag,s):
    if not s: print(f"  {tag}: no trades"); return
    def p(t): v,n=t; return (f"{v*100:+.1f}c/n{n}" if v is not None else f"-/n{n}")
    print(f"  {tag}: n={s['n']} hit={s['hit']*100:.1f}% EVtaker={s['evt']*100:+.2f}c EVmaker={s['evm']*100:+.2f}c "
          f"posdays={s['posd']}/{s['nd']} | YES {p(s['yes'])} NO {p(s['no'])} | UP {p(s['up'])} DN {p(s['dn'])}")
line("IN-SAMPLE (<=06-11)",ins)
line("FORWARD   (>06-11) ",fwd)
if fwd_e:
    byday=defaultdict(list)
    for r in fwd_e: byday[r["day"]].append(ev_taker(r))
    print("  forward per-day EV(taker): " + "  ".join(f"{d}:{mean(v)*100:+.1f}c(n{len(v)})" for d,v in sorted(byday.items())))
    print("  forward windows by date: " + ", ".join(f"{d}={sum(1 for r in fwd_e if r['day']==d)}" for d in sorted({r['day'] for r in fwd_e})))

# =========================================================================== #
# (B) VOL-NORMALIZED Z determinism cut + entry sweep
# =========================================================================== #
print("\n========== (B) DETERMINISM CUT by |z| (vol-normalized sigmas) ==========")
ZB=[(0,0.5),(0.5,1.0),(1.0,1.5),(1.5,2.5),(2.5,99)]
for blo,bhi in [(0.85,0.95),(0.90,0.98)]:
    print(f"-- favorite band {pbname(blo,bhi)}c --")
    print(f"{'|z|':>9} | {'n':>5} {'meanPx':>7} {'settle%':>8} {'grossGap':>9} {'netTaker':>9} | {'YESgap/n':>11} {'NOgap/n':>11}")
    inband=[r for r in recs if blo<=r["mid"]<bhi and r["z"] is not None]
    for lo,hi in ZB:
        v=[r for r in inband if lo<=abs(r["z"])<hi]
        if len(v)<20: print(f"{lo:>4}-{hi:<4} | {len(v):>5} (thin)"); continue
        sr=mean([r["win"] for r in v]); px=mean([r["mid"] for r in v])
        gg=(sr-px)*100; nt=(sr-mean([r["ask"] for r in v])-mean([r["fee"] for r in v]))*100
        ys=[r for r in v if r["fav"]=="YES"]; ns=[r for r in v if r["fav"]=="NO"]
        yg=(mean([r["win"] for r in ys])-mean([r["mid"] for r in ys]))*100 if len(ys)>=10 else None
        ng=(mean([r["win"] for r in ns])-mean([r["mid"] for r in ns]))*100 if len(ns)>=10 else None
        yss=f"{yg:+.1f}/{len(ys):<4}" if yg is not None else f"-/{len(ys):<4}"
        nss=f"{ng:+.1f}/{len(ns):<4}" if ng is not None else f"-/{len(ns):<4}"
        print(f"{lo:>4}-{hi:<4} | {len(v):>5} {px*100:>6.1f}c {sr*100:>7.1f}% {gg:>+8.1f} {nt:>+8.1f} | {yss:>11} {nss:>11}")

print("\n========== (B) ENTRY SWEEP with |z|>Z filter (net EV taker/maker, splits) ==========")
def entries_z(T,lo,hi,Z):
    out=[]
    for tk,bk in store.items():
        for r in sorted([r for r in bk.values() if r["ttc"]<T], key=lambda r:-r["ttc"]):
            if lo<=r["mid"]<hi and (Z<=0 or (r["z"] is not None and abs(r["z"])>Z)):
                out.append(r); break
    return out
print(f"{'T<':>4} {'band':>9} {'|z|>':>5} | {'n':>4} {'hit':>6} {'EVtak':>7} {'EVmak':>7} {'+days':>7} | "
      f"{'YES':>6} {'NO':>6} | {'UP':>6} {'DN':>6} | {'W1':>6} {'W2':>6}")
SWEEPZ=[]
for T in (120,180,300):
    for lo,hi in [(0.80,0.90),(0.85,0.95),(0.90,0.98),(0.95,0.995)]:
        for Z in (0,0.5,1.0,1.5):
            s=summarize(entries_z(T,lo,hi,Z))
            if not s or s["n"]<20: continue
            SWEEPZ.append((T,lo,hi,Z,s))
            def p1(t): v,_=t; return f"{v*100:+5.1f}" if v is not None else "   - "
            print(f"{T:>4} {pbname(lo,hi):>9} {Z:>5.1f} | {s['n']:>4} {s['hit']*100:>5.1f}% {s['evt']*100:>+6.1f} "
                  f"{s['evm']*100:>+6.1f} {s['posd']:>3}/{s['nd']:<3} | {p1(s['yes'])} {p1(s['no'])} | "
                  f"{p1(s['up'])} {p1(s['dn'])} | {p1(s['w1'])} {p1(s['w2'])}")
robustz=[]
for T,lo,hi,Z,s in SWEEPZ:
    def ok(t): return t[0] is not None and t[0]>0 and t[1]>=8
    if (s["evt"]>0 and ok(s["yes"]) and ok(s["no"]) and ok(s["up"]) and ok(s["dn"]) and ok(s["w1"]) and ok(s["w2"])
            and s["posd"]/max(s["nd"],1)>=0.55):
        robustz.append((T,lo,hi,Z,s))
print(f"\n# (B) swept {len(SWEEPZ)} z-cells; robust survivors: {len(robustz)}")
for T,lo,hi,Z,s in sorted(robustz,key=lambda z:-z[4]["evt"]):
    print(f"  ROBUST-Z: T<{T} band {pbname(lo,hi)}c |z|>{Z}: EVtaker {s['evt']*100:+.1f}c EVmaker {s['evm']*100:+.1f}c "
          f"n={s['n']} hit={s['hit']*100:.1f}% days {s['posd']}/{s['nd']}")

