// Closing · Two ways to be together (docs/SPEC.md, Closing): one dot per country, rows east (top) to west, x = 24
// hours. World time vs local time: only the time axis changes; each dot keeps its row.
import * as d3 from "d3";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { ms, reducedMotion, onEscape, liveRegion } from "../lib/a11y.js";
import { gnbu, neutral } from "../lib/colors.js";

const REF = ["NZ", "IN", "DE", "BR", "US", "MX"];
const hhmm = (h) => {
  const t = ((h % 24) + 24) % 24;
  const H = Math.floor(t + 1e-6), M = Math.round((t - H) * 60);
  return `${String(M === 60 ? H + 1 : H).padStart(2, "0")}:${String(M === 60 ? 0 : M).padStart(2, "0")}`;
};

export function mountClocks(root, data) {
  const G = gnbu();
  const N = neutral();
  const COLOR = { weather: G.teal, pope: G.blue, nye: G.deep };
  const rows = data.rows;
  const ri = new Map(rows.map((r, i) => [r.iso2, i]));
  const ev = data.events;
  const scrollyEl = document.getElementById("clk-scrolly");
  const after = document.getElementById("clk-after");
  const announce = liveRegion(root);

  root.innerHTML = `
    <div class="controls clk-controls">
      <span class="seg" role="group" aria-label="Clock"><button type="button" data-c="world" aria-pressed="true">World time</button><button type="button" data-c="local" aria-pressed="false">Local time</button></span>
      <label class="sr-only" for="clk-event">Event</label>
      <select id="clk-event" disabled><option value="weather">Weather</option><option value="pope">Pope Francis</option><option value="nye">New Year’s Eve</option></select>
      <label class="sr-only" for="clk-country">Pick your country</label>
      <select id="clk-country" disabled><option value="">Pick your country</option>${rows.slice().sort((a, b) => a.name.localeCompare(b.name)).map((r) => `<option value="${r.iso2}">${r.name}</option>`).join("")}</select>
    </div>
    <div class="clk-svg"></div>
    <p class="result clk-caption" aria-live="polite"></p>`;
  const wrap = root.querySelector(".clk-svg");
  const caption = root.querySelector(".clk-caption");
  const evSel = root.querySelector("#clk-event");
  const cSel = root.querySelector("#clk-country");
  const svg = d3.select(wrap).append("svg").attr("role", "img").attr("aria-roledescription", "dot plot")
    .attr("aria-label", `${data.takeaway} One dot per country, east at top, west at bottom. Space switches world and local time; arrow keys move country by country.`);
  svg.node().tabIndex = 0;
  const tip = createTooltip(root);
  // two panels (used side by side in step 3), otherwise one
  const panels = [svg.append("g"), svg.append("g")];
  const st = { step: -1, clock: "world", event: "weather", split: false, picked: null, focus: -1, touched: false };
  let W, H, rowH, M, phone, xs = [], panelW;

  function domainOf(e) { return ev[e].domain; }
  function wrapTo(v, d) { return ((v - d[0]) % 24 + 24) % 24 + d[0]; }

  function layout() {
    W = wrap.clientWidth || 720;
    phone = W < 560;
    // phones: the chart fits above the active step card (which starts at mid-screen)
    rowH = phone ? Math.max(2.4, Math.min(4, (window.innerHeight * 0.5 - 150) / rows.length))
      : Math.max(3.4, Math.min(5, (window.innerHeight * 0.66) / rows.length));
    M = { t: 28, b: 26, l: phone ? 8 : 104, r: 10 };
    H = M.t + rows.length * rowH + M.b;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
  }
  const yOf = (iso) => M.t + ri.get(iso) * rowH + rowH / 2;

  // draw one panel: dots for `event` on `clock`, plus faded background dots (weather) when asked
  function drawPanel(g, k, { event, clock, faded, dur }) {
    const x0 = st.split ? (k === 0 ? 0 : panelW + 16) : 0;
    const w = st.split ? panelW : W;
    const d = domainOf(event);
    const x = d3.scaleLinear(d, [x0 + M.l, x0 + w - M.r]);
    xs[k] = { x, event, clock };
    g.attr("display", null);
    // axis
    const ticks = d3.range(Math.ceil(d[0] / 6) * 6, d[1] + 0.01, 6).filter((t) => t > d[0] && t < d[1]);
    g.selectAll("g.ax").data([0]).join("g").attr("class", "ax").call((ax) => {
      ax.selectAll("line.tk").data(ticks).join("line").attr("class", "tk").attr("x1", x).attr("x2", x).attr("y1", M.t - 6).attr("y2", H - M.b)
        .attr("stroke", N.rule);
      ax.selectAll("text.tk").data(ticks).join("text").attr("class", "tk").attr("x", x).attr("y", H - M.b + 16).attr("text-anchor", "middle")
        .attr("font-size", 11).attr("fill", N.muted).text((t) => (event === "nye" && t === 0 ? "midnight" : hhmm(t)));
    });
    g.selectAll("text.ttl").data(st.split ? [0] : []).join("text").attr("class", "ttl").attr("x", x0 + M.l).attr("y", 12)
      .attr("font-size", 12).attr("font-weight", 700).attr("fill", N.ink)
      .text(`${ev[event].label}, ${clock === "world" ? "world clock" : "local clocks"}`);
    // background dots (faded weather)
    const bg = faded ? rows.filter((r) => ev.weather.values[r.iso2]) : [];
    g.selectAll("circle.bg").data(bg, (r) => r.iso2).join("circle").attr("class", "bg").attr("r", phone ? 1.6 : 2.2).attr("fill", COLOR.weather)
      .attr("opacity", 0.2).attr("cy", (r) => yOf(r.iso2))
      .attr("cx", (r) => x(wrapTo(ev.weather.values[r.iso2][clock], d)));
    // main dots
    const vals = ev[event].values;
    const sel = g.selectAll("circle.dot").data(rows.filter((r) => vals[r.iso2]), (r) => r.iso2);
    sel.exit().transition().duration(dur ? ms(300) : 0).attr("opacity", 0).remove();
    const en = sel.enter().append("circle").attr("class", "dot mark").attr("cy", (r) => yOf(r.iso2))
      .attr("cx", (r) => x(wrapTo(vals[r.iso2][clock], d))).attr("opacity", 0);
    en.merge(sel).attr("r", (r) => (st.picked === r.iso2 ? 4 : phone ? 2.2 : 2.8)).attr("fill", COLOR[event])
      .attr("stroke", (r) => (st.picked === r.iso2 || st.focus === ri.get(r.iso2) ? N.ink : "none")).attr("stroke-width", 1.5)
      .transition().duration(dur).ease(d3.easeCubicInOut)
      .attr("cy", (r) => yOf(r.iso2)).attr("cx", (r) => x(wrapTo(vals[r.iso2][clock], d))).attr("opacity", 1);
    // row labels (reference countries; Chile on step 1; the picked country)
    const lab = rows.filter((r) => (REF.includes(r.iso2) && (!phone || REF.includes(r.iso2))) || r.iso2 === st.picked || (st.step === 0 && !st.touched && r.iso2 === "CL"));
    g.selectAll("text.rl").data(k === 0 || st.split ? lab : [], (r) => r.iso2).join("text").attr("class", "rl halo")
      .attr("x", phone ? x0 + 4 : x0 + M.l - 6).attr("text-anchor", phone ? "start" : "end").attr("y", (r) => yOf(r.iso2) + 3)
      .attr("font-size", 10).attr("font-weight", (r) => (r.iso2 === st.picked || r.iso2 === "CL" ? 700 : 400)).attr("fill", N.ink)
      .text((r) => r.name);
    g.selectAll("text.ew").data(k === 0 || st.split ? ["east", "west"] : []).join("text").attr("class", "ew")
      .attr("x", phone ? x0 + W - 34 : x0 + M.l - 6).attr("text-anchor", "end").attr("y", (t) => (t === "east" ? M.t - 10 : H - M.b + 16))
      .attr("font-size", 10).attr("fill", N.faint).text((t) => t);
    // step 1: Chile marked (ring)
    const chile = st.step === 0 && !st.touched && vals.CL ? ["CL"] : [];
    g.selectAll("circle.ring").data(chile).join("circle").attr("class", "ring").attr("r", 6).attr("fill", "none")
      .attr("stroke", N.ink).attr("stroke-width", 1.5).attr("cy", (iso) => yOf(iso))
      .attr("cx", (iso) => x(wrapTo(vals[iso][clock], d)));
    // picked row highlight
    g.selectAll("rect.pk").data(st.picked && ri.has(st.picked) ? [st.picked] : []).join("rect").attr("class", "pk")
      .attr("x", x(d[0])).attr("width", x(d[1]) - x(d[0])).attr("y", (iso) => yOf(iso) - rowH / 2 - 1).attr("height", rowH + 2)
      .attr("fill", "none").attr("stroke", N.ink).attr("stroke-width", 1);
  }

  function draw(dur = ms(900)) {
    layout();
    panelW = (W - 16) / 2;
    if (st.split && !phone) {
      drawPanel(panels[0], 0, { event: "pope", clock: "world", faded: true, dur });
      drawPanel(panels[1], 1, { event: "pope", clock: "local", faded: true, dur });
    } else {
      st.split = st.split && !phone;
      const ePh = st.split || st.step === 2 && !st.touched ? "pope" : st.event;
      drawPanel(panels[0], 0, { event: ePh, clock: st.clock, faded: ePh !== "weather" && ePh === "pope" && !st.touched, dur });
      panels[1].attr("display", "none");
    }
    root.querySelectorAll("[data-c]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.c === st.clock)));
    captionText();
  }
  function captionText() {
    const e = st.split ? "pope" : st.event;
    const s = ev[e].stat;
    caption.textContent = e === "weather"
      ? (st.clock === "local" ? `On local clocks, ${s.local_within_1h} of ${s.n} countries search the weather within an hour of 6 a.m.` : "On the world’s clock, the weather peak moves west one time zone at a time.")
      : e === "pope"
        ? (st.split ? `World clock: ${s.world_within_1h} of ${s.n} countries within the same hour. Local clocks: from the middle of the night to the evening.`
          : st.clock === "world" ? `On the world’s clock, ${s.world_within_1h} of ${s.n} countries started searching within the same hour.` : "On local clocks, the same moment fell anywhere from the middle of the night to the evening.")
        : (st.clock === "local" ? `New Year’s Eve: ${s.local_within_1h} of the ${s.n} countries with a clear peak searched within an hour of their own midnight.` : `New Year’s Eve on the world’s clock: each country peaks at its own midnight, so the dots spread across the day.`);
  }

  // ------------------------------------------------------------------ steps
  function fadeRows() {
    if (reducedMotion()) return;
    panels[0].selectAll("circle.dot").attr("opacity", 0).transition().delay((r) => ri.get(r.iso2) * 15).duration(300).attr("opacity", 1);
  }
  let started = false;
  scrolly(scrollyEl, (i) => {
    if (st.touched) return;
    st.step = i;
    if (i === 0) { st.event = "weather"; st.clock = "world"; st.split = false; draw(started ? ms(900) : 0); if (!started) fadeRows(); }
    if (i === 1) { st.event = "weather"; st.clock = "local"; st.split = false; draw(ms(900)); }
    if (i === 2) {
      st.event = "pope";
      if (phone) { st.split = false; st.clock = "world"; draw(ms(600)); setTimeout(() => { if (st.step === 2 && !st.touched) { st.clock = "local"; draw(ms(900)); } }, reducedMotion() ? 0 : 1400); } else {
        // both panels start on the world clock, then the right one scatters to local clocks
        st.split = true;
        drawPanel(panels[0], 0, { event: "pope", clock: "world", faded: true, dur: ms(600) });
        drawPanel(panels[1], 1, { event: "pope", clock: "world", faded: true, dur: ms(600) });
        setTimeout(() => { if (st.split) draw(ms(900)); }, reducedMotion() ? 0 : 700);
        unlock();
      }
      unlock();
    }
    started = true;
  });
  function unlock() { evSel.disabled = false; cSel.disabled = false; }
  function touch() { if (!st.touched) { st.touched = true; st.split = false; if (st.step === 2) st.event = "pope"; evSel.value = st.event; } }

  // ------------------------------------------------------------------ controls
  root.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => {
    touch();
    st.clock = b.dataset.c;
    draw(ms(900));
    announce(caption.textContent);
  }));
  evSel.addEventListener("change", () => { const v = evSel.value; touch(); st.event = v; evSel.value = v; draw(ms(600)); announce(caption.textContent); });
  cSel.addEventListener("change", () => { st.picked = cSel.value || null; draw(ms(300)); });

  // ------------------------------------------------------------------ hover, tap, keyboard
  function nearest(ev_) {
    const [mx, my] = d3.pointer(ev_, svg.node());
    let best = null, bd = 14;
    svg.selectAll("circle.dot").each(function (r) {
      const cx = +this.getAttribute("cx"), cy = +this.getAttribute("cy");
      const dd = Math.hypot(cx - mx, cy - my);
      if (dd < bd) { bd = dd; best = { r, el: this, panel: this.parentNode === panels[1].node() ? 1 : 0 }; }
    });
    return best;
  }
  function html(r, panel) {
    const e = xs[panel] ? xs[panel].event : st.event;
    const v = ev[e].values[r.iso2];
    if (!v) return `<div class="tt-title">${r.name}</div><div class="tt-muted">No ${ev[e].label} data for this country.</div>`;
    const what = e === "weather" ? "usual weather search" : e === "pope" ? "first Pope Francis search" : "New Year’s Eve peak";
    const loc = e === "nye" ? hhmm(v.local) : hhmm(v.local);
    return `<div class="tt-title">${r.name}</div><div>${what}</div><div>World time ${hhmm(v.world)} · local ${loc}</div>` +
      (v.phrasing ? `<div class="tt-muted">Searched as “${v.phrasing}”</div>` : "");
  }
  svg.on("pointermove", (e) => { if (e.pointerType === "touch") return; const n = nearest(e); if (n) tip.show(html(n.r, n.panel), e); else tip.hide(); })
    .on("pointerleave", () => tip.hide())
    .on("click", (e) => { const n = nearest(e); if (n) { e.stopPropagation(); tip.show(html(n.r, n.panel), e, n.el); } });
  svg.node().addEventListener("keydown", (e) => {
    if (e.key === " ") { e.preventDefault(); touch(); st.clock = st.clock === "world" ? "local" : "world"; draw(ms(900)); announce(caption.textContent); return; }
    const s = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (e.key === "Escape") { tip.hide(true); st.focus = -1; draw(0); return; }
    if (!s) return;
    e.preventDefault();
    const evNow = st.split ? "pope" : st.event;
    const list = rows.filter((r) => ev[evNow].values[r.iso2]);
    let i = list.findIndex((r) => ri.get(r.iso2) === st.focus);
    i = Math.max(0, Math.min(list.length - 1, (i < 0 ? -1 : i) + s));
    st.focus = ri.get(list[i].iso2);
    draw(0);
    const el = svg.selectAll("circle.dot").filter((r) => r.iso2 === list[i].iso2).node();
    tip.show(html(list[i], 0), null, el);
  });
  svg.node().addEventListener("blur", () => { st.focus = -1; tip.hide(); });
  onEscape(() => tip.hide(true));

  // ------------------------------------------------------------------ data
  after.innerHTML = `<p class="source">One dot per country, east (top) to west by its UTC offset on April 21, 2025; the United States, Canada and Russia sit in one zone each. Weather: each country’s usual peak hour of “weather” searches. Pope Francis: its first trend on April 21, 2025. New Year’s Eve 2025/26: the 48 countries with a clear peak (two or more trends in the same 10 minutes). As of ${data.as_of}.</p>`;
  showTheData(after, {
    caption: "World and local times per country: weather peak, first Pope Francis search, New Year’s Eve peak",
    filename: "two-clocks",
    columns: [{ key: "name", label: "Country" }, { key: "offset", label: "UTC offset (h)", num: true },
      { key: "ww", label: "Weather, world" }, { key: "wl", label: "Weather, local" },
      { key: "pw", label: "Pope Francis, world" }, { key: "pl", label: "Pope Francis, local" },
      { key: "nw", label: "New Year's Eve, world" }, { key: "nl", label: "New Year's Eve, local" }],
    rows: rows.map((r) => {
      const w = ev.weather.values[r.iso2], p = ev.pope.values[r.iso2], n = ev.nye.values[r.iso2];
      return { ...r, ww: w ? hhmm(w.world) : "", wl: w ? hhmm(w.local) : "", pw: p ? hhmm(p.world) : "", pl: p ? hhmm(p.local) : "", nw: n ? hhmm(n.world) : "", nl: n ? hhmm(n.local) : "" };
    }),
  });

  draw(0);
  if (reducedMotion()) unlock();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => draw(0), 150); }).observe(wrap);
}
