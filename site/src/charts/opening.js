// Chapter 0 · Opening v2 (docs/SPEC.md, Chapter 0). One sticky screen: three accumulating paragraphs above an Equal
// Earth map (about 760 px) with one square per country under it, both shaded by the 10-minute refresh in which Pope
// Francis first trended (PuBu, darkest = 07:50). Steps: 07:50 (22) → 08:00 (67) → 08:10–08:50 (114); after the
// steps the "Later" countries fill (123 in 24 hours) and Replay the moment, the scrubber and Find your country appear.
import * as d3 from "d3";
import { feature } from "topojson-client";
import worldUrl from "world-atlas/countries-50m.json?url";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { searchBox } from "../lib/search.js";
import { keyNav, reducedMotion, onMotionChange, liveRegion, onEscape } from "../lib/a11y.js";
import { pubu, neutral } from "../lib/colors.js";

const NUM = ["zero", "ten", "twenty", "thirty", "forty", "fifty"];
const HOURS = ["", "one", "two"];
const VATICAN = [12.4534, 41.9029];

export async function mountOpening(root, data) {
  const world = await (await fetch(worldUrl)).json();
  const countries = await (await fetch(`${import.meta.env.BASE_URL}data/countries.json`)).json();
  const P = pubu();
  const N = neutral();
  const bins = data.bins; // 07:50 … 08:50, Later
  const LAST = bins.length - 1;
  const STEP_K = [0, 1, LAST - 1, LAST]; // last refresh shown at each step (3 = after the steps)
  const SHADE = [P[6], P[5], P[4], P[3], P[2], P[1], P[0], N.paper]; // "Later" = white with a light outline
  const PALE_FROM = 5; // 08:40 and later: the white selection outline gets a grey ring
  const rows = data.rows;
  const total = data.countries_24h;
  const byIso = new Map(rows.map((r) => [r.iso2, r]));
  const isoById = new Map(countries.countries.map((c) => [c.id, c.iso2]));
  const trending = rows.filter((r) => r.trending).sort((a, b) => a.minutes_after_first - b.minutes_after_first || a.name.localeCompare(b.name));
  const fillOf = (r, k) => (r && r.trending && r.bin <= k ? SHADE[r.bin] : N.land);
  const isPale = (r, k) => !r || !r.trending || r.bin > k || r.bin >= PALE_FROM;

  const scrollyEl = document.getElementById("opening-scrolly");
  const paras = [...scrollyEl.querySelectorAll(".op-text [data-p]")];
  const afterEl = document.getElementById("opening-after");

  // ------------------------------------------------------------------ DOM
  root.replaceChildren();
  root.insertAdjacentHTML("beforeend", `
    <div class="op-counter" aria-hidden="true"></div>
    <div class="op-map"></div>
    <div class="op-squares"></div>
    <div class="op-after" data-on="false">
      <div class="op-scrub">
        <button type="button" class="op-play">▶ Replay the moment</button>
        <div class="op-range-wrap">
          <label class="sr-only" for="op-range">Refresh</label>
          <input id="op-range" class="op-range" type="range" min="0" max="${LAST}" step="1" value="${LAST}">
          <div class="op-ticks" aria-hidden="true">${bins.map((b) => `<span>${b}</span>`).join("")}</div>
        </div>
      </div>
      <div class="op-find"><span class="op-search"></span><p class="op-result" aria-live="polite"></p></div>
    </div>
  `);
  const counter = root.querySelector(".op-counter");
  const after = root.querySelector(".op-after");
  const range = root.querySelector(".op-range");
  const playBtn = root.querySelector(".op-play");
  const result = root.querySelector(".op-result");
  const announce = liveRegion(root);

  // ------------------------------------------------------------------ state
  let k = -1; // last refresh shown (-1 = empty map)
  let hot = null; // hovered / focused country
  let found = null; // from "Find your country"
  let timers = [];
  let afterOn = false;

  const cumAt = (kk) => (kk < 0 ? 0 : kk >= LAST ? total : data.cumulative_by_bin[kk]);
  const counterText = (kk) => (kk < 0 ? "" : kk >= LAST ? `Within 24 hours · ${total} countries` : `${bins[kk]} UTC · ${cumAt(kk)} countries`);

  // ------------------------------------------------------------------ map + squares
  const land = feature(world, world.objects.countries).features.filter((f) => f.id !== "010"); // no Antarctica
  const fc = { type: "FeatureCollection", features: land };
  const mapWrap = root.querySelector(".op-map");
  const svg = d3.select(mapWrap).append("svg")
    .attr("role", "img").attr("aria-roledescription", "map")
    .attr("aria-label", `${data.takeaway} Map of 125 countries shaded by the refresh in which Pope Francis first trended: ${data.per_bin.slice(0, LAST).map((n, i) => `${n} at ${bins[i]} UTC`).join(", ")}, ${data.per_bin[LAST]} later that day. Use the arrow keys to move country by country in order of refresh.`);
  const gLand = svg.append("g");
  const gDots = svg.append("g");
  const gSel = svg.append("g").attr("pointer-events", "none");
  const gNote = svg.append("g").attr("pointer-events", "none");
  const projection = d3.geoEqualEarth();
  const path = d3.geoPath(projection);

  const sqWrap = root.querySelector(".op-squares");
  const sqSvg = d3.select(sqWrap).append("svg").attr("role", "img")
    .attr("aria-label", `One square per country, by refresh: ${data.per_bin.map((n, i) => `${n} at ${bins[i]}`).join(", ")}.`);
  const gSq = sqSvg.append("g");
  const gSqSel = sqSvg.append("g").attr("pointer-events", "none");

  const tip = createTooltip(root);

  // ------------------------------------------------------------------ text
  const utcLabel = (r) => `${r.refresh.replace(/^([A-Z][a-z]{2}) /, "$1. ")} UTC`;
  function localLabel(r) {
    const d = r.local_time.slice(0, 10);
    const day = d === data.date ? "" : `, ${new Date(`${d}T12:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).replace(" ", ". ")}`;
    return `${r.local_clock}${day}`;
  }
  function tipHtml(r) {
    if (!r) return "";
    if (!r.trending) return `<div class="tt-title">${r.name}</div><div>Not trending within 24 hours</div>`;
    return `<div class="tt-title">${r.name} · ${utcLabel(r)}</div>` +
      `<div>${localLabel(r)} local time (${r.city})</div>` +
      (r.searched_as && r.searched_as.length ? `<div>Searched as ${r.searched_as.map((q) => `“${q}”`).join(" · ")}</div>` : "");
  }
  function minutesWords(m) {
    if (m < 60) return `${NUM[m / 10]} minutes`;
    const h = Math.floor(m / 60), mm = m % 60;
    if (h < 3) return mm ? `${HOURS[h]} hour${h > 1 ? "s" : ""} and ${NUM[mm / 10]} minutes` : `${HOURS[h]} hour${h > 1 ? "s" : ""}`;
    return `about ${Math.round(m / 60)} hours`;
  }
  function sentence(r) {
    if (!r.trending) return `In ${r.name}, Pope Francis did not trend within 24 hours.`;
    const when = `${utcLabel(r)} (${localLabel(r)} ${r.city} time)`;
    if (r.minutes_after_first === 0) return `In ${r.name}, Pope Francis started trending at ${when}, among the first ${data.per_bin[0]} countries.`;
    const by = trending.filter((x) => x.minutes_after_first <= r.minutes_after_first).length;
    const then = by === total ? `It was the last of the ${total} countries.` : `By then, ${by} of the ${total} countries were already searching.`;
    return `In ${r.name}, Pope Francis started trending at ${when}, ${minutesWords(r.minutes_after_first)} after the first countries. ${then}`;
  }

  // land drawn once to an offscreen canvas; free(x, y, w, h) = no land under that box (1 px margin)
  function landMask(W, H) {
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    const draw = d3.geoPath(projection, ctx);
    ctx.beginPath(); draw(fc); ctx.fillStyle = "#000"; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.stroke();
    const px = ctx.getImageData(0, 0, W, H).data;
    return (x0, y0, w, h) => {
      if (x0 < 0 || y0 < 0 || x0 + w > W || y0 + h > H) return false;
      for (let y = y0; y < y0 + h; y += 1) for (let x = x0; x < x0 + w; x += 1) if (px[(y * W + x) * 4 + 3] > 0) return false;
      return true;
    };
  }
  // first choice: a two-line label in the central Mediterranean, south of Sicily
  function sicilySpot(free, w, h) {
    const c = projection([15.5, 34.5]);
    let best = null;
    for (let dy = -24; dy <= 24; dy += 1) for (let dx = -30; dx <= 30; dx += 1) {
      const x = Math.round(c[0] - w / 2 + dx), y = Math.round(c[1] - h / 2 + dy);
      if (!free(x, y, w, h)) continue;
      const d = Math.hypot(dx, dy);
      if (!best || d < best.d) best = { x, y, d };
    }
    return best;
  }
  // fallback: nearest open water to the dot (one line), preferring the sea south of Sardinia
  function seaSpot(free, v, w, h) {
    const pref = projection([9.0, 38.3]);
    let best = null;
    for (let dy = -120; dy <= 120; dy += 2) for (let dx = -220; dx <= 160; dx += 2) {
      const x = Math.round(pref[0] - w / 2 + dx), y = Math.round(pref[1] + dy);
      if (!free(x, y, w, h)) continue;
      const nx = Math.max(x, Math.min(v[0], x + w)), ny = Math.max(y, Math.min(v[1], y + h)); // nearest box point to the dot
      const d = Math.hypot(nx - v[0], ny - v[1]) + 0.25 * Math.hypot(x + w / 2 - pref[0], y + h / 2 - pref[1]);
      if (!best || d < best.d) best = { x, y, d, reach: Math.hypot(nx - v[0], ny - v[1]) };
    }
    return best || { x: 0, y: 0, reach: Infinity };
  }

  // ------------------------------------------------------------------ layout
  let mapSel, dotSel, sqSel, items = [];
  let placed = [];
  let phone = false;
  let labelPlacement = "";

  function render() {
    const avail = root.clientWidth || 760;
    phone = avail < 560;
    const sqH = phone ? 112 : 168;
    const fixed = counter.offsetHeight + after.offsetHeight + sqH + 12;
    const roomH = Math.max(140, root.clientHeight - fixed);
    projection.fitWidth(1000, fc);
    const ratio = path.bounds(fc)[1][1] / 1000;
    const W = Math.floor(Math.min(760, avail, roomH / ratio));
    projection.fitWidth(W, fc);
    let H = Math.ceil(path.bounds(fc)[1][1]) + 2;
    // Vatican City: first a two-line label ("Vatican / City", 11 px) south of Sicily; if that box would cover any
    // country, one line in the nearest open water (the Atlantic at these sizes); on small maps with no water near,
    // just above the map. Always a thin leader line to the dot.
    const fs = phone ? 9 : 11;
    gNote.selectAll("*").remove();
    const label = gNote.append("text").attr("class", "halo").attr("font-size", fs).attr("font-weight", 700)
      .attr("fill", N.ink).attr("text-anchor", "start");
    label.text("Vatican City");
    const lw1 = Math.ceil(label.node().getComputedTextLength()) + 4;
    label.attr("font-size", 11).text("Vatican");
    const lw2 = Math.ceil(label.node().getComputedTextLength()) + 4;
    label.attr("font-size", fs);
    let lh = fs + 2;
    let v = projection(VATICAN);
    const free = landMask(W, H);
    const two = sicilySpot(free, lw2, 13 * 2);
    let spot, lw, lines;
    if (two) { spot = two; lw = lw2; lh = 13; lines = ["Vatican", "City"]; label.attr("font-size", 11); } else {
      lw = lw1; lines = ["Vatican City"];
      spot = seaSpot(free, v, lw, lh);
      if (spot.reach > (phone ? 40 : 70)) {
        const pad = lh + 6;
        const [tx, ty] = projection.translate();
        projection.translate([tx, ty + pad]);
        H += pad;
        v = projection(VATICAN);
        spot = { x: Math.max(0, Math.min(W - lw, v[0] - lw / 2)), y: 0 };
      }
    }
    labelPlacement = two ? "sicily" : spot.y === 0 ? "above" : "sea";
    svg.attr("data-label", labelPlacement);
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    label.text(null).attr("x", spot.x).attr("y", spot.y + lh - 3);
    lines.forEach((t, i) => label.append("tspan").attr("x", spot.x).attr("dy", i ? lh : 0).text(t));
    const bh = lh * lines.length;
    const end = [Math.max(spot.x, Math.min(v[0], spot.x + lw)), Math.max(spot.y, Math.min(v[1], spot.y + bh))];
    gNote.insert("line", "text").attr("x1", v[0]).attr("y1", v[1]).attr("x2", end[0]).attr("y2", end[1])
      .attr("stroke", N.ink).attr("stroke-width", 0.75);
    gNote.append("circle").attr("cx", v[0]).attr("cy", v[1]).attr("r", 2.25).attr("fill", N.ink).attr("stroke", N.paper).attr("stroke-width", 0.75);


    mapSel = gLand.selectAll("path").data(land, (f) => f.id).join("path")
      .attr("d", path)
      .attr("class", (f) => (isoById.has(f.id) ? "mark" : null))
      .attr("id", (f) => (isoById.has(f.id) ? `op-${isoById.get(f.id)}` : null))
      .attr("stroke", N.paper).attr("stroke-width", 0.5)
      .style("cursor", (f) => (isoById.has(f.id) ? "pointer" : null));

    // microstates: archive countries too small to see become dots (with a bigger tap target)
    const tiny = land.filter((f) => isoById.has(f.id) && path.area(f) < (phone ? 3 : 8));
    dotSel = gDots.selectAll("g.dot").data(tiny, (f) => f.id).join((en) => {
      const g = en.append("g").attr("class", "dot");
      g.append("circle").attr("class", "hit").attr("r", 9).attr("fill", "transparent");
      g.append("circle").attr("class", "vis").attr("r", 3).attr("stroke", N.paper).attr("stroke-width", 0.75);
      return g;
    }).attr("transform", (f) => `translate(${path.centroid(f)})`).style("cursor", "pointer");

    // squares: one column per refresh, stacked from the bottom, 5 per row
    const SW = W;
    const colW = SW / bins.length;
    const per = 5;
    const byBin = d3.range(bins.length).map((b) => trending.filter((r) => r.bin === b));
    const maxRows = Math.ceil(d3.max(byBin, (x) => x.length) / per);
    const gap = phone ? 1.5 : 2.5;
    const top = 20, foot = 18;
    const size = Math.max(4, Math.min(Math.floor((colW - 8) / per - gap), Math.floor((sqH - top - foot) / maxRows - gap)));
    const base = sqH - foot;
    sqSvg.attr("viewBox", `0 0 ${SW} ${sqH}`).attr("width", SW).attr("height", sqH);
    placed = [];
    byBin.forEach((list, b) => list.forEach((r, i) => placed.push({
      r, b, x: b * colW + 2 + (i % per) * (size + gap), y: base - (Math.floor(i / per) + 1) * (size + gap), size,
    })));
    sqSel = gSq.selectAll("rect.sq").data(placed, (d) => d.r.iso2).join("rect")
      .attr("class", "sq").attr("id", (d) => `ops-${d.r.iso2}`)
      .attr("x", (d) => d.x).attr("y", (d) => d.y).attr("width", size).attr("height", size).attr("rx", 1)
      .style("cursor", "pointer");
    sqSvg.selectAll("text.bin").data(bins).join("text").attr("class", "bin")
      .attr("x", (d, i) => i * colW + 2).attr("y", base + 14).attr("font-size", phone ? 9 : 11)
      .attr("fill", N.muted).text((d) => (phone && d === "Later" ? "Later" : d));
    sqSvg.selectAll("text.cnt").data(byBin).join("text").attr("class", "cnt")
      .attr("x", (d, i) => i * colW + 2)
      .attr("y", (d) => base - Math.ceil(d.length / per) * (size + gap) - 5)
      .attr("font-size", phone ? 11 : 13).attr("font-weight", 700).attr("fill", N.ink).text((d) => d.length);
    const laterTop = base - Math.ceil(byBin[LAST].length / per) * (size + gap) - 5 - (phone ? 13 : 15);
    sqSvg.selectAll("text.later").data([0]).join("text").attr("class", "later")
      .attr("x", SW - 2).attr("y", laterTop).attr("text-anchor", "end").attr("font-size", phone ? 10 : 12).attr("fill", N.ink)
      .text(`${total} by the end of the day`);

    items = trending.map((r) => ({ r, el: document.getElementById(`op-${r.iso2}`) }));
    bindEvents();
    paint(0);
  }

  // ------------------------------------------------------------------ painting
  function selected() {
    return [hot, found].filter(Boolean).filter((r, i, a) => a.indexOf(r) === i);
  }
  function paint(dur = 0) {
    const t = d3.transition().duration(dur).ease(d3.easeCubicInOut);
    const arch = mapSel.filter((f) => isoById.has(f.id));
    (dur ? arch.transition(t) : arch).attr("fill", (f) => fillOf(byIso.get(isoById.get(f.id)), k));
    mapSel.filter((f) => !isoById.has(f.id)).attr("fill", N.land);
    // "Later" countries are white on the map, so they get a light PuBu outline
    const isLater = (f) => { const r = byIso.get(isoById.get(f.id)); return r && r.trending && r.bin === LAST && k >= LAST; };
    mapSel.attr("stroke", (f) => (isLater(f) ? P[2] : N.paper)).attr("stroke-width", (f) => (isLater(f) ? 1 : 0.5));
    mapSel.filter(isLater).raise();
    dotSel.select("circle.vis").attr("fill", (f) => fillOf(byIso.get(isoById.get(f.id)), k));
    sqSel.attr("fill", (d) => SHADE[d.b])
      .attr("stroke", (d) => (d.b === LAST ? P[1] : "none")).attr("stroke-width", 1)
      .attr("visibility", (d) => (d.b <= k ? "visible" : "hidden"));
    sqSvg.selectAll("text.cnt").attr("visibility", (d, i) => (i <= k ? "visible" : "hidden"));
    sqSvg.selectAll("text.later").attr("visibility", k >= LAST ? "visible" : "hidden");
    paintSelection();
    counter.textContent = counterText(k);
    range.value = String(Math.max(0, k));
    range.setAttribute("aria-valuetext", counterText(Math.max(0, k)));
  }
  // selection: white 2.5 px outline on the country and its square; on the palest fills a 1 px grey ring outside it
  function paintSelection() {
    const sel = selected();
    const feats = sel.map((r) => ({ r, f: land.find((f) => isoById.get(f.id) === r.iso2) })).filter((x) => x.f);
    const tinyIds = new Set(dotSel.data().map((f) => f.id));
    const shapes = gSel.selectAll("g.sel").data(feats, (d) => d.r.iso2).join((en) => {
      const g = en.append("g").attr("class", "sel");
      g.append("path").attr("class", "ring");
      g.append("path").attr("class", "edge");
      return g;
    });
    shapes.each(function ({ r, f }) {
      const g = d3.select(this);
      const [cx, cy] = path.centroid(f);
      const d = tinyIds.has(f.id) ? `M${cx - 3},${cy}a3,3 0 1,0 6,0a3,3 0 1,0 -6,0` : path(f);
      g.select(".ring").attr("d", d).attr("fill", "none").attr("stroke", N.muted).attr("stroke-width", 4.5)
        .attr("stroke-linejoin", "round").attr("visibility", isPale(r, k) ? "visible" : "hidden");
      g.select(".edge").attr("d", d).attr("fill", "none").attr("stroke", N.paper).attr("stroke-width", 2.5).attr("stroke-linejoin", "round");
    });
    const sq = placed.filter((d) => sel.includes(d.r) && d.b <= k);
    gSqSel.selectAll("g.sel").data(sq, (d) => d.r.iso2).join((en) => {
      const g = en.append("g").attr("class", "sel");
      g.append("rect").attr("class", "ring");
      g.append("rect").attr("class", "edge");
      return g;
    }).each(function (d) {
      const g = d3.select(this);
      g.select(".ring").attr("x", d.x - 2.25).attr("y", d.y - 2.25).attr("width", d.size + 4.5).attr("height", d.size + 4.5)
        .attr("rx", 2).attr("fill", "none").attr("stroke", N.muted).attr("stroke-width", 1)
        .attr("visibility", isPale(d.r, k) ? "visible" : "hidden");
      g.select(".edge").attr("x", d.x - 0.5).attr("y", d.y - 0.5).attr("width", d.size + 1).attr("height", d.size + 1)
        .attr("rx", 1.5).attr("fill", "none").attr("stroke", N.paper).attr("stroke-width", 2.5);
    });
  }

  function dropColumns(list, dur) {
    if (reducedMotion()) return;
    sqSel.filter((d) => list.includes(d.b))
      .attr("transform", "translate(0,-18)").attr("opacity", 0)
      .transition().duration(dur).ease(d3.easeCubicOut).delay((d, i) => i * 6)
      .attr("transform", null).attr("opacity", 1);
  }

  // ------------------------------------------------------------------ steps, playback
  function stop() { timers.forEach(clearTimeout); timers = []; }
  function at(delay, fn) { timers.push(setTimeout(fn, delay)); }
  // reveal refreshes from..to one by one, each over `dur` ms (the map fill and the column drop run together)
  function sequence(from, to, dur, start = 0) {
    let t = start;
    for (let b = from; b <= to; b++) {
      at(t, () => { k = b; paint(dur); dropColumns([b], Math.min(dur, 500)); announce(counterText(b)); });
      t += dur;
    }
    return t;
  }
  function setAfter(on) {
    afterOn = on;
    after.dataset.on = String(on);
    after.inert = !on;
    afterEl.hidden = !on;
  }
  function setParas(i) {
    const cur = Math.min(i, 2);
    paras.forEach((p, j) => { p.dataset.state = i < 0 || j > cur ? "future" : j === cur ? "current" : "past"; });
  }

  function onStep(i, dir, { animate }) {
    stop();
    setParas(i);
    const target = i < 0 ? -1 : STEP_K[i];
    if (i < 3) setAfter(false);
    if (!animate || reducedMotion()) {
      k = target;
      paint(0);
      if (i === 3) setAfter(true);
      return;
    }
    if (i === 0 || i === 1) { sequence(target, target, 700); return; }
    if (i === 2) { sequence(Math.max(k + 1, 2), target, 500); return; }
    // after the steps: the "Later" countries fill, then the controls appear
    const end = sequence(LAST, LAST, 600);
    at(end, () => setAfter(true));
  }

  function replay() {
    stop();
    if (reducedMotion()) { // one refresh per press
      k = k >= LAST ? 0 : k + 1;
      paint(0);
      announce(counterText(k));
      return;
    }
    k = -1;
    paint(0);
    let t = sequence(0, 1, 1000, 200);
    t = sequence(2, LAST - 1, 600, t);
    sequence(LAST, LAST, 800, t);
  }
  playBtn.addEventListener("click", replay);
  range.addEventListener("input", () => { stop(); k = +range.value; paint(0); });

  // ------------------------------------------------------------------ hover / tap / keyboard
  function setHot(r, ev, anchor) {
    hot = r;
    paintSelection();
    if (r) tip.show(tipHtml(r), ev, anchor); else tip.hide();
  }
  function bindEvents() {
    const over = (getR) => (sel) => sel
      .on("pointerenter", (ev, d) => { if (ev.pointerType !== "touch") setHot(getR(d), ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType !== "touch" && !tip.pinned) { hot = null; paintSelection(); tip.hide(); } })
      .on("click", (ev, d) => { ev.stopPropagation(); setHot(getR(d), ev, ev.currentTarget); });
    mapSel.filter((f) => isoById.has(f.id)).call(over((f) => byIso.get(isoById.get(f.id))));
    dotSel.call(over((f) => byIso.get(isoById.get(f.id))));
    sqSel.call(over((d) => d.r));
  }
  keyNav(svg.node(), {
    items: () => items,
    onFocus: ({ r, el }) => setHot(r, null, el),
    onEnter: ({ r, el }) => tip.pin(tipHtml(r), el),
    onEscape: () => { hot = null; tip.hide(true); paintSelection(); },
    onBlur: () => { if (!tip.pinned) { hot = null; tip.hide(); paintSelection(); } },
  });
  onEscape(() => { if (found) { found = null; result.textContent = ""; paintSelection(); } });

  // ------------------------------------------------------------------ find your country
  searchBox(root.querySelector(".op-search"), {
    label: "Find your country", placeholder: "Find your country",
    items: countries.countries.map((c) => ({ id: c.iso2, name: c.name })),
    onPick: (it) => { found = byIso.get(it.id); result.textContent = sentence(found); paintSelection(); },
    onNoMatch: () => { found = null; result.textContent = "We don’t have data for that country."; paintSelection(); },
  });

  // ------------------------------------------------------------------ show the data · methodology (under the graphic)
  afterEl.hidden = true;
  showTheData(afterEl, {
    methodology: "opening",
    caption: `${trending.length} countries where Pope Francis trended within 24 hours of the announcement, Apr. 21, 2025`,
    filename: "pope-francis-first-trending",
    columns: [
      { key: "name", label: "Country" },
      { key: "refresh", label: "First trending (UTC)", format: (v, r) => utcLabel(r).replace(" UTC", ""), sortValue: (r) => r.minutes_after_first },
      { key: "minutes_after_first", label: "Minutes after the first refresh", num: true },
      { key: "local_clock", label: "Local time (capital)", format: (v, r) => `${localLabel(r)} (${r.city})`, sortValue: (r) => r.local_time.slice(11, 16) },
      { key: "searched_as", label: "Searched as", format: (v) => (v || []).join(" · ") },
    ],
    rows: trending,
  });

  // ------------------------------------------------------------------ start
  setParas(-1);
  setAfter(false);
  render();
  let rt, lastSize = "";
  new ResizeObserver(() => {
    const size = `${root.clientWidth}x${root.clientHeight}`;
    if (size === lastSize) return;
    lastSize = size;
    clearTimeout(rt); rt = setTimeout(render, 150);
  }).observe(root);
  scrolly(scrollyEl, onStep);
  onMotionChange((red) => { if (red) { stop(); paint(0); } });
}
