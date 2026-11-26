// Your turn (docs/SPEC.md, Your turn): every hour of the 18 months on a map where countries searching the same thing
// share a color (frames loaded per month on demand), a day strip, an hour slider, jump buttons, and Country Wrapped.
import * as d3 from "d3";
import { feature } from "topojson-client";
import worldUrl from "world-atlas/countries-50m.json?url";
import { onEnterView } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { ms, reducedMotion, liveRegion, onEscape } from "../lib/a11y.js";
import { gnbu, neutral, hatchPattern } from "../lib/colors.js";
import { loadData } from "../lib/data.js";

const JUMPS = [
  { label: "Pope Francis dies", date: "2025-04-21", hour: 8 },
  { label: "ChatGPT goes down", date: "2025-01-23", hour: 12 },
  { label: "Champions League final", date: "2025-05-31", hour: 20 },
  { label: "New Year’s Eve", date: "2025-12-31", hour: 23 },
  { label: "Iran, US strikes", date: "2025-06-22", hour: 2 },
];
const fmtDay = d3.utcFormat("%A, %B %-d, %Y");
const pct = (v) => `${Math.round(v * 100)}%`;
const clock = (h) => (h === 0 ? "midnight" : h === 12 ? "noon" : `${h % 12} ${h < 12 ? "a.m." : "p.m."}`);

export async function mountYourTurn(rootEl, daysData) {
  const G = gnbu();
  const N = neutral();
  const SLOT = [G.teal, G.green, G.sky, G.aqua, G.mint];
  const pale = (c) => d3.interpolateRgb(c, "#ffffff")(0.58);
  const [world, cl, wIndex] = await Promise.all([fetch(worldUrl).then((r) => r.json()), loadData("countries.json"), loadData("wrapped/index.json")]);
  const isoById = new Map(cl.countries.map((c) => [c.id, c.iso2]));
  const tzOf = new Map(cl.countries.map((c) => [c.iso2, c.tz]));
  const nameOf = new Map(cl.countries.map((c) => [c.iso2, c.name]));
  const land = feature(world, world.objects.countries).features.filter((f) => f.id !== "010");
  const days = daysData.days;
  const dayIdx = new Map(days.map((d, i) => [d.date, i]));
  const main = document.getElementById("yt-main");
  const cardEl = document.getElementById("yt-card");
  const compareEl = document.getElementById("yt-compare");
  const announce = liveRegion(main);

  main.innerHTML = `
    <p class="chart-title yt-when" aria-live="polite"></p>
    <div class="controls yt-jumps" role="group" aria-label="Jump to"><span class="rd-show">Jump to:</span>${JUMPS.map((j, i) => `<button type="button" data-j="${i}">${j.label}</button>`).join("")}</div>
    <div class="yt-map" tabindex="0" role="img" aria-roledescription="map"></div>
    <p class="result yt-gapmsg" hidden>No data for this hour: Google’s collection had a gap.</p>
    <ul class="yt-legend" aria-live="polite"></ul>
    <div class="controls yt-hour">
      <button type="button" class="yt-play">▶ Play</button>
      <label class="sr-only" for="yt-range">Hour of the day (world time)</label>
      <input id="yt-range" type="range" min="0" max="23" step="1" value="8">
      <span class="yt-hlabel"></span>
    </div>
    <p class="chart-sub" style="margin:10px 0 4px">Pick a day: each bar is the day’s widest moment; dark blue = a shock.</p>
    <div class="yt-strip" tabindex="0" role="slider" aria-label="Day" aria-valuemin="0" aria-valuemax="${days.length - 1}"></div>
    <p class="source">Every country where a shared topic is active is colored. Strong color: over half of its countries started it in the last 3 hours (spreading now). Pale: it started earlier and lingers (trends stay active up to 24 hours). Hatched: gaps in the data. Times are UTC unless local. As of ${daysData.as_of}.</p>`;
  const mapWrap = main.querySelector(".yt-map");
  const legend = main.querySelector(".yt-legend");
  const when = main.querySelector(".yt-when");
  const gapMsg = main.querySelector(".yt-gapmsg");
  const range = main.querySelector("#yt-range");
  const hlabel = main.querySelector(".yt-hlabel");
  const playBtn = main.querySelector(".yt-play");
  const stripEl = main.querySelector(".yt-strip");
  const tip = createTooltip(main);

  // ------------------------------------------------------------------ map
  const svg = d3.select(mapWrap).append("svg");
  const hatch = hatchPattern(svg);
  const gLand = svg.append("g");
  const loading = svg.append("text").attr("class", "halo").attr("text-anchor", "middle").attr("font-size", 14).attr("fill", N.muted);
  const proj = d3.geoEqualEarth();
  const path = d3.geoPath(proj);
  let paths, W, H;
  const st = { day: dayIdx.get("2025-04-21"), hour: 8, frame: null, month: null, hover: null, timer: null };
  const frames = new Map();
  function frameFor(month) {
    if (!frames.has(month)) frames.set(month, loadData(`frames/${month}.json`));
    return frames.get(month);
  }

  function renderMap() {
    W = mapWrap.clientWidth || 760;
    proj.fitWidth(W, { type: "FeatureCollection", features: land });
    H = Math.ceil(path.bounds({ type: "FeatureCollection", features: land })[1][1]) + 2;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    paths = gLand.selectAll("path").data(land, (f) => f.id).join("path").attr("d", path)
      .attr("stroke", N.paper).attr("stroke-width", 0.4).attr("fill", N.nodata);
    loading.attr("x", W / 2).attr("y", H / 2);
    bindMap();
    paint(0);
  }

  // what each archive country shows this hour
  function hourState() {
    const f = st.frame;
    if (!f) return null;
    const date = days[st.day].date;
    const key = `${date}T${String(st.hour).padStart(2, "0")}`;
    const i = f.hours.indexOf(key);
    if (i < 0) return { gap: true, i: -1 };
    const gap = f.gap_hours.includes(i);
    const shared = f.shared[i] || [];
    // colors: the first shock takes deep blue (#084081, as deaths in Shocks), the others go in GnBu order
    let slot = 0, shockUsed = false;
    const items = shared.map(([ti, n, k, members, n3]) => {
      let color;
      if (k === 0 && !shockUsed) { color = G.deep; shockUsed = true; } else { color = SLOT[slot]; slot += 1; }
      return { name: f.topics[ti][0], n, kind: f.kinds[k], members: new Set(members), n3, strong: n3 > n / 2, color };
    });
    const ofCountry = new Map();
    f.countries.forEach((iso, j) => {
      const it = items.find((x) => x.members.has(j));
      const own = f.top[i][j] >= 0 ? f.topics[f.top[i][j]][0] : null;
      ofCountry.set(iso, { shared: it || null, own });
    });
    return { gap, i, items, ofCountry };
  }
  function fillFor(iso, hs) {
    if (!hs || hs.gap) return hs && hs.gap ? hatch : N.nodata;
    const c = hs.ofCountry.get(iso);
    if (!c) return N.nodata;
    if (c.shared) return c.shared.strong ? c.shared.color : pale(c.shared.color);
    return c.own ? N.own : N.nodata;
  }
  function paint(dur = ms(300)) {
    const hs = hourState();
    loading.text(st.frame ? "" : `Loading ${d3.utcFormat("%B %Y")(new Date(days[st.day].date))}…`);
    paths.transition().duration(dur).attr("fill", (f) => (isoById.has(f.id) ? fillFor(isoById.get(f.id), hs) : N.nodata));
    paths.attr("stroke", (f) => (st.hover && isoById.get(f.id) === st.hover ? N.ink : N.paper))
      .attr("stroke-width", (f) => (st.hover && isoById.get(f.id) === st.hover ? 2 : 0.4));
    if (st.hover) paths.filter((f) => isoById.get(f.id) === st.hover).raise();
    gapMsg.hidden = !(hs && hs.gap);
    const date = new Date(days[st.day].date);
    when.innerHTML = `${fmtDay(date)} <span class="chart-sub">${String(st.hour).padStart(2, "0")}:00 world time</span>`;
    range.value = String(st.hour);
    range.setAttribute("aria-valuetext", `${String(st.hour).padStart(2, "0")}:00 world time`);
    hlabel.textContent = `${String(st.hour).padStart(2, "0")}:00`;
    legend.innerHTML = !hs ? "" : hs.gap ? "" : hs.items.map((it) =>
      `<li><i class="swatch" style="background:${it.strong ? it.color : pale(it.color)}"></i><b>${esc(it.name)}</b> <span class="tt-muted">${it.n} countries, ${it.strong ? `${it.n3} in the last 3 hours` : "lingering from earlier"}</span></li>`).join("") +
      `<li><i class="swatch" style="background:${N.own}"></i><span class="tt-muted">its own search (hover to see it)</span></li>`;
    mapWrap.setAttribute("aria-label", hs && hs.items && hs.items.length
      ? `${fmtDay(date)}, ${String(st.hour).padStart(2, "0")}:00 world time. Shared topics: ${hs.items.map((x) => `${x.name}, ${x.n} countries`).join("; ")}. Left and right arrows change the hour, Page Up and Page Down the day.`
      : `${fmtDay(date)}, ${String(st.hour).padStart(2, "0")}:00 world time.`);
    drawStripHandle();
    if (table) table.update(hourRows(hs));
  }
  function hourRows(hs) {
    if (!hs || hs.gap) return [];
    return [...hs.ofCountry.entries()].map(([iso, c]) => ({ name: nameOf.get(iso), own: c.own || "", shared: c.shared ? c.shared.name : "",
      kind: c.shared ? c.shared.kind : "", spreading: c.shared ? (c.shared.strong ? "spreading" : "lingering") : "" }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }
  let table = null;
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  async function go(day, hour, { fade = false } = {}) {
    st.day = Math.max(0, Math.min(days.length - 1, day));
    st.hour = (hour + 24) % 24;
    const month = days[st.day].date.slice(0, 7);
    if (st.month !== month) {
      st.month = month;
      st.frame = null;
      paint(0);
      const f = await frameFor(month);
      if (st.month !== month) return;
      st.frame = f;
    }
    paint(fade ? ms(600) : ms(300));
  }

  // tooltip: country · local time · its top search · the shared topic it is part of
  function tipHtml(iso) {
    const hs = hourState();
    const name = nameOf.get(iso);
    const tz = tzOf.get(iso);
    const t = new Date(`${days[st.day].date}T${String(st.hour).padStart(2, "0")}:00:00Z`);
    const local = tz ? t.toLocaleTimeString("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit" }) : "";
    if (!hs || hs.gap) return `<div class="tt-title">${name}</div><div class="tt-muted">No data for this hour.</div>`;
    const c = hs.ofCountry.get(iso);
    return `<div class="tt-title">${name}</div><div class="tt-muted">${local} local time</div>` +
      (c && c.own ? `<div>Its top search: <b>${esc(c.own)}</b></div>` : `<div class="tt-muted">No trend active this hour.</div>`) +
      (c && c.shared ? `<div>Part of: ${esc(c.shared.name)} (${c.shared.n} countries)</div>` : "");
  }
  function bindMap() {
    paths.filter((f) => isoById.has(f.id))
      .on("pointerenter", (ev, f) => { if (ev.pointerType === "touch") return; st.hover = isoById.get(f.id); paint(0); tip.show(tipHtml(st.hover), ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType === "touch") return; st.hover = null; paint(0); tip.hide(); })
      .on("click", (ev, f) => { ev.stopPropagation(); st.hover = isoById.get(f.id); paint(0); tip.show(tipHtml(st.hover), ev, ev.currentTarget); });
  }
  onEscape(() => { st.hover = null; tip.hide(true); paint(0); stop(); });

  // ------------------------------------------------------------------ day strip
  const ssvg = d3.select(stripEl).append("svg");
  const shatch = hatchPattern(ssvg);
  let sx, SH = 70;
  function renderStrip() {
    const Ws = stripEl.clientWidth || 760;
    sx = d3.scaleBand(d3.range(days.length), [0, Ws]).paddingInner(0);
    const y = d3.scaleLinear([0, 125], [SH - 16, 4]);
    ssvg.attr("viewBox", `0 0 ${Ws} ${SH}`).attr("width", Ws).attr("height", SH);
    ssvg.selectAll("rect.b").data(days).join("rect").attr("class", "b")
      .attr("x", (d, i) => sx(i)).attr("width", Math.max(0.6, sx.bandwidth() - 0.2))
      .attr("y", (d) => (d.gap ? 4 : y(d.top[0] ? d.top[0].countries : 0)))
      .attr("height", (d) => (d.gap ? SH - 20 : SH - 16 - y(d.top[0] ? d.top[0].countries : 0)))
      .attr("fill", (d) => (d.gap ? shatch : !d.top[0] ? N.nodata : d.top[0].kind === "shock" ? G.deep : d.top[0].kind === "appointment" ? N.barAppt : N.barOther));
    ssvg.selectAll("text.m").data(days.filter((d) => d.date.endsWith("-01") && ["01", "06"].includes(d.date.slice(5, 7)) || (Ws >= 560 && d.date === days[0].date)))
      .join("text").attr("class", "m").attr("x", (d) => sx(dayIdx.get(d.date))).attr("y", SH - 3).attr("font-size", 10).attr("fill", N.muted)
      .text((d) => d3.utcFormat("%b %Y")(new Date(d.date)));
    ssvg.selectAll("g.h").data([0]).join((en) => { const g = en.append("g").attr("class", "h"); g.append("line"); g.append("circle"); return g; });
    drawStripHandle();
  }
  function drawStripHandle() {
    if (!sx) return;
    const x = sx(st.day) + sx.bandwidth() / 2;
    const g = ssvg.select("g.h");
    g.select("line").attr("x1", x).attr("x2", x).attr("y1", 0).attr("y2", SH - 14).attr("stroke", N.ink).attr("stroke-width", 1.5);
    g.select("circle").attr("cx", x).attr("cy", SH - 14).attr("r", 6).attr("fill", N.ink);
    stripEl.setAttribute("aria-valuenow", String(st.day));
    stripEl.setAttribute("aria-valuetext", fmtDay(new Date(days[st.day].date)) + (days[st.day].top[0] ? `: ${days[st.day].top[0].name}, ${days[st.day].top[0].countries} countries` : ""));
  }
  const dayAt = (ev) => Math.max(0, Math.min(days.length - 1, Math.floor(d3.pointer(ev, ssvg.node())[0] / sx.step())));
  ssvg.on("click", (ev) => { stop(); go(dayAt(ev), st.hour); })
    .on("pointermove", (ev) => {
      const d = days[dayAt(ev)];
      tip.show(`<div class="tt-title">${fmtDay(new Date(d.date))}</div>${d.gap ? `<div class="tt-muted">Gap in the data</div>` : d.top[0] ? `<div>${esc(d.top[0].name)}: ${d.top[0].countries} countries (${d.top[0].kind})</div>` : `<div class="tt-muted">No global moment</div>`}`, ev);
    }).on("pointerleave", () => tip.hide())
    .call(d3.drag().on("drag", (ev) => { stop(); const i = Math.max(0, Math.min(days.length - 1, Math.floor(ev.x / sx.step()))); if (i !== st.day) go(i, st.hour); }));

  // ------------------------------------------------------------------ hour slider, play, keys, jumps
  function stop() { clearInterval(st.timer); st.timer = null; playBtn.textContent = reducedMotion() ? "▶ Next hour" : "▶ Play"; }
  playBtn.addEventListener("click", () => {
    if (reducedMotion()) { go(st.day, st.hour + 1); return; }
    if (st.timer) { stop(); return; }
    playBtn.textContent = "❚❚ Pause";
    st.timer = setInterval(() => { if (st.hour >= 23) { stop(); return; } go(st.day, st.hour + 1); }, 1000);
  });
  range.addEventListener("input", () => { stop(); go(st.day, +range.value); });
  function keys(ev) {
    const k = ev.key;
    if (k === "ArrowRight" || k === "ArrowLeft") { ev.preventDefault(); stop(); go(st.day, st.hour + (k === "ArrowRight" ? 1 : -1)); announce(when.textContent); }
    else if (k === "PageDown" || k === "PageUp") { ev.preventDefault(); stop(); go(st.day + (k === "PageDown" ? 1 : -1), st.hour); announce(when.textContent); }
  }
  mapWrap.addEventListener("keydown", keys);
  stripEl.addEventListener("keydown", (ev) => {
    const s = { ArrowRight: 1, ArrowLeft: -1, PageDown: 7, PageUp: -7 }[ev.key];
    if (!s) return;
    ev.preventDefault(); stop(); go(st.day + s, st.hour); announce(stripEl.getAttribute("aria-valuetext"));
  });
  main.querySelectorAll("[data-j]").forEach((b) => b.addEventListener("click", () => {
    const j = JUMPS[+b.dataset.j];
    stop();
    main.querySelectorAll("[data-j]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    go(dayIdx.get(j.date), j.hour, { fade: true });
  }));

  // ------------------------------------------------------------------ Country Wrapped
  const locale = (navigator.languages || [navigator.language || ""]).map((l) => (l.split("-")[1] || "").toUpperCase()).find((r) => wIndex.countries.some((c) => c.iso2 === r));
  cardEl.innerHTML = `<p class="kicker">Country Wrapped</p><label class="sr-only" for="yt-country">Your country</label>
    <select id="yt-country">${wIndex.countries.map((c) => `<option value="${c.iso2}">${c.name}</option>`).join("")}</select>
    <div class="yt-cardbody" aria-live="polite"></div>`;
  const csel = cardEl.querySelector("#yt-country");
  const body = cardEl.querySelector(".yt-cardbody");
  async function showCard(iso) {
    const c = await loadData(`wrapped/${iso}.json`);
    const row = (k, v) => `<tr><th scope="row">${k}</th><td>${v}</td></tr>`;
    const kept = c.local_top5.length
      ? `<ul class="yt-list">${c.local_top5.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
      : `<p class="tt-muted">Almost everything it searched, it shared.</p>`;
    body.innerHTML = `
      <p class="yt-headline">${pct(c.local_share)} of what trended in ${c.name} trended nowhere else. It joined ${c.shocks_joined} of the ${c.shocks_total} biggest shocks.</p>
      <p class="kicker yt-sec">What it kept to itself</p>${kept}
      <p class="tt-muted yt-small">${pct(c.local_share)} of its topics trended nowhere else (${c.local_rank} of ${c.local_rank_of}; ${c.most_local.name} is first at ${pct(c.most_local.share)}).</p>
      <p class="kicker yt-sec">What it shared with the world</p>
      <table class="yt-table"><tbody>
        ${row("Global moments joined", `${c.global_joined.toLocaleString("en-US")} of ${c.global_total.toLocaleString("en-US")}`)}
        ${row("Biggest shocks joined", `${c.shocks_joined} of ${c.shocks_total}${c.biggest_shocks.length ? `<br><span class="tt-muted">${c.biggest_shocks.map((x) => esc(x.name)).join(", ")}</span>` : ""}`)}
        ${row("Among the first 3 countries to search*", c.first3_share == null ? "—" : `${pct(c.first3_share)} of its moments${c.first3_rank ? ` (${c.first3_rank} of ${c.first3_rank_of})` : ""}`)}
        ${row("Waves ridden", `${c.waves_joined} of ${c.waves_total}`)}
        ${row("Share of its shared moments that were scheduled", c.scheduled_share == null ? "—" : `${pct(c.scheduled_share)} (typical: ${pct(c.scheduled_typical)})`)}
        ${row("Weather", c.weather_hour == null ? "too few weather searches" : `${clock(c.weather_hour)} · “${esc(c.weather_phrasings[0] || "")}”`)}
        ${row("Holidays it searched both years", `${c.holidays_both.length} of ${c.holidays_total}`)}
      </tbody></table>
      <p class="kicker yt-sec">Its search twins</p>
      <table class="yt-table"><tbody>
        ${row("Most similar country", c.twin.name)}
        ${row("Most similar without sport", c.twin_no_sport.name)}
        ${c.surprising_twin ? row("Most similar in another language", c.surprising_twin.name) : ""}
      </tbody></table>
      <p class="kicker yt-sec">Its biggest day</p>
      <p>${d3.utcFormat("%B %-d, %Y")(new Date(c.biggest_day.date))}: ${c.biggest_day.trends} trends${c.biggest_day.top_topic ? `, led by <b>${esc(c.biggest_day.top_topic)}</b>` : ""}.</p>
      <p class="source">*Partly reflects how often each country's feed updates (here a new trend every ${c.feed_minutes} minutes, at the median). Ranks among the 120 countries with enough data.${c.low_data ? " This country has little data, so read its numbers with care." : ""}</p>`;
  }
  csel.value = locale || "MX";
  csel.addEventListener("change", () => showCard(csel.value));
  showCard(csel.value);

  // compare: Japan, United States, Brazil
  const cmp = await Promise.all(["JP", "US", "BR"].map((c) => loadData(`wrapped/${c}.json`)));
  compareEl.innerHTML = `<p class="kicker" style="margin-top:28px">Compare</p><ul class="yt-compare">${cmp.map((c) =>
    `<li><b>${c.name}:</b> kept ${pct(c.local_share)} to itself · joined ${c.shocks_joined} of ${c.shocks_total} biggest shocks · weather at ${c.weather_hour == null ? "—" : clock(c.weather_hour)} · most like ${c.twin.name}</li>`).join("")}</ul>`;

  table = showTheData(main, {
    caption: "This hour: each country's top active search and the shared topic it is part of (world time)",
    filename: "hour-by-country",
    columns: [{ key: "name", label: "Country" }, { key: "own", label: "Its top search" }, { key: "shared", label: "Shared topic" },
      { key: "kind", label: "Kind" }, { key: "spreading", label: "Spreading or lingering" }],
    rows: [],
  });
  // ------------------------------------------------------------------ start: Apr 21, 2025, 08:00
  renderMap();
  renderStrip();
  if (reducedMotion()) playBtn.textContent = "▶ Next hour";
  // the default frame loads at once (in the background); the map fades in when the section enters view
  go(st.day, st.hour);
  if (!reducedMotion()) {
    svg.style("opacity", 0);
    onEnterView(main, () => svg.transition().duration(600).style("opacity", 1), { offset: 0.95 });
    setTimeout(() => svg.style("opacity", 1), 4000); // safety: never leave the map hidden
  }
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { renderMap(); renderStrip(); }, 150); }).observe(mapWrap);
}
