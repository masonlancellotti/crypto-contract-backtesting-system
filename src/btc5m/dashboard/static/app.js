"use strict";
/* Kalshi Microstructure Lab dashboard — vanilla JS, hand-rolled SVG charts.
   All data comes from committed artifacts via the /api/* endpoints. */

const C = {
  market: "#c17a30", modelA: "#3987e5", modelB: "#d55181",
  pos: "#3fb950", neg: "#e06054", warn: "#d9a021",
  ink: "#e6edf3", ink2: "#aeb9c4", muted: "#7d8894",
  grid: "#252d38", baseline: "#37414d",
};
const SVGNS = "http://www.w3.org/2000/svg";
const $ = (s, r = document) => r.querySelector(s);
const el = (t, a = {}, kids = []) => {
  const n = document.createElement(t);
  for (const k in a) { if (k === "class") n.className = a[k]; else if (k === "html") n.innerHTML = a[k]; else n.setAttribute(k, a[k]); }
  (Array.isArray(kids) ? kids : [kids]).forEach(c => c != null && n.append(c.nodeType ? c : document.createTextNode(c)));
  return n;
};
const s = (t, a = {}) => { const n = document.createElementNS(SVGNS, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
const fmt = (v, d = 2) => (v == null || Number.isNaN(v)) ? "–" : (+v).toFixed(d);
const signed = (v, d = 2) => (v == null) ? "–" : (v >= 0 ? "+" : "") + (+v).toFixed(d);

const tip = $("#tip");
function showTip(evt, html) { tip.innerHTML = html; tip.style.display = "block"; tip.style.maxWidth = "260px"; tip.style.whiteSpace = "normal"; tip.style.left = Math.min(evt.clientX + 14, window.innerWidth - 280) + "px"; tip.style.top = (evt.clientY + 16) + "px"; }
function hideTip() { tip.style.display = "none"; }

async function api(path) { const r = await fetch(path); if (!r.ok) throw new Error(path + " -> " + r.status); return r.json(); }

// ---- plain-language layer: glossary decode + explainer cards ---- //
let GLOSSARY = {};
function richText(str) {
  // split on [[Term]] markers -> plain text + decoded term chips (safe, no HTML regex)
  const frag = document.createDocumentFragment();
  String(str).split(/(\[\[[^\]]+\]\])/).forEach(part => {
    const m = part.match(/^\[\[([^\]]+)\]\]$/);
    if (m) {
      const [disp, keyRaw] = m[1].split("|");
      const key = (keyRaw || disp).trim();
      const def = GLOSSARY[key] || GLOSSARY[key.toUpperCase()] || GLOSSARY[key.toLowerCase()] || "";
      const sp = el("span", { class: "term", tabindex: "0", "data-def": def, role: "button", "aria-label": disp + ": " + def }, disp);
      frag.append(sp);
    } else if (part) {
      frag.append(document.createTextNode(part));
    }
  });
  return frag;
}
function richP(cls, str) { const p = el("p", { class: cls }); p.append(richText(str)); return p; }
function explainer(str) {
  const box = el("div", { class: "explainer" }, [el("span", { class: "eyicon", "aria-hidden": "true" }, "?")]);
  const body = el("div", {}); body.append(el("b", {}, "What am I looking at? "), richText(str));
  box.append(body);
  return box;
}
// delegated tooltip for decoded terms (hover, focus, tap)
function bindTerm(node, evt) { const def = node.getAttribute("data-def"); if (def) showTip(evt, `<b>${node.textContent}</b> — ${def}`); }
document.addEventListener("mouseover", e => { const t = e.target.closest(".term"); if (t) bindTerm(t, e); });
document.addEventListener("mouseout", e => { if (e.target.closest(".term")) hideTip(); });
document.addEventListener("focusin", e => { const t = e.target.closest(".term"); if (t) { const r = t.getBoundingClientRect(); bindTerm(t, { clientX: r.left, clientY: r.bottom }); } });
document.addEventListener("focusout", e => { if (e.target.closest(".term")) hideTip(); });

// --------------------------------------------------------------------------- //
//  chart primitives                                                           //
// --------------------------------------------------------------------------- //
function axes(svg, x0, y0, w, h, opts = {}) {
  // baseline + optional gridlines with labels (y: value fractions)
  const g = s("g");
  (opts.yticks || []).forEach(t => {
    const yy = y0 + h - t.f * h;
    g.append(s("line", { x1: x0, y1: yy, x2: x0 + w, y2: yy, stroke: C.grid, "stroke-width": t.strong ? 1.4 : 1, "stroke-dasharray": t.strong ? "" : "3 4" }));
    const lab = s("text", { x: x0 - 8, y: yy + 3.5, "text-anchor": "end", "font-size": 10 }); lab.textContent = t.label; g.append(lab);
  });
  (opts.xticks || []).forEach(t => {
    const xx = x0 + t.f * w;
    if (t.line) g.append(s("line", { x1: xx, y1: y0, x2: xx, y2: y0 + h, stroke: t.strong ? C.baseline : C.grid, "stroke-width": 1, "stroke-dasharray": t.strong ? "4 3" : "3 4" }));
    const lab = s("text", { x: xx, y: y0 + h + 15, "text-anchor": t.anchor || "middle", "font-size": 10 }); lab.textContent = t.label; g.append(lab);
  });
  svg.append(g);
}

function reliabilityChart(series) {
  // series: [{name,color,points:[{mean_pred,mean_actual,count}]}]
  const W = 460, H = 380, m = { l: 42, r: 16, t: 12, b: 30 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
  const X = v => m.l + v * w, Y = v => m.t + h - v * h;
  const ticks = [0, .25, .5, .75, 1].map(f => ({ f, label: f.toFixed(2) }));
  axes(svg, m.l, m.t, w, h, { yticks: ticks, xticks: ticks.map(t => ({ ...t })) });
  // 45deg reference
  svg.append(s("line", { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), stroke: C.baseline, "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
  const refl = s("text", { x: X(0.82), y: Y(0.9), "font-size": 10, fill: C.muted }); refl.textContent = "perfect"; svg.append(refl);
  series.forEach(se => {
    if (!se.points || !se.points.length) return;
    const pts = se.points.slice().sort((a, b) => a.mean_pred - b.mean_pred);
    let d = "";
    pts.forEach((p, i) => { d += (i ? "L" : "M") + X(p.mean_pred) + " " + Y(p.mean_actual) + " "; });
    svg.append(s("path", { d, fill: "none", stroke: se.color, "stroke-width": 2, "stroke-linejoin": "round", opacity: se.dashed ? 0.9 : 1, "stroke-dasharray": se.dashed ? "6 4" : "" }));
    pts.forEach(p => {
      const c = s("circle", { cx: X(p.mean_pred), cy: Y(p.mean_actual), r: 4.2, fill: se.color, stroke: C.surface || "#151b23", "stroke-width": 1.5 });
      c.addEventListener("mousemove", e => showTip(e, `<b style="color:${se.color}">${se.name}</b><br>pred ${fmt(p.mean_pred)} → actual ${fmt(p.mean_actual)}<br>n=${p.count}`));
      c.addEventListener("mouseleave", hideTip);
      svg.append(c);
    });
  });
  const yl = s("text", { x: -H / 2 + 30, y: 13, transform: "rotate(-90)", "font-size": 10 }); yl.textContent = "observed frequency"; svg.append(yl);
  const xl = s("text", { x: m.l + w / 2, y: H - 2, "text-anchor": "middle", "font-size": 10 }); xl.textContent = "predicted probability"; svg.append(xl);
  return svg;
}

function eceBars(rows) {
  // rows: [{model,ece}] lower is better; market lowest highlighted
  const W = 460, H = 200, m = { l: 130, r: 40, t: 8, b: 24 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  const max = Math.max(...rows.map(r => r.ece || 0)) * 1.15 || 0.15;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  const bh = Math.min(30, h / rows.length - 8);
  rows.forEach((r, i) => {
    const y = m.t + i * (h / rows.length) + (h / rows.length - bh) / 2;
    const ww = (r.ece || 0) / max * w;
    const col = r.model === "market_implied" ? C.market : (i % 2 ? C.modelB : C.modelA);
    svg.append(s("rect", { x: m.l, y, width: Math.max(2, ww), height: bh, rx: 3, fill: col, opacity: 0.92 }));
    const lab = s("text", { x: m.l - 10, y: y + bh / 2 + 4, "text-anchor": "end", "font-size": 11, fill: C.ink2 }); lab.textContent = r.model; svg.append(lab);
    const val = s("text", { x: m.l + ww + 8, y: y + bh / 2 + 4, "font-size": 11, fill: C.ink }); val.textContent = fmt(r.ece, 3); svg.append(val);
  });
  return svg;
}

function feeBars(models) {
  // horizontal signed net-PnL bars per model with fee burden marked
  const W = 560, H = 44 + models.length * 52, m = { l: 130, r: 60, t: 20, b: 24 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  const vals = models.flatMap(x => [x.gross_pnl || 0, x.net_pnl || 0]);
  const lo = Math.min(0, ...vals) * 1.15, hi = Math.max(0, ...vals) * 1.15 || 1;
  const span = (hi - lo) || 1;
  const X = v => m.l + (v - lo) / span * w;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  svg.append(s("line", { x1: X(0), y1: m.t - 6, x2: X(0), y2: m.t + h, stroke: C.baseline, "stroke-width": 1.2 }));
  const z = s("text", { x: X(0), y: m.t - 10, "text-anchor": "middle", "font-size": 10, fill: C.muted }); z.textContent = "0"; svg.append(z);
  models.forEach((mo, i) => {
    const y = m.t + i * 52 + 6;
    const gross = mo.gross_pnl || 0, net = mo.net_pnl || 0;
    // gross bar (faint), net bar (solid, signed color)
    const gx0 = X(Math.min(0, gross)), gx1 = X(Math.max(0, gross));
    svg.append(s("rect", { x: gx0, y, width: Math.max(1.5, gx1 - gx0), height: 12, rx: 2, fill: C.muted, opacity: 0.35 }));
    const nx0 = X(Math.min(0, net)), nx1 = X(Math.max(0, net));
    svg.append(s("rect", { x: nx0, y: y + 15, width: Math.max(1.5, nx1 - nx0), height: 16, rx: 3, fill: net >= 0 ? C.pos : C.neg }));
    // fee wedge: from gross to net
    if (mo.fee_burden) {
      svg.append(s("line", { x1: X(gross), y1: y + 6, x2: X(net), y2: y + 6, stroke: C.warn, "stroke-width": 2, "stroke-dasharray": "2 2" }));
    }
    const lab = s("text", { x: m.l - 12, y: y + 22, "text-anchor": "end", "font-size": 11.5, fill: C.ink2 }); lab.textContent = mo.model; svg.append(lab);
    const val = s("text", { x: (net >= 0 ? nx1 + 8 : nx0 - 8), y: y + 27, "text-anchor": net >= 0 ? "start" : "end", "font-size": 11.5, fill: net >= 0 ? C.pos : C.neg }); val.textContent = signed(net) + "c"; svg.append(val);
  });
  // legend row
  const lg = s("g", { transform: `translate(${m.l},${H - 6})` });
  const mk = (x, col, t, faint) => { lg.append(s("rect", { x, y: -8, width: 12, height: 8, rx: 2, fill: col, opacity: faint ? 0.35 : 1 })); const tx = s("text", { x: x + 17, y: -1, "font-size": 10, fill: C.muted }); tx.textContent = t; lg.append(tx); };
  mk(0, C.muted, "gross", true); mk(90, C.neg, "net after fees");
  svg.append(lg);
  return svg;
}

function foldChart(folds) {
  if (!folds || !folds.length) return el("div", { class: "empty" }, "no walk-forward folds");
  const W = 300, H = 150, m = { l: 30, r: 12, t: 12, b: 26 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  const vals = folds.map(f => f.net_pnl);
  const lo = Math.min(0, ...vals) * 1.2, hi = Math.max(0, ...vals) * 1.2 || 1, span = (hi - lo) || 1;
  const Y = v => m.t + h - (v - lo) / span * h;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  svg.append(s("line", { x1: m.l, y1: Y(0), x2: m.l + w, y2: Y(0), stroke: C.baseline }));
  const bw = w / folds.length * 0.5;
  folds.forEach((f, i) => {
    const cx = m.l + (i + 0.5) * (w / folds.length);
    const y0 = Y(0), y1 = Y(f.net_pnl);
    svg.append(s("rect", { x: cx - bw / 2, y: Math.min(y0, y1), width: bw, height: Math.abs(y1 - y0) || 1.5, rx: 2, fill: f.net_pnl >= 0 ? C.pos : C.neg }));
    const lab = s("text", { x: cx, y: H - 8, "text-anchor": "middle", "font-size": 10 }); lab.textContent = "f" + f.fold; svg.append(lab);
  });
  return svg;
}

// --------------------------------------------------------------------------- //
//  views                                                                      //
// --------------------------------------------------------------------------- //
const views = {};

views.overview = async () => {
  const d = await api("/api/overview");
  GLOSSARY = d.glossary || GLOSSARY;
  const wrap = el("div", { class: "view" });
  const story = d.plain_story || {};
  // plain-English hero: the whole story in 10 seconds
  const hero = el("div", { class: "hero" });
  hero.append(el("div", { class: "eyebrow" }, "Kalshi 15-minute BTC market · research finding"));
  hero.append(el("h1", { class: "hero-title" }, story.headline || "The market is the best forecaster we measured."));
  const story_col = el("div", { class: "hero-body" });
  (story.paragraphs || []).forEach(p => story_col.append(el("p", {}, p)));
  hero.append(story_col);
  const scoreline = el("div", { class: "scoreline" }, [
    el("div", { class: "score" }, [el("span", { class: "n" }, "38"), el("span", { class: "l" }, "ideas tested")]),
    el("div", { class: "score" }, [el("span", { class: "n" }, "1"), el("span", { class: "l" }, "survived the stats")]),
    el("div", { class: "score neg" }, [el("span", { class: "n" }, "0"), el("span", { class: "l" }, "worth trading")]),
  ]);
  hero.append(scoreline);
  wrap.append(hero);

  wrap.append(el("h2", { class: "section-label" }, "The finding in six numbers"));
  const tiles = el("div", { class: "tiles" });
  (d.tiles || []).forEach((t) => {
    const cls = t.key === "market_implied_window_ece" ? "accent" : (t.key === "bankable_edges" ? "neg" : (t.key === "gauntlet_survivors" ? "pos" : ""));
    const tile = el("div", { class: "tile " + cls }, [
      el("div", { class: "plabel" }, t.plain || t.label),
      el("div", { class: "value", html: `${t.value}<small>${t.unit || ""}</small>` }),
      el("div", { class: "cap" }, t.caption || ""),
    ]);
    if (t.explain) {
      const det = el("details", { class: "tile-more" });
      det.append(el("summary", {}, t.label));
      det.append(el("div", { class: "explain" }, t.explain));
      det.append(el("div", { class: "src" }, "source: " + (t.source || "")));
      tile.append(det);
    }
    tiles.append(tile);
  });
  wrap.append(tiles);

  const row = el("div", { class: "grid cols-2", style: "margin-top:26px" });
  // verdict breakdown
  const VMEAN = { NEGATIVE: "tested — no edge after costs", OPEN: "promising — needs more data", INFRA: "a tool we built, not an edge claim", RESOLVED: "question answered / characterized", PARKED: "set aside, restorable from git" };
  const vb = el("div", { class: "panel" });
  vb.append(el("h2", {}, "How the 38 ideas resolved"));
  vb.append(el("div", { class: "hint" }, "Every idea got an honest verdict. Most were tested and closed as no-edge."));
  const total = (d.verdict_breakdown || []).reduce((a, b) => a + b.count, 0);
  const vcol = { NEGATIVE: C.neg, OPEN: C.warn, INFRA: C.info, RESOLVED: C.teal, PARKED: C.violet };
  const bar = el("div", { class: "stackbar", role: "img", "aria-label": "verdict breakdown" });
  (d.verdict_breakdown || []).forEach(v => bar.append(el("div", { style: `width:${v.count / total * 100}%;background:${vcol[v.verdict] || C.muted}`, title: `${v.verdict}: ${v.count}` })));
  vb.append(bar);
  (d.verdict_breakdown || []).forEach(v => vb.append(el("div", { class: "vrow" }, [
    el("span", { class: "chip", "data-v": v.verdict }, [el("span", { class: "dot" }), v.verdict]),
    el("span", { class: "vmean" }, VMEAN[v.verdict] || ""),
    el("span", { class: "num vcount" }, String(v.count)),
  ])));
  row.append(vb);
  // fees kill alpha
  const fk = d.fees_kill_alpha || {};
  const fp = el("div", { class: "panel" });
  fp.append(el("h2", {}, fk.headline || "Fees kill the alpha"));
  fp.append(el("div", { class: "hint" }, fk.plain || fk.detail || ""));
  const ft = el("table", { class: "data" });
  ft.append(el("thead", {}, el("tr", {}, [el("th", {}, "baseline"), el("th", { class: "num" }, "net (c)"), el("th", { class: "num" }, "per-contract"), el("th", { class: "num" }, "trades")])));
  const tb = el("tbody");
  (fk.sample_backtest || []).forEach(r => tb.append(el("tr", {}, [
    el("td", {}, r.model),
    el("td", { class: "num " + (r.net_pnl_cents < 0 ? "neg-t" : "") }, signed(r.net_pnl_cents)),
    el("td", { class: "num" }, r.per_contract_cents == null ? "–" : signed(r.per_contract_cents, 3)),
    el("td", { class: "num" }, String(r.trades)),
  ])));
  ft.append(tb); fp.append(el("div", { class: "tbl-wrap" }, ft));
  fp.append(el("div", { class: "source", html: "Source: <b>" + (fk.source || "") + "</b>" }));
  row.append(fp);
  wrap.append(row);
  const caveat = el("div", { class: "callout", style: "margin-top:26px" });
  caveat.append(el("h3", {}, "Why the one survivor still isn't tradeable"));
  caveat.append(richP("", "The surviving trade buys near-certain favorites and pockets 2 to 4 cents almost every time. It passed the [[Deflated Sharpe Ratio]] (0.998), the [[PBO]] overfitting check (0.00), and a [[sealed holdout]] it had never seen. But it is selling insurance: when the favorite loses, the loss is about 96 cents. That rare huge loss never appeared in the small winning sample, so the statistics couldn't see it. Real and repeatable, but a penny in front of a steamroller."));
  wrap.append(caveat);
  wrap.append(el("blockquote", { class: "quote", style: "margin-top:26px" }, d.verdict_of_the_lab || ""));
  return wrap;
};

views.calibration = async () => {
  const d = await api("/api/calibration");
  const wrap = el("div", { class: "view" });
  const head = el("div", { class: "view-head" }, [
    el("div", { class: "eyebrow" }, "Calibration"),
    el("h1", {}, "Whose odds are right most often?"),
  ]);
  head.append(richP("", "A forecaster is [[well-calibrated|calibration]] if the things it calls 70% likely happen about 70% of the time. We score that with [[ECE]] — lower is better. The finding: the market's own price is the best-calibrated forecaster here, and no model we trained beat it."));
  wrap.append(head);
  wrap.append(explainer("A [[reliability diagram]] plots what a forecaster predicted (left–right) against what actually happened (up–down). A perfect forecaster sits on the dashed diagonal. The amber market line hugs it; the model lines stray off it."));
  const row = el("div", { class: "grid cols-2" });
  // reliability
  const rp = el("div", { class: "panel" });
  rp.append(el("h2", {}, "Reliability diagram"));
  rp.append(el("div", { class: "hint" }, "Market-implied computed live from the committed 95-window sample; the model curves are the committed raw-vs-isotonic buckets."));
  const legend = el("div", { class: "legend" }, [
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.market}` }), "market-implied (sample)"]),
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.modelA}` }), "model (raw)"]),
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.modelB};border-bottom:2px dashed ${C.modelB}` }), "model (isotonic)"]),
  ]);
  rp.append(legend);
  const mr = d.market_reliability || {}, iso = d.isotonic || {};
  rp.append(reliabilityChart([
    { name: "market-implied", color: C.market, points: mr.points || [] },
    { name: "model raw", color: C.modelA, points: (iso.before || []).map(p => ({ mean_pred: p.mean_pred, mean_actual: p.mean_actual, count: p.count })) },
    { name: "model isotonic", color: C.modelB, dashed: true, points: (iso.after || []).map(p => ({ mean_pred: p.mean_pred, mean_actual: p.mean_actual, count: p.count })) },
  ]));
  rp.append(el("div", { class: "source", html: `Sources: <b>sample_data/features + labels</b> (market curve, live), <b>${iso.source || ""}</b> (model curves)` }));
  row.append(rp);
  // ECE panel
  const ep = el("div", { class: "panel" });
  ep.append(el("h2", {}, "Expected calibration error"));
  ep.append(el("div", { class: "hint" }, "Per-model ECE on the executable-backtest candidate rows — market-implied is lowest."));
  ep.append(eceBars((d.backtest_calibration || []).map(r => ({ model: r.model, ece: r.ece })).sort((a, b) => a.ece - b.ece)));
  const he = d.headline_ece || {};
  ep.append(el("div", { class: "callout", style: "margin-top:16px;border-left-color:" + C.market }, [
    el("h3", { style: "color:" + C.market }, "Full-corpus window-level ECE"),
    el("p", { html: `Market-implied <b class="num" style="color:${C.ink}">${fmt(he.market_implied, 3)}</b> vs best trained model <b class="num" style="color:${C.ink}">${fmt(he.best_model, 3)}+</b> across distinct 15-minute windows.` }),
  ]));
  ep.append(el("div", { class: "source", html: "Source: <b>sample_data/expected/kalshi_baseline_backtest.md</b>; corpus figures <b>docs/RESEARCH_LEDGER.md leg 3</b>" }));
  row.append(ep);
  wrap.append(row);

  // per-coin ECE (multi-coin sample)
  const byCoin = d.market_by_coin || [];
  if (byCoin.length > 1) {
    const cp = el("div", { class: "panel", style: "margin-top:16px" });
    cp.append(el("h2", {}, "Market-implied calibration by coin"));
    cp.append(el("div", { class: "hint" }, "The market's own price is the best-calibrated forecaster on every coin in the sample, not just Bitcoin. Lower ECE is better."));
    const t = el("table", { class: "data" });
    t.append(el("thead", {}, el("tr", {}, [el("th", {}, "coin"), el("th", { class: "num" }, "sample rows"), el("th", { class: "num" }, "market-implied ECE")])));
    const tb = el("tbody");
    byCoin.forEach(c => tb.append(el("tr", {}, [
      el("td", {}, el("b", {}, c.coin)),
      el("td", { class: "num" }, String(c.n)),
      el("td", { class: "num" }, fmt(c.ece, 3)),
    ])));
    t.append(tb); cp.append(el("div", { class: "tbl-wrap" }, t));
    cp.append(el("div", { class: "source", html: "Source: <b>sample_data/features + labels</b> (computed live, pooled across coins)" }));
    wrap.append(cp);
  }

  // before/after metrics table
  const cr = d.calibration_report || {};
  if (cr.metrics) {
    const mp = el("div", { class: "panel", style: "margin-top:16px" });
    mp.append(el("h2", {}, "Sample isotonic calibration — before vs after"));
    mp.append(el("div", { class: "hint" }, `method: ${cr.method || "isotonic"} — fit on held-out, purged/embargoed windows (diagnostic-only; below the 150-window gate).`));
    const t = el("table", { class: "data" });
    t.append(el("thead", {}, el("tr", {}, [el("th", {}, "metric"), el("th", { class: "num" }, "before (raw)"), el("th", { class: "num" }, "after (calibrated)")])));
    const tb = el("tbody");
    ["ece", "brier", "log_loss", "slope", "intercept"].forEach(k => { const m = cr.metrics[k]; if (m) tb.append(el("tr", {}, [el("td", {}, k.toUpperCase()), el("td", { class: "num" }, fmt(m.before, 4)), el("td", { class: "num" }, fmt(m.after, 4))])); });
    t.append(tb); mp.append(el("div", { class: "tbl-wrap" }, t));
    mp.append(el("div", { class: "source", html: "Source: <b>" + (cr.source || "") + "</b>" }));
    wrap.append(mp);
  }
  return wrap;
};

let LEDGER = null, filterV = "ALL", filterQ = "";
views.research = async () => {
  const d = LEDGER || (LEDGER = await api("/api/ledger"));
  const wrap = el("div", { class: "view wide" });
  wrap.append(el("div", { class: "view-head" }, [
    el("div", { class: "eyebrow" }, "Research Map"),
    el("h1", {}, "Every idea we tried, and how it ended"),
    el("p", {}, "Each row is one trading idea: what was tested, the key number, and the verdict. Filter or search, and click any row for the plain detail. Verdicts: red = tested with no edge after costs, amber = still open pending more data, blue = a tool we built, teal = a question we answered, violet = set aside."),
  ]));
  const counts = {}; d.legs.forEach(l => counts[l.verdict] = (counts[l.verdict] || 0) + 1);
  const controls = el("div", { class: "controls" });
  const search = el("input", { type: "search", placeholder: "filter hypothesis / method / stat…", value: filterQ });
  search.addEventListener("input", e => { filterQ = e.target.value.toLowerCase(); renderRows(); });
  controls.append(search);
  const mkBtn = (v, label) => { const b = el("button", { class: "filter-btn" + (filterV === v ? " active" : "") }, [label, v === "ALL" ? null : el("span", { class: "c" }, String(counts[v] || 0))]); b.addEventListener("click", () => { filterV = v; renderRows(); [...controls.querySelectorAll(".filter-btn")].forEach(x => x.classList.remove("active")); b.classList.add("active"); }); return b; };
  controls.append(mkBtn("ALL", "all"));
  ["NEGATIVE", "OPEN", "INFRA", "RESOLVED", "PARKED"].forEach(v => { if (counts[v]) controls.append(mkBtn(v, v.toLowerCase())); });
  wrap.append(controls);

  const panel = el("div", { class: "panel", style: "padding:0;overflow:hidden" });
  const tw = el("div", { class: "tbl-wrap" });
  const table = el("table", { class: "data" });
  table.append(el("thead", {}, el("tr", {}, [el("th", {}, "#"), el("th", {}, "Hypothesis"), el("th", {}, "Key statistic"), el("th", {}, "Verdict")])));
  const tbody = el("tbody");
  table.append(tbody); tw.append(table); panel.append(tw); wrap.append(panel);

  function renderRows() {
    tbody.innerHTML = "";
    const rows = d.legs.filter(l => (filterV === "ALL" || l.verdict === filterV) &&
      (!filterQ || (l.title + " " + l.where + " " + l.key_stat + " " + l.result).toLowerCase().includes(filterQ)));
    if (!rows.length) { tbody.append(el("tr", {}, el("td", { colspan: 4, class: "empty" }, "No legs match."))); return; }
    rows.forEach(l => {
      const tr = el("tr", { class: "leg-row" }, [
        el("td", { class: "id" }, String(l.id)),
        el("td", {}, el("b", {}, l.title)),
        el("td", { class: "mono", style: "color:var(--ink-2);font-size:12px" }, l.key_stat),
        el("td", {}, el("span", { class: "chip", "data-v": l.verdict }, [el("span", { class: "dot" }), l.verdict])),
      ]);
      let open = false; let detail = null;
      tr.addEventListener("click", () => {
        open = !open;
        if (open) {
          detail = el("tr", { class: "leg-detail" }, el("td", { colspan: 4 }, [
            el("div", { html: l.result }),
            el("div", { style: "margin-top:8px" }, [el("span", { class: "kv" }, "where "), l.where]),
            el("div", { html: `<span class="kv">status </span>${l.status_raw}` }),
            el("div", { html: `<span class="kv">source </span>${d.source_doc} · leg ${l.ledger_leg}` }),
          ]));
          tr.after(detail);
        } else if (detail) { detail.remove(); }
      });
      tbody.append(tr);
    });
  }
  renderRows();
  return wrap;
};

views.backtest = async () => {
  const d = await api("/api/backtest");
  const wrap = el("div", { class: "view" });
  const bhead = el("div", { class: "view-head" }, [
    el("div", { class: "eyebrow" }, "Backtest"),
    el("h1", {}, "What happens when you actually trade the models?"),
  ]);
  bhead.append(richP("", `We replay each model over the sample and fill its trades at the real price you could have gotten — an [[executable backtest]] buys at the [[ask|taker]] price, never an optimistic mid-price, and then subtracts fees. The verdict below: gross profit that looks positive turns net-negative once the ${d.gate_windows ?? ""}-window sample pays its costs. Diagnostic only — not a profitability claim.`));
  wrap.append(bhead);
  wrap.append(explainer("Each bar shows a model's profit and loss in cents. The faint bar is gross (before costs); the solid bar is net (after fees). Amber dashes mark the fee bite that drags gross into the red."));
  if (!d.models || !d.models.length) { wrap.append(el("div", { class: "empty" }, [el("b", {}, "Backtest report not found. "), "Run the dashboard from the repo root so it can read sample_data/expected/."])); return wrap; }
  const top = el("div", { class: "grid cols-2" });
  const fp = el("div", { class: "panel" });
  fp.append(el("h2", {}, "Net P&L per baseline"));
  fp.append(el("div", { class: "hint" }, "Faint bar = gross; solid = net after fees. Amber dashes mark the fee burden that pulls gross into the red."));
  fp.append(feeBars(d.models));
  top.append(fp);
  const wf = el("div", { class: "panel" });
  wf.append(el("h2", {}, "Walk-forward stability"));
  wf.append(el("div", { class: "hint" }, "Per-fold net P&L for distance/time/vol — signs flip across folds (regime luck, not edge)."));
  const dtv = d.models.find(m => m.model === "distance_time_vol");
  wf.append(foldChart(dtv && dtv.walk_forward));
  top.append(wf);
  wrap.append(top);

  const tp = el("div", { class: "panel", style: "margin-top:16px" });
  tp.append(el("h2", {}, "Per-baseline detail"));
  const t = el("table", { class: "data" });
  t.append(el("thead", {}, el("tr", {}, ["baseline", "trades", "gross", "fees", "net", "per-contract", "hit-rate", "profit-factor", "ECE"].map((h, i) => el("th", { class: i ? "num" : "" }, h)))));
  const tb = el("tbody");
  d.models.forEach(m => tb.append(el("tr", {}, [
    el("td", {}, m.model),
    el("td", { class: "num" }, m.trades == null ? "–" : String(m.trades)),
    el("td", { class: "num" }, signed(m.gross_pnl)),
    el("td", { class: "num", style: "color:var(--warn)" }, m.fee_burden == null ? "–" : "−" + fmt(m.fee_burden)),
    el("td", { class: "num " + (m.net_pnl < 0 ? "neg-t" : "pos-t") }, signed(m.net_pnl)),
    el("td", { class: "num" }, m.per_contract == null ? "–" : signed(m.per_contract, 3)),
    el("td", { class: "num" }, fmt(m.hit_rate)),
    el("td", { class: "num" }, fmt(m.profit_factor)),
    el("td", { class: "num" }, fmt(m.ece, 3)),
  ])));
  t.append(tb); tp.append(el("div", { class: "tbl-wrap" }, t));
  tp.append(el("div", { class: "source", html: "Source: <b>" + (d.source || "") + "</b>" }));
  wrap.append(tp);
  return wrap;
};

// ------- replay engine ------- //
let RP = null;
views.replay = async () => {
  const d = RP || (RP = await api("/api/replay"));
  const wrap = el("div", { class: "view wide" });
  const meta = d.meta || {};
  wrap.append(el("div", { class: "view-head" }, [
    el("div", { class: "eyebrow" }, "Replay"),
    el("h1", {}, "Watch one 15-minute bet play out"),
    el("p", { html: `A real recorded window (<span class="num">${meta.market_ticker || ""}</span>): ${(meta.n_book_snapshots_recorded || 0).toLocaleString()} order-book snapshots and ${(meta.n_trade_prints_recorded || 0).toLocaleString()} trades. Press play or drag the slider to move through time, from the market opening to its settlement.` }),
  ]));
  wrap.append(explainer("The chart tracks two probabilities over the 15 minutes: the amber line is the market's live price (the crowd's odds of \"yes\"), and the blue line is a simple physics model's odds based on how far Bitcoin has moved. The grey line is Bitcoin's price versus its starting point. On the left, the order book shows the best buy/sell prices right now, and the three gate lights show whether the data was fresh and deep enough to trust. It all ends at settlement, when the bet is decided."));
  if (!d.frames || !d.frames.length) { wrap.append(el("div", { class: "empty" }, [el("b", {}, "Replay window not found. "), "Run the dashboard from the repo root."])); return wrap; }
  const F = d.frames;

  // probability + spot chart (static paths; playhead moves)
  const chartPanel = el("div", { class: "panel" });
  chartPanel.append(el("div", { class: "legend" }, [
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.market}` }), "market-implied P(yes)"]),
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.modelA}` }), "model P(yes) — Φ(z) physics"]),
    el("span", { class: "item" }, [el("span", { class: "swatch", style: `background:${C.muted}` }), "spot vs start ($)"]),
  ]));
  const CW = 860, CH = 300, mm = { l: 44, r: 52, t: 14, b: 26 };
  const cw = CW - mm.l - mm.r, ch = CH - mm.t - mm.b;
  const t0 = F[0].t_ms, t1 = F[F.length - 1].t_ms, tspan = (t1 - t0) || 1;
  const X = t => mm.l + (t - t0) / tspan * cw;
  const Yp = p => mm.t + ch - p * ch; // prob 0..1
  const dists = F.map(f => f.dist_to_start).filter(v => v != null);
  const dlo = Math.min(...dists), dhi = Math.max(...dists), dspan = (dhi - dlo) || 1;
  const Yd = v => mm.t + ch - (v - dlo) / dspan * ch;
  const svg = s("svg", { viewBox: `0 0 ${CW} ${CH}`, width: "100%", id: "rp-svg" });
  // gridlines prob
  [0, .25, .5, .75, 1].forEach(f => { svg.append(s("line", { x1: mm.l, y1: Yp(f), x2: mm.l + cw, y2: Yp(f), stroke: C.grid, "stroke-width": f === .5 ? 1.3 : 1, "stroke-dasharray": f === .5 ? "5 4" : "3 4" })); const tx = s("text", { x: mm.l - 8, y: Yp(f) + 3.5, "text-anchor": "end", "font-size": 10 }); tx.textContent = f.toFixed(2); svg.append(tx); });
  // settlement marker
  if (meta.close_ms) { const xc = X(meta.close_ms); svg.append(s("line", { x1: xc, y1: mm.t, x2: xc, y2: mm.t + ch, stroke: C.warn, "stroke-width": 1.3, "stroke-dasharray": "4 3", opacity: 0.8 })); const tl = s("text", { x: xc + 4, y: mm.t + 12, "font-size": 10, fill: C.warn }); tl.textContent = "close"; svg.append(tl); }
  const pathFor = (acc, Y) => { let dd = ""; let started = false; F.forEach(f => { const v = acc(f); if (v == null) return; dd += (started ? "L" : "M") + X(f.t_ms) + " " + Y(v) + " "; started = true; }); return dd; };
  svg.append(s("path", { d: pathFor(f => f.dist_to_start, Yd), fill: "none", stroke: C.muted, "stroke-width": 1.4, opacity: 0.6 }));
  svg.append(s("path", { d: pathFor(f => f.p_model, Yp), fill: "none", stroke: C.modelA, "stroke-width": 1.8, opacity: 0.9 }));
  svg.append(s("path", { d: pathFor(f => f.p_market, Yp), fill: "none", stroke: C.market, "stroke-width": 2.2 }));
  const playhead = s("line", { x1: mm.l, y1: mm.t - 4, x2: mm.l, y2: mm.t + ch, stroke: C.ink, "stroke-width": 1.2, opacity: 0.85 });
  svg.append(playhead);
  const dotM = s("circle", { r: 4.5, fill: C.market, stroke: "#151b23", "stroke-width": 1.5 });
  const dotP = s("circle", { r: 4, fill: C.modelA, stroke: "#151b23", "stroke-width": 1.5 });
  svg.append(dotP); svg.append(dotM);
  chartPanel.append(svg);

  // readout + ladder + gates
  const body = el("div", { class: "replay-grid", style: "margin-top:16px" });
  const left = el("div", { class: "panel" });
  left.append(el("h2", {}, "Order book"));
  left.append(el("div", { class: "hint" }, "Best bid/ask per side + resting size (recorded top-of-book)."));
  const ladder = el("div", { class: "ladder", id: "rp-ladder" });
  left.append(ladder);
  const gates = el("div", { class: "gate-lights", id: "rp-gates" });
  ["fresh", "depth_ok", "spot_fresh"].forEach(g => gates.append(el("div", { class: "gate", "data-g": g }, [el("span", { class: "led" }), g.replace("_", " ")])));
  left.append(el("h2", { style: "margin-top:6px;font-size:12px;color:var(--muted)" }, "Gates"));
  left.append(gates);

  const right = el("div", {});
  const readout = el("div", { class: "readout" });
  const rv = {};
  const rItem = (k, key, col) => { const v = el("span", { class: "v", style: col ? "color:" + col : "" }, "–"); rv[key] = v; return el("div", { class: "r" }, [el("span", { class: "k" }, k), v]); };
  readout.append(rItem("P(yes) market", "pm", C.market));
  readout.append(rItem("P(yes) model", "pp", C.modelA));
  readout.append(rItem("spot", "spot"));
  readout.append(rItem("dist to start", "dist"));
  readout.append(rItem("to close", "ttc"));
  right.append(readout);
  right.append(chartPanel);
  // scrubber
  const scr = el("div", { class: "scrubber" });
  const playBtn = el("button", { id: "rp-play", title: "play/pause" }, "▶");
  const range = el("input", { type: "range", min: 0, max: String(F.length - 1), value: "0", id: "rp-range" });
  const clock = el("div", { class: "clock", id: "rp-clock" }, "");
  scr.append(playBtn, range, clock);
  right.append(scr);
  body.append(left, right);
  wrap.append(body);
  wrap.append(el("div", { class: "callout", style: "margin-top:16px;border-left-color:" + (meta.official_result === "yes" ? C.pos : C.neg) }, [
    el("h3", { style: "color:" + (meta.official_result === "yes" ? C.pos : C.neg) }, "Settles " + (meta.official_result || "").toUpperCase()),
    el("p", { html: (meta.rules_excerpt || "").slice(0, 200) + "… Reference: " + (meta.settlement_reference_source || "") }),
  ]));

  // ------- drive it ------- //
  let idx = 0, playing = false, timer = null;
  function ladderRow(cls, label, px, sz) {
    const barW = sz ? Math.min(100, Math.max(6, Math.log10(sz + 1) * 26)) : 0;
    return el("div", { class: "lvl " + cls }, [
      el("span", { class: "px" }, px == null ? "–" : Math.round(px * 100) + "¢"),
      el("div", {}, el("div", { class: "bar", style: `width:${barW}%` })),
      el("span", { class: "sz" }, sz == null ? "" : Math.round(sz).toLocaleString()),
    ]);
  }
  function paint(i) {
    const f = F[i]; if (!f) return;
    const b = f.book;
    ladder.innerHTML = "";
    ladder.append(el("div", { style: "font-family:var(--mono);font-size:10.5px;color:var(--muted);display:flex;justify-content:space-between" }, [el("span", {}, "YES side"), el("span", {}, "size")]));
    ladder.append(ladderRow("ask", "yes ask", b.yes_ask, b.yes_ask_size));
    ladder.append(ladderRow("bid", "yes bid", b.yes_bid, b.yes_bid_size));
    const sp = (b.yes_ask != null && b.yes_bid != null) ? Math.round((b.yes_ask - b.yes_bid) * 100) : null;
    ladder.append(el("div", { class: "spread" }, sp == null ? "spread –" : `spread ${sp}¢ · depth ${b.yes_depth_levels || 0}/${b.no_depth_levels || 0} lvls`));
    ladder.append(el("div", { style: "font-family:var(--mono);font-size:10.5px;color:var(--muted);display:flex;justify-content:space-between;margin-top:2px" }, [el("span", {}, "NO side"), el("span", {}, "size")]));
    ladder.append(ladderRow("ask", "no ask", b.no_ask, b.no_ask_size));
    ladder.append(ladderRow("bid", "no bid", b.no_bid, b.no_bid_size));
    // gates
    [...gates.children].forEach(g => { const on = f.gates[g.dataset.g]; g.classList.toggle("on", !!on); g.classList.toggle("off", !on); });
    // readout
    rv.pm.textContent = f.p_market == null ? "–" : fmt(f.p_market);
    rv.pp.textContent = f.p_model == null ? "–" : fmt(f.p_model);
    rv.spot.textContent = f.spot == null ? "–" : "$" + f.spot.toLocaleString();
    rv.dist.textContent = f.dist_to_start == null ? "–" : signed(f.dist_to_start, 0); rv.dist.style.color = f.dist_to_start >= 0 ? C.pos : C.neg;
    rv.ttc.textContent = f.phase === "settled" ? "settled" : Math.floor(f.sec_to_close / 60) + ":" + String(Math.floor(f.sec_to_close % 60)).padStart(2, "0");
    clock.textContent = (f.phase === "settled" ? "SETTLED · " : "T−") + fmt(f.sec_to_close, 0) + "s";
    // playhead
    const x = X(f.t_ms);
    playhead.setAttribute("x1", x); playhead.setAttribute("x2", x);
    if (f.p_market != null) { dotM.setAttribute("cx", x); dotM.setAttribute("cy", Yp(f.p_market)); dotM.style.display = ""; } else dotM.style.display = "none";
    if (f.p_model != null) { dotP.setAttribute("cx", x); dotP.setAttribute("cy", Yp(f.p_model)); dotP.style.display = ""; } else dotP.style.display = "none";
    range.value = String(i);
  }
  function step() { if (!playing) return; idx = (idx + 1) % F.length; paint(idx); timer = setTimeout(step, 45); }
  playBtn.addEventListener("click", () => { playing = !playing; playBtn.textContent = playing ? "‖" : "▶"; if (playing) { if (idx >= F.length - 1) idx = 0; step(); } else clearTimeout(timer); });
  range.addEventListener("input", e => { playing = false; playBtn.textContent = "▶"; clearTimeout(timer); idx = +e.target.value; paint(idx); });
  paint(0);
  return wrap;
};

// --------------------------------------------------------------------------- //
//  router                                                                     //
// --------------------------------------------------------------------------- //
async function route() {
  const name = (location.hash.replace("#", "") || "overview");
  const fn = views[name] || views.overview;
  [...$("#nav").children].forEach(a => a.classList.toggle("active", a.dataset.view === name));
  const content = $("#content");
  content.innerHTML = '<div class="loading">Loading…</div>';
  try { const node = await fn(); content.innerHTML = ""; content.append(node); }
  catch (e) { content.innerHTML = `<div class="view"><div class="empty">Could not load this view.<br><b>${e.message}</b><br>The dashboard serves committed artifacts only — run from the repo root.</div></div>`; }
  window.scrollTo(0, 0);
}
$("#nav").addEventListener("click", e => { const a = e.target.closest("a"); if (a) location.hash = a.dataset.view; });
window.addEventListener("hashchange", route);
// preload the glossary once so decoded terms work on every view, not just Overview
(async function boot() {
  try { const ov = await api("/api/overview"); GLOSSARY = ov.glossary || {}; } catch (e) { /* offline: terms show without defs */ }
  route();
})();
