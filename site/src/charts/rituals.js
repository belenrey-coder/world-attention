// Chapter 5 · Rituals (docs/SPEC.md, Chapter 5): the weather at 6 a.m. going round the world (map with solar-time
// meridians, play, scrubber, pick your country), a usual day over every day of the archive, and the holiday circle
// that unrolls into two timelines.
import * as d3 from "d3";
import { feature } from "topojson-client";
import worldUrl from "world-atlas/countries-50m.json?url";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { keyNav, ms, reducedMotion, onEscape, liveRegion } from "../lib/a11y.js";
import { pubu, gnbu, neutral } from "../lib/colors.js";

let worldP = null;
const loadWorld = () => (worldP ||= Promise.all([
  fetch(worldUrl).then((r) => r.json()),
  fetch(`${import.meta.env.BASE_URL}data/countries.json`).then((r) => r.json()),
]));
const clock = (h) => (h === 0 ? "midnight" : h === 12 ? "noon" : `${h % 12} ${h < 12 ? "a.m." : "p.m."}`);
const pad = (h) => `${String(h).padStart(2, "0")}:00`;
// "Japan and South Korea"; "7 countries, including Mexico, Honduras, El Salvador and Guatemala"
const and = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`);
const listNames = (a) => (a.length <= 4 ? and(a) : `${a.length} countries, including ${and(a.slice(0, 4))}`);

// ==================================================================== the weather at 6 a.m., everywhere
export async function mountWeatherMap(root, data) {
  const [world, cl] = await loadWorld();
  const G = gnbu();
  const N = neutral();
  const isoById = new Map(cl.countries.map((c) => [c.id, c.iso2]));
  const byIso = new Map(data.countries.map((c) => [c.iso2, c]));
  const land = feature(world, world.objects.countries).features.filter((f) => f.id !== "010");
  const ordered = data.countries.slice().sort((a, b) => a.utc_peak_hour - b.utc_peak_hour || a.utc_offset_h - b.utc_offset_h);
  root.innerHTML = `
    <p class="chart-title">The weather at 6 a.m., everywhere</p>
    <p class="chart-sub">Each country lights up at the local hour its weather searches usually peak. The lines show where it is each hour of the day; they move west as the day goes by.</p>
    <div class="controls wm-controls">
      <button type="button" class="wm-play">▶ Play one day</button>
      <label class="sr-only" for="wm-range">World time (UTC)</label>
      <input id="wm-range" type="range" min="0" max="23" step="1" value="12">
      <span class="wm-time"></span>
      <span class="wm-pick"></span>
    </div>
    <div class="legend" aria-hidden="true"><span><i class="swatch" style="background:${G.blue}"></i>its usual weather peak (mostly 6 a.m.)</span><span><i class="swatch" style="background:${N.off}"></i>any other hour</span><span>Lines: where it is each hour of the day; bold = 6 a.m.</span></div>
    <div class="wm-svg"></div>
    <p class="result wm-caption" aria-live="polite"></p>
    <p class="result wm-card" aria-live="polite"></p>
    <p class="source">Countries placed at their usual peak hour over the archive and their typical UTC offset (United States, Canada and Russia from their regional feeds, each in its zone; ${data.countries.length} countries with 20+ weather trends). Lines are solar time. Weather “today” searches only. As of ${data.as_of}.</p>`;
  const wrap = root.querySelector(".wm-svg");
  const range = root.querySelector("#wm-range");
  const timeEl = root.querySelector(".wm-time");
  const caption = root.querySelector(".wm-caption");
  const card = root.querySelector(".wm-card");
  const playBtn = root.querySelector(".wm-play");
  const announce = liveRegion(root);
  const svg = d3.select(wrap).append("svg").attr("role", "img")
    .attr("aria-label", "Map: at each hour of world time, the countries where it is the usual hour of the morning weather search light up; the 6 a.m. line moves west through the day. Arrow keys move country by country from east to west.");
  const gLand = svg.append("g"), gMer = svg.append("g").attr("fill", "none"), gLab = svg.append("g");
  const tip = createTooltip(root);
  const proj = d3.geoEqualEarth();
  const path = d3.geoPath(proj);
  let hour = 12, picked = null, hot = null, timer = null, paths;

  function render() {
    const W = wrap.clientWidth || 1100;
    proj.fitWidth(W, { type: "FeatureCollection", features: land });
    const H = Math.ceil(path.bounds({ type: "FeatureCollection", features: land })[1][1]) + 22;
    proj.translate([proj.translate()[0], proj.translate()[1] + 18]);
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    paths = gLand.selectAll("path").data(land, (f) => f.id).join("path").attr("d", path)
      .attr("class", (f) => (byIso.has(isoById.get(f.id)) ? "mark" : null)).attr("id", (f) => `wm-${isoById.get(f.id)}`)
      .attr("stroke", N.paper).attr("stroke-width", 0.5).style("cursor", (f) => (byIso.has(isoById.get(f.id)) ? "pointer" : null));
    bind();
    paint(0);
  }
  function lit(c) { return c && c.utc_peak_hour === hour; }
  function paint(dur = ms(300)) {
    paths.transition().duration(dur).attr("fill", (f) => {
      const c = byIso.get(isoById.get(f.id));
      return lit(c) ? G.blue : c ? N.off : N.land;
    });
    const out = (f) => { const iso = isoById.get(f.id); return (picked && picked.iso2 === iso) || (hot && hot.iso2 === iso); };
    paths.attr("stroke", (f) => (out(f) ? N.ink : N.paper)).attr("stroke-width", (f) => (out(f) ? 2 : 0.5));
    paths.filter(out).raise();
    // solar-time meridians: at world time T, local solar time k is at longitude (k - T) * 15
    const mers = d3.range(24).map((k) => {
      let lon = ((k - hour) * 15 + 540) % 360 - 180;
      return { k, lon };
    });
    gMer.selectAll("path").data(mers, (d) => d.k).join("path")
      .attr("d", (d) => path({ type: "LineString", coordinates: d3.range(-58, 84, 2).map((lat) => [d.lon, lat]) }))
      .attr("stroke", (d) => (d.k === 6 ? G.blue : N.context)).attr("stroke-width", (d) => (d.k === 6 ? 1.6 : 0.7))
      .attr("stroke-dasharray", (d) => (d.k === 6 ? null : "2 3"));
    const every = (wrap.clientWidth || 1100) < 560 ? 6 : 3;
    gLab.selectAll("text").data(mers.filter((d) => d.k % every === 0), (d) => d.k).join("text").attr("class", "halo")
      .attr("x", (d) => (proj([d.lon, 84]) || [0, 0])[0]).attr("y", 12).attr("text-anchor", "middle")
      .attr("font-size", (d) => (d.k === 6 ? 13 : 10)).attr("font-weight", (d) => (d.k === 6 ? 700 : 400))
      .attr("fill", (d) => (d.k === 6 ? G.blue : N.faint)).text((d) => clock(d.k));
    range.value = String(hour);
    range.setAttribute("aria-valuetext", `${pad(hour)} world time`);
    timeEl.textContent = `${pad(hour)} world time (UTC)`;
    const now = data.countries.filter(lit).sort((a, b) => a.utc_offset_h - b.utc_offset_h);
    caption.textContent = now.length
      ? `${pad(hour)} world time: the usual weather hour in ${listNames(now.map((c) => c.name))}.`
      : `${pad(hour)} world time: it is the middle of the night where most people live; few countries are at their weather hour.`;
  }
  function setHour(h, dur) { hour = (h + 24) % 24; paint(dur); }
  const html = (c) => `<div class="tt-title">${c.name}</div><div>Weather searches peak at ${clock(c.local_peak_hour)} local, ${pad(c.utc_peak_hour)} world time</div><div class="tt-muted">Searched as “${c.phrasing}”</div>`;
  function bind() {
    paths.filter((f) => byIso.has(isoById.get(f.id)))
      .on("pointerenter", (ev, f) => { if (ev.pointerType === "touch") return; hot = byIso.get(isoById.get(f.id)); paint(0); tip.show(html(hot), ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType === "touch") return; hot = null; paint(0); tip.hide(); })
      .on("click", (ev, f) => { ev.stopPropagation(); hot = byIso.get(isoById.get(f.id)); paint(0); tip.show(html(hot), ev, ev.currentTarget); });
  }
  keyNav(svg.node(), {
    items: () => ordered.map((c) => ({ c, el: document.getElementById(`wm-${c.iso2}`) })),
    onFocus: ({ c, el }) => { hot = c; paint(0); tip.show(html(c), null, el); },
    onEnter: ({ c, el }) => tip.pin(html(c), el),
    onEscape: () => { hot = null; tip.hide(true); paint(0); },
    onBlur: () => { if (!tip.pinned) { hot = null; tip.hide(); paint(0); } },
  });

  // play one day: 0.5 s per hour, once; under reduced motion each press steps one hour
  function stop() { clearInterval(timer); timer = null; playBtn.textContent = reducedMotion() ? "▶ Next hour" : "▶ Play one day"; }
  playBtn.addEventListener("click", () => {
    if (reducedMotion()) { setHour(hour + 1, 0); announce(caption.textContent); return; }
    if (timer) { stop(); return; }
    let h = 0;
    setHour(0, 0);
    playBtn.textContent = "❚❚ Pause";
    timer = setInterval(() => { h += 1; if (h > 23) { stop(); return; } setHour(h, 200); }, 500);
  });
  range.addEventListener("input", () => { stop(); setHour(+range.value, 0); });
  // pick your country
  const sel = document.createElement("select");
  sel.setAttribute("aria-label", "Pick your country");
  sel.innerHTML = `<option value="">Pick your country</option>` + data.countries.slice().sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `<option value="${c.iso2}">${c.name}</option>`).join("");
  root.querySelector(".wm-pick").appendChild(sel);
  sel.addEventListener("change", () => {
    picked = byIso.get(sel.value) || null;
    if (picked) {
      stop();
      setHour(picked.utc_peak_hour, ms(300));
      const d = picked.utc_offset_h >= 0 ? "" : "";
      card.textContent = `In ${picked.name}, weather searches usually peak at ${clock(picked.local_peak_hour)}, which is ${pad(picked.utc_peak_hour)} world time${d}. It is searched as “${picked.phrasing}”.`;
    } else { card.textContent = ""; paint(0); }
  });
  onEscape(() => { if (timer) stop(); });
  showTheData(root, {
    caption: "Each country's usual hour of the morning weather search", filename: "weather-hour-by-country",
    columns: [{ key: "name", label: "Country" }, { key: "local_peak_hour", label: "Local peak hour", num: true },
      { key: "utc_peak_hour", label: "World time (UTC) hour", num: true }, { key: "utc_offset_h", label: "UTC offset (h)", num: true },
      { key: "phrasing", label: "Searched as" }],
    rows: data.countries,
  });
  render();
  if (reducedMotion()) playBtn.textContent = "▶ Next hour";
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(wrap);
}

// ==================================================================== a usual day, every day
export function mountUsualDay(root, data) {
  const P = pubu();
  const G = gnbu();
  const N = neutral();
  const days = data.days;
  const mean = data.usual_day.mean;
  const maxC = d3.max(days, (d) => d3.max(d.today));
  const color = d3.scaleQuantize([0, Math.max(30, maxC)], P.slice(0, 7));
  root.innerHTML = `
    <p class="chart-title">A usual day, every day</p>
    <p class="chart-sub">On a usual day, weather starts trending in about ${Math.round(data.usual_day.peak_mean)} countries at ${data.usual_day.peak_hour} a.m. Below, every day of the archive: the same stripe, day after day. Hover over an hour for its average; hover over a day to see which countries searched.</p>
    <div class="ud-line"></div>
    <div class="ud-grid"><canvas></canvas></div>
    <p class="source">Countries where a weather trend started in each local hour, averaged over ${data.full_coverage_days} days with full collection; light grey rows are days with gaps (or next to one). As of ${data.as_of}.</p>`;
  const lw = root.querySelector(".ud-line");
  const gw = root.querySelector(".ud-grid");
  const canvas = gw.querySelector("canvas");
  const svg = d3.select(lw).append("svg").attr("role", "img").attr("aria-label", `${data.takeaway} Line of the average number of countries starting a weather trend at each local hour; arrow keys move hour by hour.`);
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `Grid of ${days.length} days by 24 local hours, shaded by the countries where a weather trend started; the 6 a.m. column is dark on almost every day. Arrow keys move day by day.`);
  canvas.tabIndex = 0;
  const tip = createTooltip(root);
  let x, W, rowH, M = { l: 60, r: 14 }, focusH = -1, focusD = -1;

  function render() {
    W = lw.clientWidth || 1100;
    const H = 150;
    x = d3.scaleBand(d3.range(24), [M.l, W - M.r]).paddingInner(0);
    const y = d3.scaleLinear([0, Math.ceil(d3.max(mean) / 5) * 5], [H - 22, 18]);
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    svg.selectAll("*").remove();
    svg.append("g").attr("transform", `translate(${M.l},0)`).call(d3.axisLeft(y).ticks(3).tickSize(-(W - M.l - M.r)))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll(".tick line").attr("stroke", N.rule))
      .call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    const cx = (h) => x(h) + x.bandwidth() / 2;
    svg.append("path").attr("d", d3.line().x((v, h) => cx(h)).y((v) => y(v))(mean)).attr("fill", "none").attr("stroke", G.blue).attr("stroke-width", 2.5);
    const pk = data.usual_day.peak_hour;
    svg.append("circle").attr("cx", cx(pk)).attr("cy", y(mean[pk])).attr("r", 4).attr("fill", G.blue);
    svg.append("text").attr("class", "halo").attr("x", cx(pk) + 8).attr("y", y(mean[pk]) + 4).attr("font-size", 12).attr("font-weight", 700).attr("fill", N.ink)
      .text(`${pk} a.m.: about ${Math.round(mean[pk])} countries`);
    svg.append("text").attr("x", M.l).attr("y", 11).attr("font-size", 11).attr("fill", N.muted).text("a usual day: countries where it starts trending, each local hour");
    const cur = svg.append("line").attr("class", "ud-cur").attr("stroke", N.ink).attr("opacity", 0);
    svg.append("rect").attr("x", M.l).attr("y", 0).attr("width", W - M.l - M.r).attr("height", H).attr("fill", "transparent")
      .on("pointermove", (ev) => { const h = hourAt(ev); showHour(h, ev); })
      .on("pointerleave", () => { cur.attr("opacity", 0); tip.hide(); })
      .on("click", (ev) => { ev.stopPropagation(); showHour(hourAt(ev), ev); });
    svg.node().__cur = cur; svg.node().__y = y;
    // grid on a canvas (539 × 24 cells)
    rowH = W < 560 ? 1 : 1.2;
    const GH = Math.ceil(days.length * rowH) + 24;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr; canvas.height = GH * dpr;
    canvas.style.width = `${W}px`; canvas.style.height = `${GH}px`;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, GH);
    days.forEach((d, i) => {
      const y0 = i * rowH;
      if (d.flag) { ctx.fillStyle = N.gap; ctx.fillRect(M.l, y0, W - M.l - M.r, Math.max(1, rowH)); return; }
      d.today.forEach((v, h) => { ctx.fillStyle = v ? color(v) : N.paper; ctx.fillRect(x(h), y0, x.bandwidth() + 0.5, Math.max(1, rowH) + 0.3); });
    });
    ctx.fillStyle = N.muted; ctx.font = '10px "Libre Franklin", sans-serif'; ctx.textAlign = "right";
    days.forEach((d, i) => { if (d.date.endsWith("-01") && ["01", "04", "07", "10"].includes(d.date.slice(5, 7))) ctx.fillText(d3.utcFormat("%b %Y")(new Date(d.date)), M.l - 6, i * rowH + 8); });
    ctx.textAlign = "center";
    [0, 6, 12, 18].forEach((h) => ctx.fillText(clock(h), x(h) + x.bandwidth() / 2, GH - 8));
    if (focusD >= 0) { ctx.strokeStyle = N.ink; ctx.lineWidth = 1.5; ctx.strokeRect(M.l - 1, focusD * rowH - 1, W - M.l - M.r + 2, rowH + 2); }
  }
  const hourAt = (ev) => Math.max(0, Math.min(23, Math.floor((d3.pointer(ev, svg.node())[0] - M.l) / x.step())));
  function showHour(h, ev) {
    const cur = svg.node().__cur;
    cur.attr("x1", x(h) + x.bandwidth() / 2).attr("x2", x(h) + x.bandwidth() / 2).attr("y1", 14).attr("y2", 128).attr("opacity", 1);
    tip.show(`<div class="tt-title">${clock(h)} local</div><div>${mean[h].toFixed(1)} countries on average start a weather trend</div>`, ev, cur.node());
  }
  const fmt = d3.utcFormat("%a, %B %-d, %Y");
  const dayHtml = (d) => `<div class="tt-title">${fmt(new Date(d.date))}</div>` +
    (d.flag ? `<div class="tt-muted">${d.flag === "gap" ? "Collection gap" : "Next to a collection gap"}: counts are low.</div>` : "") +
    `<div>${d.six.length} countries searched the weather at 6 a.m.${d.six.length ? ":" : ""}</div>` +
    (d.six.length ? `<div class="tt-muted">${d.six.slice(0, 14).join(", ")}${d.six.length > 14 ? ", …" : ""}</div>` : "");
  function showDay(i, ev) {
    focusD = i;
    render();
    tip.show(dayHtml(days[i]), ev, canvas);
  }
  canvas.addEventListener("pointermove", (ev) => { const i = Math.max(0, Math.min(days.length - 1, Math.floor(ev.offsetY / rowH))); if (ev.pointerType !== "touch") { tip.show(dayHtml(days[i]), ev); } });
  canvas.addEventListener("pointerleave", () => tip.hide());
  canvas.addEventListener("click", (ev) => { ev.stopPropagation(); showDay(Math.max(0, Math.min(days.length - 1, Math.floor(ev.offsetY / rowH))), ev); });
  // keyboard: line = left/right hours; grid = up/down days
  const lineEl = svg.node();
  lineEl.tabIndex = 0;
  lineEl.addEventListener("keydown", (ev) => {
    const s = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
    if (!s) { if (ev.key === "Escape") tip.hide(true); return; }
    ev.preventDefault();
    focusH = Math.max(0, Math.min(23, (focusH < 0 ? 5 : focusH) + s));
    showHour(focusH);
  });
  lineEl.addEventListener("blur", () => { svg.node().__cur.attr("opacity", 0); tip.hide(); });
  canvas.addEventListener("keydown", (ev) => {
    const s = { ArrowDown: 1, ArrowUp: -1, PageDown: 30, PageUp: -30 }[ev.key];
    if (!s) { if (ev.key === "Escape") { tip.hide(true); focusD = -1; render(); } return; }
    ev.preventDefault();
    showDay(Math.max(0, Math.min(days.length - 1, (focusD < 0 ? 0 : focusD) + s)));
  });
  canvas.addEventListener("blur", () => { focusD = -1; render(); tip.hide(); });
  showTheData(root, {
    caption: `A usual day: average countries where a weather trend started, by local hour (${data.full_coverage_days} full days)`, filename: "weather-usual-day",
    columns: [{ key: "h", label: "Local hour" }, { key: "v", label: "Average countries", num: true, format: (v) => v.toFixed(2) }],
    rows: mean.map((v, h) => ({ h: clock(h), v })),
  });
  render();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(lw);
}

// ==================================================================== the holiday circle
export async function mountHolidays(root, data) {
  const [world, cl] = await loadWorld();
  const G = gnbu();
  const N = neutral();
  const COL = (h) => (h.moving ? G.blue : G.green);
  const hols = data.holidays;
  const scrollyEl = document.getElementById("rit-scrolly");
  const after = document.getElementById("rit-after");
  const announce = liveRegion(root);
  const doy = (s) => { const d = new Date(s); return d3.utcDay.count(d3.utcYear(d), d); }; // 0-based day of year
  // one spike per day per occurrence
  const spikes = [];
  hols.forEach((h, hi) => h.occurrences.forEach((o, oi) => o.days.forEach(([day, c]) => spikes.push({ h, hi, oi, day, d: doy(day), c }))));
  const peaks = hols.flatMap((h, hi) => h.occurrences.map((o, oi) => ({ h, hi, oi, d: doy(o.peak_day), c: o.peak_countries })));

  root.innerHTML = `<div class="hc-svg"></div>`;
  const wrap = root.querySelector(".hc-svg");
  const svg = d3.select(wrap).append("svg").attr("role", "img")
    .attr("aria-label", `${data.takeaway} Holidays around the year, first and second time: fixed dates (green) land on the same day; moving dates (blue) shift. Arrow keys move holiday by holiday; Enter shows where it was searched both years.`);
  const gGuide = svg.append("g"), gSp = svg.append("g"), gCon = svg.append("g"), gLab = svg.append("g");
  const tip = createTooltip(root);
  const st = { step: -1, m: 0, rot: 1, selected: null, filter: "all", grown: 0, second: 0, conn: 0 };
  let W, H, cx, cy, r0, L, xLin, yBase, lenLin;

  function layout() {
    W = wrap.clientWidth || 720;
    const phone = W < 560;
    H = phone ? 380 : Math.min(600, Math.max(460, window.innerHeight * 0.7));
    const S = Math.min(W, H, phone ? 340 : 600);
    cx = W / 2; cy = H / 2;
    r0 = S * 0.2; L = S * 0.27;
    xLin = d3.scaleLinear([0, 365], [phone ? 8 : 40, W - (phone ? 8 : 40)]);
    yBase = [H * 0.44, H * 0.92];
    lenLin = H * 0.32;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
  }
  const ang = (d) => (d / 365) * 2 * Math.PI - Math.PI / 2;
  // a spike's base and tip at morph m (0 = circle, 1 = timelines) and rotation progress rot (0 = at the first's date)
  function geom(s) {
    const dd = s.oi === 1 && s.h.moving ? s.d - (1 - st.rot) * s.h.shift_days : s.d;
    const a = ang(dd);
    const len = (s.c / 125);
    const pb = [cx + r0 * Math.cos(a), cy + r0 * Math.sin(a)], pt = [cx + (r0 + len * L) * Math.cos(a), cy + (r0 + len * L) * Math.sin(a)];
    const lb = [xLin(dd), yBase[s.oi]], lt = [xLin(dd), yBase[s.oi] - len * lenLin];
    const m = st.m;
    const g = s.oi === 0 ? st.grown : st.second;
    const tip_ = [pt[0] * (1 - m) + lt[0] * m, pt[1] * (1 - m) + lt[1] * m];
    const base = [pb[0] * (1 - m) + lb[0] * m, pb[1] * (1 - m) + lb[1] * m];
    return [base, [base[0] + (tip_[0] - base[0]) * g, base[1] + (tip_[1] - base[1]) * g]];
  }
  const visible = (h) => st.filter === "all" || (st.filter === "moving" ? h.moving : !h.moving);
  function draw() {
    // guides: the circle and month ticks, or two baselines
    gGuide.selectAll("*").remove();
    if (st.m < 0.5) {
      gGuide.append("circle").attr("cx", cx).attr("cy", cy).attr("r", r0).attr("fill", "none").attr("stroke", N.context).attr("opacity", 1 - st.m * 2);
      d3.range(12).forEach((k) => {
        const d = doy(`2025-${String(k + 1).padStart(2, "0")}-01`) + 14;
        const a = ang(d);
        gGuide.append("text").attr("x", cx + (r0 - 14) * Math.cos(a)).attr("y", cy + (r0 - 14) * Math.sin(a) + 3).attr("text-anchor", "middle")
          .attr("font-size", 10).attr("fill", N.muted).attr("opacity", 1 - st.m * 2).text(d3.utcFormat("%b")(new Date(Date.UTC(2025, k, 1))));
      });
    } else {
      [0, 1].forEach((oi) => {
        gGuide.append("line").attr("x1", xLin(0)).attr("x2", xLin(365)).attr("y1", yBase[oi]).attr("y2", yBase[oi]).attr("stroke", N.context).attr("opacity", st.m * 2 - 1);
        gGuide.append("text").attr("x", xLin(0)).attr("y", yBase[oi] - lenLin - 6).attr("font-size", 11).attr("font-weight", 700).attr("fill", N.ink)
          .attr("opacity", st.m * 2 - 1).text(oi === 0 ? "First time" : "Second time");
      });
      d3.range(12).forEach((k) => gGuide.append("text").attr("x", xLin(doy(`2025-${String(k + 1).padStart(2, "0")}-01`) + 14)).attr("y", yBase[1] + 14)
        .attr("text-anchor", "middle").attr("font-size", 10).attr("fill", N.muted).attr("opacity", st.m * 2 - 1).text(d3.utcFormat("%b")(new Date(Date.UTC(2025, k, 1)))));
    }
    const sp = gSp.selectAll("line").data(spikes).join("line").attr("stroke-linecap", "round");
    sp.each(function (s) {
      const [b, t] = geom(s);
      d3.select(this).attr("x1", b[0]).attr("y1", b[1]).attr("x2", t[0]).attr("y2", t[1]);
    })
      .attr("stroke", (s) => (s.oi === 0 && st.second > 0 && st.m < 0.5 ? N.ghost : COL(s.h)))
      .attr("stroke-width", (s) => (st.selected === s.h ? 2.6 : 1.8))
      .attr("opacity", (s) => (s.oi === 1 && st.second === 0 ? 0 : !visible(s.h) ? 0.15 : st.selected && st.selected !== s.h ? 0.35 : 1));
    // connectors between the two peaks (step 4)
    gCon.selectAll("line").data(st.conn > 0 ? hols : []).join("line")
      .attr("x1", (h) => xLin(doy(h.occurrences[0].peak_day))).attr("y1", yBase[0] + 2)
      .attr("x2", (h) => xLin(doy(h.occurrences[0].peak_day)) + (xLin(doy(h.occurrences[1].peak_day)) - xLin(doy(h.occurrences[0].peak_day))) * st.conn)
      .attr("y2", (h) => yBase[0] + 2 + (yBase[1] - (h.occurrences[1].peak_countries / 125) * lenLin - 4 - yBase[0] - 2) * st.conn)
      .attr("stroke", COL).attr("stroke-width", 1).attr("opacity", (h) => (visible(h) ? 0.8 : 0.15));
    drawLabels();
  }
  function drawLabels() {
    const showOcc = st.second > 0 ? 1 : 0;
    const items = hols.map((h, hi) => {
      const p = peaks.find((q) => q.hi === hi && q.oi === (st.m >= 0.5 ? 0 : showOcc));
      const [, t] = geom({ ...p, c: p.c });
      const moved = h.moving && showOcc && st.m < 0.5 ? ` · ${Math.abs(h.shift_days)} days ${h.shift_days < 0 ? "earlier" : "later"}` : "";
      return { h, x: t[0], y: t[1], text: h.name + moved };
    });
    // keep labels apart: on the circle, per side by height; on the timelines, raise labels that crowd in x
    if (st.m < 0.5) {
      [true, false].forEach((right) => {
        const side = items.filter((d) => (d.x >= cx) === right).sort((a, b) => a.y - b.y);
        for (let i = 1; i < side.length; i++) if (side[i].y - side[i - 1].y < 13) side[i].y = side[i - 1].y + 13;
      });
    } else {
      const byX = items.slice().sort((a, b) => a.x - b.x);
      for (let i = 1; i < byX.length; i++) {
        const near = byX.slice(0, i).filter((d) => Math.abs(d.x - byX[i].x) < 84);
        if (near.length) byX[i].y = Math.min(byX[i].y, d3.min(near, (d) => d.y) - 13);
      }
    }
    const g = gLab.selectAll("g").data(st.grown > 0.5 ? items : [], (d) => d.h.name).join((en) => { const gg = en.append("g").style("cursor", "pointer"); gg.append("text").attr("class", "halo"); return gg; });
    g.select("text").attr("x", (d) => d.x + (st.m < 0.5 ? (d.x >= cx ? 4 : -4) : 0)).attr("y", (d) => d.y - 4)
      .attr("text-anchor", (d) => (st.m >= 0.5 ? (d.x < 60 ? "start" : d.x > W - 60 ? "end" : "middle") : d.x >= cx ? "start" : "end")).attr("font-size", 11).attr("font-weight", 700)
      .attr("fill", (d) => COL(d.h)).attr("opacity", (d) => (visible(d.h) ? 1 : 0.2)).text((d) => d.text);
    g.on("click", (ev, d) => { ev.stopPropagation(); select(d.h); });
  }
  function tweenTo(target, dur, done) {
    const from = { ...st };
    if (!dur) { Object.assign(st, target); draw(); done && done(); return; }
    d3.select(svg.node()).interrupt().transition().duration(dur).ease(d3.easeCubicInOut).tween("morph", () => (t) => {
      Object.keys(target).forEach((k) => { st[k] = from[k] + (target[k] - from[k]) * t; });
      draw();
    }).on("end", () => { Object.assign(st, target); draw(); done && done(); });
  }
  const STATES = [
    { grown: 1, second: 0, rot: 0, m: 0, conn: 0 },
    { grown: 1, second: 1, rot: 1, m: 0, conn: 0 },
    { grown: 1, second: 1, rot: 1, m: 1, conn: 0 },
    { grown: 1, second: 1, rot: 1, m: 1, conn: 1 },
  ];
  const DUR = [800, 1200, 1200, 600];
  const BEFORE = { grown: 0, second: 0, rot: 0, m: 0, conn: 0 };
  function go(i, animate) {
    const prev = st.step;
    st.step = i;
    const target = i < 0 ? BEFORE : STATES[i];
    if (!animate || reducedMotion()) { tweenTo(target, 0); }
    else if (i === 1 && prev === 0) {
      // second time draws at the first's dates, then moving ones rotate to their own
      Object.assign(st, { second: 0, rot: 0 });
      tweenTo({ second: 1 }, 500, () => tweenTo({ rot: 1 }, DUR[1]));
    } else tweenTo(target, DUR[i]);
    if (i === 3 && !st.selected) {
      const ram = hols.find((h) => h.name === "Ramadan");
      if (animate) setTimeout(() => { if (!st.selected) select(ram, true); }, 700); else select(ram, true);
    }
    unlock(i === 3);
  }

  // ------------------------------------------------------------------ tap a holiday: countries both years
  const iso2name = new Map(cl.countries.map((c) => [c.iso2, c.name]));
  const isoById = new Map(cl.countries.map((c) => [c.id, c.iso2]));
  const land = feature(world, world.objects.countries).features.filter((f) => f.id !== "010");
  after.innerHTML = `
    <div class="controls hc-controls" role="group" aria-label="Show">
      <span class="rd-show">Show:</span>
      <button type="button" data-f="all" aria-pressed="true" disabled>All</button>
      <button type="button" data-f="fixed" aria-pressed="false" disabled><i class="swatch" style="background:${G.green}"></i> Fixed dates</button>
      <button type="button" data-f="moving" aria-pressed="false" disabled><i class="swatch" style="background:${G.blue}"></i> Moving dates</button>
      <span class="hc-pick"></span>
    </div>
    <div class="hc-explore"><div class="hc-map"></div><p class="result hc-text" aria-live="polite"></p></div>
    <p class="source">Clean holiday groups (hand-checked, 90% precise); windows from 10 days before to 5 days after each holiday. Halloween, Diwali and Eid al-Adha appear once and are left out of the circle. A national trend can come from a minority community, travelers or the news. As of ${data.as_of}.</p>`;
  const fb = after.querySelectorAll("[data-f]");
  const pick = document.createElement("select");
  pick.setAttribute("aria-label", "Pick a holiday");
  pick.disabled = true;
  pick.innerHTML = `<option value="">Pick a holiday</option>` + hols.map((h) => `<option>${h.name}</option>`).join("");
  after.querySelector(".hc-pick").appendChild(pick);
  pick.addEventListener("change", () => { const h = hols.find((x) => x.name === pick.value); if (h) select(h); });
  function unlock(on) {
    if (!on) return;
    fb.forEach((b) => { b.disabled = false; });
    pick.disabled = false;
  }
  fb.forEach((b) => b.addEventListener("click", () => {
    st.filter = b.dataset.f;
    fb.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
  const mapEl = after.querySelector(".hc-map");
  const textEl = after.querySelector(".hc-text");
  const msvg = d3.select(mapEl).append("svg").attr("role", "img");
  const PRIORITY = ["JP", "MX", "BR", "AR", "US", "GB", "IN", "ID", "NG", "KR", "DE", "FR", "SA", "PK", "IR", "TR", "EG", "AU", "CA", "ZA"];
  function select(h, quiet) {
    st.selected = h;
    pick.value = h.name;
    draw();
    const Wm = Math.min(mapEl.clientWidth || 420, 520);
    const proj = d3.geoEqualEarth().fitWidth(Wm, { type: "FeatureCollection", features: land });
    const path = d3.geoPath(proj);
    const Hm = Math.ceil(path.bounds({ type: "FeatureCollection", features: land })[1][1]) + 2;
    const both = new Set(h.both_years);
    msvg.attr("viewBox", `0 0 ${Wm} ${Hm}`).attr("width", Wm).attr("height", Hm)
      .attr("aria-label", `Map of the ${h.both_years_n} countries where ${h.name} trended both years.`);
    msvg.selectAll("path").data(land).join("path").attr("d", path).attr("stroke", N.paper).attr("stroke-width", 0.4)
      .transition().duration(ms(300)).attr("fill", (f) => (both.has(isoById.get(f.id)) ? COL(h) : N.land));
    const incl = PRIORITY.filter((c) => both.has(c)).slice(0, 4).map((c) => iso2name.get(c));
    const [o1, o2] = h.occurrences;
    const when = h.moving ? ` Its date moved ${Math.abs(h.shift_days)} days ${h.shift_days < 0 ? "earlier" : "later"} (${o1.date} → ${o2.date}).` : "";
    textEl.innerHTML = `<b>${h.name}</b> trended in <b>${h.both_years_n} countries both years</b>${incl.length ? `, including ${incl.slice(0, -1).join(", ")}${incl.length > 1 ? " and " : ""}${incl[incl.length - 1]}` : ""}. Its widest days: ${o1.peak_countries} countries in ${o1.year}, ${o2.peak_countries} in ${o2.year}.${when}`;
    if (!quiet) announce(textEl.textContent);
  }
  // hover a spike: holiday, day, countries
  const fmt = d3.utcFormat("%B %-d, %Y");
  gSp.on("pointermove", (ev) => {
    const s = d3.select(ev.target).datum();
    if (!s || !s.h) return;
    tip.show(`<div class="tt-title">${s.h.name}</div><div>${fmt(new Date(s.day))}: ${s.c} countries</div><div class="tt-muted">${s.h.moving ? "moving date" : "fixed date"}</div>`, ev);
  }).on("pointerleave", () => tip.hide())
    .on("click", (ev) => { const s = d3.select(ev.target).datum(); if (s && s.h && st.step >= 3) { ev.stopPropagation(); select(s.h); } });
  // keyboard: arrows move holiday by holiday; Enter selects
  let ki = -1;
  keyNav(svg.node(), {
    items: () => hols.map((h) => ({ h, el: null })),
    onFocus: ({ h }, i) => { ki = i; st.selected = h; draw(); tip.show(`<div class="tt-title">${h.name}</div><div>${h.occurrences.map((o) => `${o.year}: ${o.peak_countries} countries`).join(" · ")}</div>`, null, gLab.node()); },
    onEnter: ({ h }) => select(h),
    onEscape: () => { tip.hide(true); },
    onBlur: () => tip.hide(),
  });
  onEscape(() => tip.hide(true));

  showTheData(after, {
    caption: "Holidays that came twice: widest day and countries both years", filename: "holidays-both-years",
    columns: [{ key: "name", label: "Holiday" }, { key: "type", label: "Date" },
      { key: "d1", label: "First date" }, { key: "p1", label: "Widest day, first (countries)", num: true },
      { key: "d2", label: "Second date" }, { key: "p2", label: "Widest day, second", num: true },
      { key: "shift_days", label: "Shift (days)", num: true }, { key: "both_years_n", label: "Countries both years", num: true }],
    rows: hols.map((h) => ({ ...h, type: h.moving ? "moving" : "fixed", d1: h.occurrences[0].date, p1: h.occurrences[0].peak_countries, d2: h.occurrences[1].date, p2: h.occurrences[1].peak_countries })),
  });

  layout();
  draw();
  scrolly(scrollyEl, (i, dir, { animate }) => go(i, animate));
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { layout(); draw(); if (st.selected) select(st.selected, true); }, 150); }).observe(wrap);
}
