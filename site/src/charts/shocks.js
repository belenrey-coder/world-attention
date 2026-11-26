// Chapter 2 · Shocks (docs/SPEC.md, Chapter 2): the 60 widest shocks as step lines, x = 0 to 3 hours from the third
// country, y = countries reached. Step 1: four stories over grey context. Step 2: every line takes its type color and
// the legend becomes the counts. Nothing moves between steps.
import * as d3 from "d3";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { searchBox } from "../lib/search.js";
import { keyNav, ms, reducedMotion, onEscape, liveRegion } from "../lib/a11y.js";
import { gnbu, neutral } from "../lib/colors.js";
import { miniMap } from "./minimap.js";

// the four stories of step 1, by name and date
const FOUR = [
  { name: "ChatGPT", date: "2025-01-23", note: "the widest shock of all" },
  { name: "Pope Francis", date: "2025-04-21", note: "half his countries in 10 min" },
  { name: "Diogo Jota", date: "2025-07-03", note: "122 countries in a day" },
  { name: "Venezuela", date: "2026-01-03", note: "kept spreading for hours" },
];

export function mountShocks(root, data) {
  const G = gnbu();
  const N = neutral();
  const TYPE_COLOR = { death: G.deep, outage: G.sky, "politics or conflict": G.green, other: N.faint };
  const TYPE_PLURAL = { death: "deaths", outage: "outages", "politics or conflict": "politics or conflict", other: "other" };
  const shocks = data.shocks; // sorted by reach
  const minutes = data.curve_minutes;
  const fourIds = new Map();
  FOUR.forEach((f) => {
    const s = shocks.find((x) => x.name === f.name && x.date === f.date);
    if (s) fourIds.set(s.id, f.note);
  });
  const scrollyEl = document.getElementById("shocks-scrolly");
  const after = document.getElementById("shocks-after");
  const announce = liveRegion(root);

  root.innerHTML = `
    <p class="chart-title">Most shocks reach half their countries within an hour</p>
    <p class="chart-sub">The widest tenth of shocks, 60 in all, each checked by hand. Each line is one event, timed from the third country to start searching.</p>
    <div class="legend sh-legend" role="group" aria-label="Shock types"></div>
    <div class="controls sh-controls">
      <span class="sh-search"></span>
      <span class="seg" role="group" aria-label="Measure">
        <button type="button" data-m="count" aria-pressed="true">Countries reached</button>
        <button type="button" data-m="share" aria-pressed="false">Share of its final reach</button>
      </span>
      <button type="button" class="sh-reset" hidden>Reset</button>
    </div>
    <div class="sh-plot"></div>
    <ul class="sh-labels-list"></ul>
    <div class="sh-card" hidden role="dialog" aria-modal="false" aria-labelledby="sh-card-title"></div>`;
  const plot = root.querySelector(".sh-plot");
  const legend = root.querySelector(".sh-legend");
  const resetBtn = root.querySelector(".sh-reset");
  const card = root.querySelector(".sh-card");
  const labelList = root.querySelector(".sh-labels-list");

  // ------------------------------------------------------------------ state
  const st = { step: 0, measure: "count", filter: null, search: null, selected: null, hover: null, drawn: false };

  const svg = d3.select(plot).append("svg").attr("role", "img").attr("aria-roledescription", "chart")
    .attr("aria-label", `${data.takeaway} Step lines for the 60 widest shocks: ${data.counts.death} deaths, ${data.counts.outage} outages, ${data.counts["politics or conflict"]} politics or conflict, ${data.counts.other} other. Arrow keys move through the lines in order of reach; Enter opens a line.`);
  const gAxis = svg.append("g");
  const gLines = svg.append("g").attr("fill", "none");
  const gLabels = svg.append("g");
  const overlay = svg.append("rect").attr("fill", "transparent");
  const tip = createTooltip(root);

  let x, y, W, H, M, phone, delaunay, pts;
  const yVal = (s, i) => (st.measure === "count" ? s.curve[i] : s.curve[i] / s.countries_24h);

  function linePath(s) {
    const g = d3.line().curve(d3.curveStepAfter).x((d) => x(d[0])).y((d) => y(d[1]));
    return g(minutes.map((m, i) => [m, yVal(s, i)]));
  }

  // ------------------------------------------------------------------ styling from state
  function lineStyle(s) {
    const isFour = fourIds.has(s.id);
    const hot = st.hover === s.id || st.selected === s.id;
    const match = st.search === s.id;
    let color, width, op;
    if (st.step === 0) {
      color = isFour ? TYPE_COLOR[s.type] : N.context;
      width = isFour ? 3 : 1;
      op = 1;
    } else {
      color = TYPE_COLOR[s.type];
      width = 1.5;
      op = 0.9;
      if (st.filter && s.type !== st.filter) op = 0.15;
    }
    if (st.search != null) { op = match ? 1 : 0.15; width = match ? 3 : width; }
    if (hot) { color = st.step === 0 && !isFour ? N.ink : d3.color(color).darker(0.6).formatHex(); width = 3; op = 1; }
    return { color, width, op, front: hot || match || (st.step === 0 && isFour) };
  }
  function restyle(dur = ms(300)) {
    const sel = gLines.selectAll("path.line");
    sel.each(function (s) { this.__st = lineStyle(s); });
    sel.filter(function () { return this.__st.front; }).raise();
    sel.transition().duration(dur).attr("stroke", function () { return this.__st.color; })
      .attr("stroke-width", function () { return this.__st.width; }).attr("opacity", function () { return this.__st.op; });
    drawLabels();
    drawLegend();
    resetBtn.hidden = !(st.filter || st.search != null || st.selected != null);
  }

  // ------------------------------------------------------------------ layout
  function render() {
    W = plot.clientWidth || 720;
    phone = W < 560;
    M = { t: 22, r: phone ? 14 : 150, b: 30, l: 34 };
    H = Math.max(300, Math.min(460, window.innerHeight * 0.55));
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    x = d3.scaleLinear([0, 180], [M.l, W - M.r]);
    y = st.measure === "count" ? d3.scaleLinear([0, 125], [H - M.b, M.t]) : d3.scaleLinear([0, 1], [H - M.b, M.t]);
    drawAxes(0);
    gLines.selectAll("path.line").data(shocks, (s) => s.id).join("path")
      .attr("class", "line mark").attr("id", (s) => `sh-${s.id}`).attr("d", linePath)
      .attr("stroke-linejoin", "round");
    overlay.attr("x", M.l).attr("y", M.t).attr("width", W - M.l - M.r).attr("height", H - M.t - M.b);
    buildVoronoi();
    restyle(0);
  }
  function drawAxes(dur) {
    const ticks = [0, 30, 60, 120, 180];
    const fmt = { 0: "start", 30: "30 min", 60: "1 hour", 120: "2 hours", 180: "3 hours" };
    gAxis.selectAll("g.x").data([0]).join("g").attr("class", "x")
      .attr("transform", `translate(0,${H - M.b})`)
      .call(d3.axisBottom(x).tickValues(ticks).tickFormat((d) => fmt[d]).tickSize(0).tickPadding(10))
      .call((g) => g.select(".domain").attr("stroke", N.rule))
      .call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 12));
    const yTicks = st.measure === "count" ? [0, 25, 50, 75, 100, 125] : [0, 0.25, 0.5, 0.75, 1];
    const gy = gAxis.selectAll("g.y").data([0]).join("g").attr("class", "y");
    gy.transition().duration(dur).ease(d3.easeCubicInOut)
      .call(d3.axisLeft(y).tickValues(yTicks).tickFormat(st.measure === "count" ? d3.format("d") : d3.format(".0%"))
        .tickSize(-(W - M.l - M.r)).tickPadding(6))
      .attr("transform", `translate(${M.l},0)`);
    gy.call((g) => g.select(".domain").remove())
      .call((g) => g.selectAll(".tick line").attr("stroke", N.rule))
      .call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    gAxis.selectAll("text.ylab").data([0]).join("text").attr("class", "ylab halo")
      .attr("x", M.l + 4).attr("y", M.t - 8).attr("font-size", 12).attr("fill", N.ink)
      .text(st.measure === "count" ? "countries where it was trending" : "share of the countries it reached in 24 hours");
  }
  function buildVoronoi() {
    pts = [];
    shocks.forEach((s) => minutes.forEach((m, i) => {
      pts.push([x(m), y(yVal(s, i)), s]);
      if (i + 1 < minutes.length) pts.push([x(minutes[i + 1]) - 0.5, y(yVal(s, i)), s]); // the step's flat part
    }));
    delaunay = d3.Delaunay.from(pts, (p) => p[0], (p) => p[1]);
  }

  // ------------------------------------------------------------------ labels and legend
  function drawLabels() {
    const show = shocks.filter((s) => (st.step === 0 && fourIds.has(s.id)) || st.search === s.id || st.selected === s.id);
    const items = show.map((s) => ({ s, y: y(yVal(s, minutes.length - 1)) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) items[i].y = Math.max(items[i].y, items[i - 1].y + 28);
    if (phone) {
      gLabels.selectAll("*").remove();
      labelList.innerHTML = items.map(({ s }) => `<li><i class="swatch" style="background:${TYPE_COLOR[s.type]}"></i><b>${s.label}</b> ${fourIds.get(s.id) || `${s.countries_24h} countries`}</li>`).join("");
      return;
    }
    labelList.innerHTML = "";
    const g = gLabels.selectAll("g.lab").data(items, (d) => d.s.id).join((en) => {
      const gg = en.append("g").attr("class", "lab");
      gg.append("text").attr("class", "n halo");
      gg.append("text").attr("class", "d halo");
      return gg;
    });
    g.attr("transform", (d) => `translate(${W - M.r + 8},${d.y})`);
    g.select(".n").attr("font-size", 12).attr("font-weight", 700).attr("dy", "0.32em")
      .attr("fill", (d) => TYPE_COLOR[d.s.type]).text((d) => d.s.label);
    g.select(".d").attr("font-size", 11).attr("dy", "1.5em").attr("fill", N.muted)
      .text((d) => fourIds.get(d.s.id) || `${d.s.countries_24h} countries in 24 h`);
  }
  function drawLegend() {
    legend.replaceChildren();
    data.types.forEach((tp) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "legend-btn";
      const n = data.counts[tp];
      b.innerHTML = `<i class="swatch" style="background:${TYPE_COLOR[tp]}"></i>` +
        (st.step === 0 ? (tp === "politics or conflict" ? "Politics or conflict" : tp[0].toUpperCase() + tp.slice(1)) : `<b>${n}</b> ${TYPE_PLURAL[tp]}`);
      b.disabled = st.step === 0;
      b.setAttribute("aria-pressed", String(st.filter === tp));
      b.addEventListener("click", () => { st.filter = st.filter === tp ? null : tp; restyle(); });
      legend.appendChild(b);
    });
    if (st.step === 0) legend.insertAdjacentHTML("beforeend", `<span><i class="swatch" style="background:${N.context}"></i>Other widest shocks</span>`);
    else legend.insertAdjacentHTML("beforeend", `<span class="tt-muted">of the widest 60 · tap a type to filter</span>`);
  }

  // ------------------------------------------------------------------ hover, tap, keyboard
  const fmtDate = d3.utcFormat("%B %-d, %Y");
  const tipHtml = (s) => `<div class="tt-title">${s.label}</div><div class="tt-muted">${s.type} · ${fmtDate(new Date(s.first_utc))}</div><div>${s.countries_24h} countries in 24 hours</div>`;
  function nearest(ev) {
    const [mx, my] = d3.pointer(ev, svg.node());
    const i = delaunay.find(mx, my);
    const p = pts[i];
    return Math.hypot(p[0] - mx, p[1] - my) < 40 ? p[2] : null;
  }
  overlay
    .on("pointermove", (ev) => {
      if (ev.pointerType === "touch") return;
      const s = nearest(ev);
      if ((s && s.id) !== st.hover) { st.hover = s && s.id; restyle(0); }
      if (s) tip.show(tipHtml(s), ev); else tip.hide();
    })
    .on("pointerleave", () => { st.hover = null; restyle(0); tip.hide(); })
    .on("click", (ev) => {
      const s = nearest(ev);
      if (!s) return;
      if (ev.pointerType === "touch" && st.hover !== s.id) { // first tap: select nearest, show tooltip
        st.hover = s.id; restyle(0); tip.show(tipHtml(s), ev, document.getElementById(`sh-${s.id}`)); return;
      }
      openCard(s);
    })
    .style("cursor", "pointer");
  keyNav(svg.node(), {
    items: () => shocks.map((s) => ({ s, el: document.getElementById(`sh-${s.id}`) })),
    onFocus: ({ s, el }) => { st.hover = s.id; restyle(0); tip.show(tipHtml(s), null, el); announce(`${s.label}, ${s.countries_24h} countries`); },
    onEnter: ({ s }) => openCard(s),
    onEscape: () => closeCard(),
    onBlur: () => { st.hover = null; restyle(0); tip.hide(); },
  });

  // ------------------------------------------------------------------ event card
  let mm = null;
  function openCard(s) {
    st.selected = s.id;
    tip.hide(true);
    restyle();
    const first = d3.utcFormat("%H:%M")(new Date(s.first_utc));
    card.innerHTML = `
      <button type="button" class="tt-close sh-card-close" aria-label="Close">×</button>
      <p class="kicker" style="color:${TYPE_COLOR[s.type] === N.faint ? N.muted : TYPE_COLOR[s.type]}">${s.type}</p>
      <p class="chart-title" id="sh-card-title">${s.label}</p>
      <p class="chart-sub">${fmtDate(new Date(s.first_utc))}, first trending ${first} UTC</p>
      <p class="sh-facts"><b>${s.countries_24h}</b> countries in 24 hours · <b>${s.within_1h}</b> within an hour<br>Half of them within ${s.minutes_to_half} minutes</p>
      <button type="button" class="sh-replay">▶ Replay it on the opening map</button>
      <div class="sh-mini"></div>
      <p class="source">Same shades as the opening map: darkest = the first 10 minutes after the first country.</p>`;
    card.hidden = false;
    card.querySelector(".sh-card-close").addEventListener("click", closeCard);
    const mini = card.querySelector(".sh-mini");
    miniMap(mini, s.map, { label: `Map of the ${s.countries_24h} countries where ${s.label} trended, shaded by minutes after the first country.` })
      .then((m) => { mm = m; });
    card.querySelector(".sh-replay").addEventListener("click", () => mm && mm.replay());
    card.querySelector(".sh-replay").focus({ preventScroll: true });
    announce(`${s.label}: ${s.countries_24h} countries in 24 hours, half within ${s.minutes_to_half} minutes.`);
  }
  function closeCard() {
    if (st.selected == null) return;
    mm && mm.stop();
    card.hidden = true;
    st.selected = null;
    restyle();
  }
  onEscape(closeCard);

  // ------------------------------------------------------------------ controls
  searchBox(root.querySelector(".sh-search"), {
    label: "Find a shock", placeholder: "Find a shock (e.g. “Ozzy”)",
    items: shocks.map((s) => ({ id: s.id, name: `${s.label} (${s.date.slice(0, 4)})`, s })),
    onPick: (it) => { st.search = it.id; restyle(); announce(`${it.s.label}: ${it.s.countries_24h} countries.`); },
    onNoMatch: () => { st.search = null; restyle(); announce("No shock by that name among the 60."); },
  });
  root.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    if (st.measure === b.dataset.m) return;
    st.measure = b.dataset.m;
    root.querySelectorAll(".seg button").forEach((x2) => x2.setAttribute("aria-pressed", String(x2 === b)));
    y = st.measure === "count" ? d3.scaleLinear([0, 125], [H - M.b, M.t]) : d3.scaleLinear([0, 1], [H - M.b, M.t]);
    drawAxes(ms(600));
    gLines.selectAll("path.line").transition("measure").duration(ms(600)).ease(d3.easeCubicInOut).attr("d", linePath);
    buildVoronoi();
    setTimeout(drawLabels, ms(600));
  }));
  resetBtn.addEventListener("click", () => {
    st.filter = null; st.search = null;
    root.querySelector(".sh-search input").value = "";
    closeCard();
    restyle();
  });

  // ------------------------------------------------------------------ steps
  function drawIn() {
    if (st.drawn || reducedMotion()) { st.drawn = true; return; }
    st.drawn = true;
    gLines.selectAll("path.line").each(function () {
      const L = this.getTotalLength();
      d3.select(this).attr("stroke-dasharray", `${L} ${L}`).attr("stroke-dashoffset", L)
        .transition("draw").duration(1200).ease(d3.easeCubicInOut).attr("stroke-dashoffset", 0)
        .on("end", function () { d3.select(this).attr("stroke-dasharray", null); });
    });
  }
  scrolly(scrollyEl, (i, dir, { animate }) => {
    st.step = Math.max(0, i);
    if (animate && i === 0) drawIn(); else st.drawn = true; // lines draw only when step 1 is entered by scrolling
    restyle(animate ? ms(300) : 0);
  });

  // ------------------------------------------------------------------ show the data
  showTheData(after, {
    caption: "The 60 widest shocks, Nov. 2024 to May 2026 (event level, timed from the third country)",
    filename: "sixty-shocks",
    columns: [
      { key: "label", label: "Shock" },
      { key: "date", label: "Date" },
      { key: "type", label: "Type" },
      { key: "countries_24h", label: "Countries (24 h)", num: true },
      { key: "within_1h", label: "Within 1 hour", num: true },
      { key: "minutes_to_half", label: "Minutes to half", num: true },
    ],
    rows: shocks,
  });

  render();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(plot);
}
