// Chapter 0 · Opening: the day the world searched for one man (docs/SPEC.md, Chapter 0).
// Equal Earth map + one square per country, both shaded by the 10-minute refresh in which Pope Francis first
// trended (PuBu, darkest = 07:50). Plays once when the chart reaches 50% of the viewport; then a scrubber.
import * as d3 from "d3";
import { feature } from "topojson-client";
import worldUrl from "world-atlas/countries-50m.json?url";
import { onEnterView } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { searchBox } from "../lib/search.js";
import { keyNav, ms, reducedMotion, onMotionChange, liveRegion, onEscape } from "../lib/a11y.js";
import { pubu, neutral } from "../lib/colors.js";

const STEP_MS = 700;
const WORDS = ["", "ten", "twenty", "thirty", "forty", "fifty"];

export async function mountOpening(root, data) {
  const world = await (await fetch(worldUrl)).json();
  const P = pubu();
  const N = neutral();
  const bins = data.bins; // 07:50 … 08:50, Later
  const LAST = bins.length - 1;
  // darkest = first refresh; "Later" is the lightest, outlined
  const SHADE = [P[6], P[5], P[4], P[3], P[2], P[1], P[0], N.paper];
  const fillOf = (r, k) => (r && r.trending && r.bin <= k ? SHADE[r.bin] : N.land);
  const rows = data.rows;
  const byIso = new Map(rows.map((r) => [r.iso2, r]));
  const countries = await (await fetch(`${import.meta.env.BASE_URL}data/countries.json`)).json();
  const isoById = new Map(countries.countries.map((c) => [c.id, c.iso2]));
  const trending = rows.filter((r) => r.trending).sort((a, b) => a.bin - b.bin || a.name.localeCompare(b.name));

  // ------------------------------------------------------------------ DOM
  root.replaceChildren();
  root.insertAdjacentHTML("beforeend", `
    <p class="chart-title">How fast the news traveled</p>
    <p class="chart-sub">Each country is shaded by the 10-minute refresh in which Pope Francis first appeared on its trending list (UTC).</p>
    <div class="legend" aria-hidden="true"></div>
    <div class="controls op-controls">
      <span class="op-counter" aria-live="polite"></span>
      <span class="op-search"></span>
    </div>
    <p class="result op-result" aria-live="polite"></p>
    <div class="op-map"></div>
    <div class="op-scrub controls" hidden>
      <button type="button" class="op-play">▶ Replay</button>
      <label class="sr-only" for="op-range">Refresh</label>
      <div class="op-range-wrap"><input id="op-range" class="op-range" type="range" min="0" max="${LAST}" step="1" value="${LAST}" aria-valuetext="Later"></div>
      <span class="op-range-label"></span>
      <div class="op-ticks" aria-hidden="true">${bins.map((b) => `<span>${b}</span>`).join("")}</div>
    </div>
    <p class="chart-title" style="margin-top:28px">New countries at each refresh</p>
    <p class="chart-sub">One square per country, in the same shades as the map</p>
    <div class="op-squares"></div>
    <p class="source">Source: GoogleTrendArchive, national Trending Now feeds, collected every 10 minutes, so countries in the same refresh tie. Times are UTC; local times use each feed's time zone (United States: Chicago). The topic merges every way of searching for him (${data.countries_24h} countries in 24 hours). As of ${data.as_of}.</p>
  `);
  const legend = root.querySelector(".legend");
  bins.concat(["Not trending"]).forEach((b, i) => {
    const sw = i < bins.length ? SHADE[i] : N.land;
    const border = i === LAST ? `border:1px solid ${P[1]}` : "";
    legend.insertAdjacentHTML("beforeend", `<span><i class="swatch" style="background:${sw};${border}"></i>${b}</span>`);
  });
  const counter = root.querySelector(".op-counter");
  const result = root.querySelector(".op-result");
  const scrub = root.querySelector(".op-scrub");
  const range = root.querySelector(".op-range");
  const rangeLabel = root.querySelector(".op-range-label");
  const playBtn = root.querySelector(".op-play");
  const announce = liveRegion(root);

  // ------------------------------------------------------------------ state
  let k = -1; // last refresh shown (-1 = empty map)
  let hot = null; // hovered / focused country
  let found = null; // country from "Find your country"
  let timer = null;
  let played = false;

  const cum = (kk) => (kk < 0 ? 0 : kk >= LAST ? data.countries_24h : data.cumulative_by_bin[kk]);
  const counterText = (kk) => (kk < 0 ? "" : `${kk === LAST ? "Later (within 24 hours)" : `${bins[kk]} UTC`} · ${cum(kk)} countries`);

  // ------------------------------------------------------------------ map
  const land = feature(world, world.objects.countries).features.filter((f) => f.id !== "010"); // no Antarctica
  const mapWrap = root.querySelector(".op-map");
  const svg = d3.select(mapWrap).append("svg")
    .attr("role", "img").attr("aria-roledescription", "map")
    .attr("aria-label", `${data.takeaway} Map of 125 countries shaded by the refresh in which Pope Francis first trended. Use the arrow keys to move country by country in order of refresh.`);
  const gLand = svg.append("g");
  const gDots = svg.append("g");
  const gNote = svg.append("g");
  const projection = d3.geoEqualEarth();
  const path = d3.geoPath(projection);

  // ------------------------------------------------------------------ squares
  const sqWrap = root.querySelector(".op-squares");
  const sqSvg = d3.select(sqWrap).append("svg")
    .attr("role", "img")
    .attr("aria-label", `${data.takeaway} Squares: ${data.per_bin.map((n, i) => `${n} at ${bins[i]}`).join(", ")}.`);

  const tip = createTooltip(root);

  function localPhrase(r) {
    const h = +r.local_time.slice(11, 13);
    const day = r.local_day_offset < 0 ? "the evening before, " : r.local_day_offset > 0 ? "the next day, " : "";
    const when = h < 5 ? "in the middle of the night" : h < 7 ? "before most of the country was awake"
      : h < 12 ? "in the morning" : h < 18 ? "in the afternoon" : h < 22 ? "in the evening" : "late at night";
    return `${r.local_clock} in ${r.city}: ${day}${when}`;
  }
  function tipHtml(r) {
    if (!r) return "";
    if (!r.trending) return `<div class="tt-title">${r.name}</div><div class="tt-muted">Pope Francis did not trend here within 24 hours.</div>`;
    const ph = (r.phrasings_first || []).map((q) => `“${q}”`).join(", ");
    const other = (r.phrasings_other || []).length ? `<div class="tt-muted">Later also: ${r.phrasings_other.slice(0, 2).map((q) => `“${q}”`).join(", ")}</div>` : "";
    return `<div class="tt-title">${r.name} · ${r.refresh} UTC refresh</div>` +
      `<div>${localPhrase(r)}</div><div>Searched as ${ph}</div>${other}`;
  }

  let sqSel, mapSel, dotSel, items = [];

  function render() {
    const W = mapWrap.clientWidth || 1100;
    const phone = W < 700;
    projection.fitWidth(W, { type: "FeatureCollection", features: land });
    const H = Math.ceil(path.bounds({ type: "FeatureCollection", features: land })[1][1]) + 4;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);

    mapSel = gLand.selectAll("path").data(land, (f) => f.id).join("path")
      .attr("d", path)
      .attr("class", (f) => (isoById.has(f.id) ? "mark" : null))
      .attr("id", (f) => (isoById.has(f.id) ? `op-${isoById.get(f.id)}` : null))
      .attr("stroke", N.paper).attr("stroke-width", 0.5)
      .style("cursor", (f) => (isoById.has(f.id) ? "pointer" : null));

    // microstates: archive countries too small to see become dots (with a bigger tap target)
    const tiny = land.filter((f) => isoById.has(f.id) && path.area(f) < (phone ? 4 : 14));
    dotSel = gDots.selectAll("g.dot").data(tiny, (f) => f.id).join((en) => {
      const g = en.append("g").attr("class", "dot");
      g.append("circle").attr("class", "hit").attr("r", 9).attr("fill", "transparent");
      g.append("circle").attr("class", "vis mark").attr("r", phone ? 3 : 3.5).attr("stroke", N.paper).attr("stroke-width", 0.75);
      return g;
    }).attr("transform", (f) => `translate(${path.centroid(f)})`).style("cursor", "pointer");

    // where the news came from (annotation, not data)
    const vat = projection([12.4534, 41.9029]);
    gNote.selectAll("*").remove();
    gNote.append("circle").attr("cx", vat[0]).attr("cy", vat[1]).attr("r", 2.5).attr("fill", N.ink);
    gNote.append("text").attr("class", "halo").attr("x", vat[0] - 8).attr("y", vat[1] - 8).attr("text-anchor", "end")
      .attr("font-size", 12).attr("font-weight", 700).attr("fill", N.ink).text("Vatican City");

    // squares: one column per refresh, stacked from the bottom, 5 per row
    const colW = W / bins.length;
    const per = 5;
    const size = Math.max(5, Math.min(14, Math.floor((colW - 10) / per) - 3));
    const gap = phone ? 2 : 3;
    const byBin = d3.range(bins.length).map((b) => trending.filter((r) => r.bin === b));
    const maxRows = Math.ceil(d3.max(byBin, (l) => l.length) / per);
    const top = 46, base = top + maxRows * (size + gap) + 4;
    const SH = base + 22;
    sqSvg.attr("viewBox", `0 0 ${W} ${SH}`).attr("width", W).attr("height", SH);
    const placed = [];
    byBin.forEach((list, b) => list.forEach((r, i) => placed.push({
      r, b, x: b * colW + 2 + (i % per) * (size + gap), y: base - (Math.floor(i / per) + 1) * (size + gap),
    })));
    sqSel = sqSvg.selectAll("rect.sq").data(placed, (d) => d.r.iso2).join("rect")
      .attr("class", "sq mark").attr("id", (d) => `ops-${d.r.iso2}`)
      .attr("x", (d) => d.x).attr("y", (d) => d.y).attr("width", size).attr("height", size).attr("rx", 1.5)
      .style("cursor", "pointer");
    sqSvg.selectAll("text.bin").data(bins).join("text").attr("class", "bin")
      .attr("x", (d, i) => i * colW + 2).attr("y", base + 16).attr("font-size", phone ? 10 : 12)
      .attr("font-weight", (d, i) => (i === 0 ? 700 : 400)).attr("fill", N.muted).text((d) => d);
    sqSvg.selectAll("text.cnt").data(byBin).join("text").attr("class", "cnt")
      .attr("x", (d, i) => i * colW + 2)
      .attr("y", (d) => base - Math.ceil(d.length / per) * (size + gap) - 6)
      .attr("font-size", phone ? 12 : 15).attr("font-weight", 700).attr("fill", N.ink).text((d) => d.length);
    // annotation: more than half within 10 minutes (after the 08:00 column)
    const ax = 2 * colW - 4;
    sqSvg.selectAll("g.note").data([0]).join((en) => {
      const g = en.append("g").attr("class", "note");
      g.append("line");
      g.append("text").attr("class", "l1");
      g.append("text").attr("class", "l2");
      return g;
    }).call((g) => {
      g.select("line").attr("x1", ax).attr("x2", ax).attr("y1", 8).attr("y2", base)
        .attr("stroke", N.muted).attr("stroke-dasharray", "3 3");
      const half = cum(1) > data.countries_24h / 2;
      g.select(".l1").attr("x", ax + 6).attr("y", 18).attr("font-size", phone ? 10 : 12).attr("fill", N.ink)
        .text(half ? `More than half of the ${data.countries_24h} countries` : "");
      g.select(".l2").attr("x", ax + 6).attr("y", 33).attr("font-size", phone ? 10 : 12).attr("fill", N.ink)
        .text(half ? "were searching within 10 minutes" : "");
    });

    items = trending.map((r) => ({ r, el: document.getElementById(`op-${r.iso2}`) }));
    bindEvents();
    paint(0);
  }

  // ------------------------------------------------------------------ painting
  function strokeFor(iso) {
    return iso === (hot && hot.iso2) || iso === (found && found.iso2);
  }
  function paint(dur = ms(300)) {
    const t = d3.transition().duration(dur).ease(d3.easeCubicInOut);
    mapSel.filter((f) => isoById.has(f.id)).transition(t)
      .attr("fill", (f) => fillOf(byIso.get(isoById.get(f.id)), k));
    mapSel.filter((f) => !isoById.has(f.id)).attr("fill", N.land);
    // outlines on top: re-append the outlined path so its stroke isn't covered by neighbours
    // "Later" countries are white on the map, so they get a light PuBu outline to stay visible
    const isLater = (f) => { const r = byIso.get(isoById.get(f.id)); return r && r.trending && r.bin === LAST && k >= LAST; };
    mapSel.attr("stroke", (f) => (strokeFor(isoById.get(f.id)) ? N.ink : isLater(f) ? P[2] : N.paper))
      .attr("stroke-width", (f) => (strokeFor(isoById.get(f.id)) ? 2 : isLater(f) ? 1 : 0.5));
    mapSel.filter(isLater).raise();
    mapSel.filter((f) => strokeFor(isoById.get(f.id))).raise();
    dotSel.select("circle.vis").attr("fill", (f) => fillOf(byIso.get(isoById.get(f.id)), k))
      .attr("stroke", (f) => (strokeFor(isoById.get(f.id)) ? N.ink : N.paper))
      .attr("stroke-width", (f) => (strokeFor(isoById.get(f.id)) ? 2 : 0.75));
    sqSel.attr("fill", (d) => (d.b <= k ? SHADE[d.b] : "transparent"))
      .attr("stroke", (d) => (strokeFor(d.r.iso2) ? N.ink : d.b === LAST && d.b <= k ? P[1] : "none"))
      .attr("stroke-width", (d) => (strokeFor(d.r.iso2) ? 2 : 1))
      .attr("visibility", (d) => (d.b <= k ? "visible" : "hidden"));
    sqSvg.selectAll("text.cnt").attr("visibility", (d, i) => (i <= k ? "visible" : "hidden"));
    counter.textContent = counterText(k);
    range.value = String(Math.max(0, k));
    range.setAttribute("aria-valuetext", counterText(Math.max(0, k)));
    rangeLabel.textContent = counterText(k);
  }

  function dropColumn(b) {
    if (reducedMotion()) return;
    sqSel.filter((d) => d.b === b)
      .attr("transform", "translate(0,-24)").attr("opacity", 0)
      .transition().duration(400).ease(d3.easeCubicOut).delay((d, i) => i * 6)
      .attr("transform", null).attr("opacity", 1);
  }

  // ------------------------------------------------------------------ playback
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function play() {
    stop();
    k = -1;
    paint(0);
    let b = 0;
    const tick = () => {
      k = b;
      paint(reducedMotion() ? 0 : 300);
      dropColumn(b);
      announce(counterText(k));
      b += 1;
      if (b > LAST) { stop(); finish(); }
    };
    tick();
    timer = setInterval(tick, STEP_MS);
  }
  function finish() {
    played = true;
    scrub.hidden = false;
    playBtn.textContent = "▶ Replay";
  }
  playBtn.addEventListener("click", play);
  range.addEventListener("input", () => { stop(); k = +range.value; paint(0); });

  // ------------------------------------------------------------------ hover / tap / keyboard
  function setHot(r, ev, anchor) {
    hot = r;
    paint(0);
    if (r) tip.show(tipHtml(r), ev, anchor); else tip.hide();
  }
  function bindEvents() {
    const over = (getR) => (sel) => sel
      .on("pointerenter", (ev, d) => { if (ev.pointerType !== "touch") setHot(getR(d), ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType !== "touch" && !tip.pinned) { hot = null; paint(0); tip.hide(); } })
      .on("click", (ev, d) => { ev.stopPropagation(); setHot(getR(d), ev, ev.currentTarget); });
    mapSel.filter((f) => isoById.has(f.id)).call(over((f) => byIso.get(isoById.get(f.id))));
    dotSel.call(over((f) => byIso.get(isoById.get(f.id))));
    sqSel.call(over((d) => d.r));
  }
  keyNav(svg.node(), {
    items: () => items,
    onFocus: ({ r, el }) => setHot(r, null, el),
    onEnter: ({ r, el }) => tip.pin(tipHtml(r), el),
    onEscape: () => { hot = null; tip.hide(true); paint(0); },
    onBlur: () => { if (!tip.pinned) { hot = null; tip.hide(); paint(0); } },
  });
  onEscape(() => { if (found) { found = null; paint(0); } });

  // ------------------------------------------------------------------ find your country
  function sentence(r) {
    if (!r.trending) return `In ${r.name}, Pope Francis did not trend within 24 hours.`;
    const m = r.minutes_after_first;
    const after = m === 0 ? "in the very first refresh, with the first countries"
      : m < 60 ? `${WORDS[m / 10]} minutes after the first countries`
      : m < 120 ? "about an hour after the first countries" : `${Math.round(m / 60)} hours after the first countries`;
    const clock = r.local_clock.replace(":00 ", " ");
    const half = r.bin <= LAST - 1 && cum(r.bin) > data.countries_24h / 2 && r.bin > 0
      ? ` By then more than half of the countries were searching.` : "";
    return `In ${r.name}, Pope Francis started trending at ${clock}, ${after}.${half}`;
  }
  searchBox(root.querySelector(".op-search"), {
    label: "Find your country", placeholder: "Find your country",
    items: countries.countries.map((c) => ({ id: c.iso2, name: c.name })),
    onPick: (it) => {
      found = byIso.get(it.id);
      result.textContent = sentence(found);
      paint(ms(300));
    },
    onNoMatch: () => { found = null; result.textContent = "We don't have data for that country."; paint(0); },
  });

  // ------------------------------------------------------------------ show the data
  showTheData(root, {
    caption: `${trending.length} countries where Pope Francis trended within 24 hours of the announcement, Apr. 21, 2025`,
    filename: "pope-francis-first-trending",
    columns: [
      { key: "name", label: "Country" },
      { key: "refresh", label: "First trending (UTC)", sortValue: (r) => r.minutes_after_first },
      { key: "minutes_after_first", label: "Minutes after the first refresh", num: true },
      { key: "local_clock", label: "Local time", format: (v, r) => `${v} (${r.city})`, sortValue: (r) => r.local_time.slice(11, 16) },
      { key: "phrasings_first", label: "Searched as", format: (v) => (v || []).join("; ") },
    ],
    rows: trending,
  });

  // ------------------------------------------------------------------ start
  render();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(mapWrap);

  function showEnd() { stop(); k = LAST; paint(0); finish(); playBtn.textContent = "▶ Play"; }
  if (reducedMotion()) showEnd();
  else onEnterView(mapWrap, () => { if (!played && !reducedMotion()) play(); });
  onMotionChange((red) => { if (red && !played) showEnd(); });
}
