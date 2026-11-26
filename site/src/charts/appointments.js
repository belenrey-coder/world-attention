// Chapter 3 · Appointments (docs/SPEC.md, Chapter 3): a calendar of every day (one square per day, rows Mon–Sun,
// columns by week), shaded by the number of scheduled events in 15+ countries or by the widest event's reach; four
// scroll steps change emphasis only; then a filter (football / any sport) and a measure toggle. Plus the
// guess-first comparison of a league match and the Oscars.
import * as d3 from "d3";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { keyNav, ms, reducedMotion, liveRegion, onEscape } from "../lib/a11y.js";
import { pubu, neutral, hatchPattern } from "../lib/colors.js";

const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WD_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const COUNT_BINS = [{ lo: 0, hi: 0, label: "0" }, { lo: 1, hi: 4, label: "1–4" }, { lo: 5, hi: 9, label: "5–9" },
  { lo: 10, hi: 19, label: "10–19" }, { lo: 20, hi: 29, label: "20–29" }, { lo: 30, hi: 1e9, label: "30+" }];
const REACH_BINS = [{ lo: 0, hi: 14, label: "none" }, { lo: 15, hi: 49, label: "15–49" }, { lo: 50, hi: 79, label: "50–79" },
  { lo: 80, hi: 99, label: "80–99" }, { lo: 100, hi: 114, label: "100–114" }, { lo: 115, hi: 125, label: "115–125" }];
const LABELLED = { "2026-03-15": "Oscars", "2025-01-20": "Inauguration", "2025-05-08": "Conclave" };
const FILTERS = { all: "Everything", no_football: "Without football", no_sport: "Without any sport" };

export function mountAppointments(root, data) {
  const P = pubu();
  const N = neutral();
  const SH = [P[0], P[2], P[3], P[4], P[5], P[6]];
  const days = data.days;
  const S = data.summary;
  const scrollyEl = document.getElementById("appt-scrolly");
  const after = document.getElementById("appt-after");
  const announce = liveRegion(root);

  root.innerHTML = `
    <p class="chart-title">The world keeps a weekend appointment</p>
    <p class="chart-sub ap-sub"></p>
    <div class="controls ap-controls">
      <span class="seg" role="group" aria-label="Filter">${Object.entries(FILTERS).map(([k, v]) => `<button type="button" data-f="${k}" aria-pressed="${k === "all"}" disabled>${v}</button>`).join("")}</span>
      <span class="seg" role="group" aria-label="Measure"><button type="button" data-m="count" aria-pressed="true" disabled>Number of events</button><button type="button" data-m="reach" aria-pressed="false" disabled>Widest reach</button></span>
    </div>
    <div class="legend ap-legend" aria-hidden="true"></div>
    <div class="ap-cal"></div>
    <p class="result ap-sentence" aria-live="polite"></p>`;
  const cal = root.querySelector(".ap-cal");
  const sub = root.querySelector(".ap-sub");
  const legend = root.querySelector(".ap-legend");
  const sentence = root.querySelector(".ap-sentence");
  const tip = createTooltip(root);

  const st = { step: -1, filter: "all", measure: "count", unlocked: false, touched: false, hover: null, filled: false };
  const evKey = { all: "events", no_football: "events_no_football", no_sport: "events_no_sport" };
  const wKey = { all: "widest", no_football: "widest_no_football", no_sport: "widest_no_sport" };
  const value = (d) => (st.measure === "count" ? d[evKey[st.filter]] : (d[wKey[st.filter]] || { reach: 0 }).reach);
  const binOf = (v) => (st.measure === "count" ? COUNT_BINS : REACH_BINS).findIndex((b) => v >= b.lo && v <= b.hi);

  // ------------------------------------------------------------------ layout (desktop: weeks as columns; phones:
  // three panels of weeks as rows, Mon–Sun as columns)
  const t0 = d3.utcMonday.floor(new Date(days[0].date));
  const weekOf = (d) => d3.utcMonday.count(t0, new Date(d.date));
  const nWeeks = weekOf(days[days.length - 1]) + 1;
  const svg = d3.select(cal).append("svg").attr("role", "img").attr("aria-roledescription", "calendar")
    .attr("aria-label", `${data.takeaway} Calendar of ${days.length} days, one square per day; arrow keys move day by day.`);
  const hatch = hatchPattern(svg);
  const gCells = svg.append("g");
  const gAxis = svg.append("g");
  const gNotes = svg.append("g");
  let cells, W, phone, pos;

  function render() {
    W = cal.clientWidth || 720;
    phone = W < 560;
    let H;
    if (!phone) {
      const left = 30, right = 56;
      const c = Math.min(16, Math.floor((W - left - right) / nWeeks));
      const g = c >= 9 ? 2 : 1;
      const top = 16;
      pos = (d) => ({ x: left + weekOf(d) * c, y: top + d.weekday * c, s: c - g });
      H = top + 7 * c + 34;
      gAxis.selectAll("*").remove();
      WD.forEach((w, i) => { if (i % 2 === 0) gAxis.append("text").attr("x", left - 6).attr("y", top + i * c + c * 0.7).attr("text-anchor", "end").attr("font-size", 10).attr("fill", N.muted).text(w); });
      // months under the grid
      d3.utcMonths(new Date(days[0].date), new Date(days[days.length - 1].date)).forEach((m) => {
        const x = left + d3.utcMonday.count(t0, d3.utcMonday.ceil(m)) * c;
        gAxis.append("text").attr("x", x).attr("y", top + 7 * c + 13).attr("font-size", 10).attr("fill", N.muted)
          .text(d3.utcFormat("%b")(m));
        if (m.getUTCMonth() === 0) gAxis.append("text").attr("x", x).attr("y", top + 7 * c + 26).attr("font-size", 10).attr("font-weight", 700).attr("fill", N.ink).text(m.getUTCFullYear());
      });
      gAxis.append("g").attr("class", "wdavg");
      svg.node().__rowX = left + nWeeks * c + 6;
      svg.node().__rowY = (i) => top + i * c + c * 0.7;
    } else {
      const panels = 3;
      const per = Math.ceil(nWeeks / panels);
      const pw = (W - 8 * (panels - 1)) / panels;
      const c = Math.floor((pw - 34) / 7);
      pos = (d) => {
        const w = weekOf(d);
        const p = Math.floor(w / per);
        return { x: p * (pw + 8) + 34 + d.weekday * c, y: 16 + (w % per) * c, s: c - 1 };
      };
      H = 16 + per * c + 8;
      gAxis.selectAll("*").remove();
      for (let p = 0; p < panels; p++) {
        ["M", "T", "W", "T", "F", "S", "S"].forEach((w, i) => gAxis.append("text").attr("x", p * (pw + 8) + 34 + i * c + c / 2)
          .attr("y", 11).attr("text-anchor", "middle").attr("font-size", 9).attr("fill", N.muted).text(w));
      }
      d3.utcMonths(new Date(days[0].date), new Date(days[days.length - 1].date)).forEach((m) => {
        const w = d3.utcMonday.count(t0, d3.utcMonday.ceil(m));
        const p = Math.floor(w / per);
        gAxis.append("text").attr("x", p * (pw + 8) + 31).attr("y", 16 + (w % per) * c + c * 0.75).attr("text-anchor", "end")
          .attr("font-size", 9).attr("fill", N.muted).text(d3.utcFormat(m.getUTCMonth() === 0 ? "%b ’%y" : "%b")(m));
      });
    }
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    cells = gCells.selectAll("rect.day").data(days, (d) => d.date).join("rect")
      .attr("class", "day mark").attr("id", (d) => `ap-${d.date}`)
      .each(function (d) { const p = pos(d); d3.select(this).attr("x", p.x).attr("y", p.y).attr("width", p.s).attr("height", p.s); })
      .attr("rx", 1).style("cursor", "pointer");
    bindCells();
    paint(0);
  }

  // ------------------------------------------------------------------ painting
  function fillOf(d) {
    if (d.gap) return hatch;
    return SH[Math.max(0, binOf(value(d)))];
  }
  function outlineOf(d) {
    if (st.hover && st.hover.date === d.date) return N.ink;
    if (st.step === 2 && !st.touched) return (d.widest && d.widest.reach >= 100) ? N.ink : null;
    if (st.step === 3 && !st.touched) return d.events_no_sport > 0 ? N.ink : null;
    return null;
  }
  function opacityOf(d) {
    if (st.step < 0 && !st.filled) return 0;
    if (st.step === 1 && !st.touched) return d.weekday >= 5 ? 1 : 0.4;
    return 1;
  }
  function paint(dur = ms(300)) {
    cells.interrupt("paint").transition("paint").duration(dur)
      .attr("fill", fillOf).attr("opacity", opacityOf);
    cells.attr("stroke", (d) => outlineOf(d) || "none").attr("stroke-width", (d) => (outlineOf(d) ? (st.hover && st.hover.date === d.date ? 2 : 1) : 0));
    // gap squares get a thin border so the hatch reads as a square
    cells.filter((d) => d.gap && !outlineOf(d)).attr("stroke", N.hatch).attr("stroke-width", 0.5);
    drawLegend();
    drawNotes();
    drawSentence();
  }
  function drawLegend() {
    const bins = st.measure === "count" ? COUNT_BINS : REACH_BINS;
    legend.innerHTML = `<span>${st.measure === "count" ? "Scheduled events that day:" : "Widest event that day, countries:"}</span>` +
      bins.map((b, i) => `<span><i class="swatch" style="background:${SH[i]}"></i>${b.label}</span>`).join("") +
      `<span><i class="swatch hatched" style="border:1px solid ${N.hatch}"></i>gap in the data</span>`;
    sub.textContent = st.measure === "count"
      ? "Each square is one day; the darker, the more scheduled events trended in 15 or more countries that day."
      : "Each square is one day; the darker, the more countries the day's widest scheduled event reached.";
  }
  function drawNotes() {
    gNotes.selectAll("*").remove();
    // weekday averages at the end of each row (desktop, step 2 and later)
    if (!phone && st.step >= 1) {
      const rx = svg.node().__rowX, ry = svg.node().__rowY;
      const avg = st.measure === "count" ? S.mean_events_by_weekday : S.mean_widest_reach_by_weekday;
      const showAvg = st.filter === "all";
      if (showAvg) WD.forEach((w, i) => gNotes.append("text").attr("x", rx).attr("y", ry(i)).attr("font-size", 10)
        .attr("font-weight", i >= 5 ? 700 : 400).attr("fill", N.ink).text(Math.round(avg[i])));
      if (showAvg) gNotes.append("text").attr("x", rx).attr("y", ry(0) - 13).attr("font-size", 9).attr("fill", N.muted).text("per day, avg");
    }
    if (st.step >= 3 || st.unlocked) {
      days.filter((d) => LABELLED[d.date]).forEach((d) => {
        const p = pos(d);
        gNotes.append("line").attr("x1", p.x + p.s / 2).attr("x2", p.x + p.s / 2).attr("y1", p.y).attr("y2", p.y - 4).attr("stroke", N.ink);
        gNotes.append("text").attr("class", "halo").attr("x", p.x + p.s / 2).attr("y", p.y - 6).attr("text-anchor", "middle")
          .attr("font-size", 10).attr("font-weight", 700).attr("fill", N.ink).text(LABELLED[d.date]);
      });
    }
  }
  function drawSentence() {
    if (!st.touched) {
      sentence.textContent = st.step === 2 ? "Outlined: days whose widest scheduled event reached 100 countries or more."
        : st.step === 3 ? `Outlined: the ${S.days_with_event.no_sport} days with a scheduled event outside sport in 15 or more countries.` : "";
      return;
    }
    const n = S.days_with_event[st.filter];
    const med = S.median_events[st.filter] || "none";
    const lead = { all: "With everything", no_football: "Without football", no_sport: "Without any sport" }[st.filter];
    sentence.textContent = `${lead}: ${n} of ${S.full_days} days had a scheduled event in 15 or more countries; a typical day had ${med}.`;
  }

  // ------------------------------------------------------------------ hover, tap, keyboard
  const fmt = d3.utcFormat("%B %-d, %Y");
  function html(d) {
    const head = `<div class="tt-title">${WD_LONG[d.weekday]}, ${fmt(new Date(d.date))}</div>`;
    if (d.gap) return `${head}<div class="tt-muted">Google's collection had a gap this day, so counts are lower.</div>${d.events ? `<div>${d.events} events</div>` : ""}`;
    const n = d[evKey[st.filter]];
    const w = d[wKey[st.filter]];
    const lab = { all: "scheduled events", no_football: "scheduled events without football", no_sport: "scheduled events outside sport" }[st.filter];
    return `${head}<div>${n} ${lab} in 15+ countries</div>` +
      (w ? `<div>Widest: <b>${w.event}</b>, ${w.reach} countries</div>` : "") +
      (st.filter === "all" && d.searches && d.searches.length ? `<div class="tt-muted">Searched as ${d.searches.map((q) => `“${q}”`).join(", ")}</div>` : "");
  }
  function setHover(d, ev, el) {
    st.hover = d;
    paint(0);
    if (d) tip.show(html(d), ev, el); else tip.hide();
  }
  function bindCells() {
    cells.on("pointerenter", (ev, d) => { if (ev.pointerType !== "touch") setHover(d, ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType !== "touch" && !tip.pinned) setHover(null); })
      .on("click", (ev, d) => { ev.stopPropagation(); setHover(d, ev, ev.currentTarget); });
  }
  keyNav(svg.node(), {
    items: () => days.map((d) => ({ d, el: document.getElementById(`ap-${d.date}`) })),
    onFocus: ({ d, el }) => setHover(d, null, el),
    onEnter: ({ d, el }) => tip.pin(html(d), el),
    onEscape: () => { tip.hide(true); setHover(null); },
    onBlur: () => { if (!tip.pinned) setHover(null); },
  });
  onEscape(() => { if (st.hover) setHover(null); });

  // ------------------------------------------------------------------ controls (unlock after step 4)
  const btns = root.querySelectorAll(".ap-controls button");
  function unlock() {
    if (st.unlocked) return;
    st.unlocked = true;
    btns.forEach((b) => { b.disabled = false; });
    paint();
  }
  root.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => {
    st.touched = true;
    st.filter = b.dataset.f;
    root.querySelectorAll("[data-f]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    paint(ms(600));
    announce(sentence.textContent);
  }));
  root.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => {
    st.touched = true;
    st.measure = b.dataset.m;
    root.querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    paint(ms(600));
  }));
  function setMeasure(m) {
    st.measure = m;
    root.querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.m === m)));
  }

  // ------------------------------------------------------------------ steps
  function fillIn() {
    st.filled = true;
    if (reducedMotion()) { paint(0); return; }
    cells.attr("opacity", 0).interrupt("paint").transition("paint").delay((d) => (weekOf(d) / nWeeks) * 1200).duration(200)
      .attr("fill", fillOf).attr("opacity", opacityOf);
  }
  scrolly(scrollyEl, (i, dir, { animate }) => {
    if (i < 0 && !st.filled) return; // before the first step: the calendar is still empty
    st.step = Math.max(0, i);
    if (!st.touched) setMeasure(st.step >= 2 ? "reach" : "count");
    if (i === 3) unlock(); // the last step, or past it
    if (!st.filled) {
      if (animate && i === 0) { fillIn(); drawNotes(); drawLegend(); drawSentence(); return; }
      st.filled = true;
    }
    paint(animate ? ms(i === 2 ? 600 : 300) : 0);
  });

  // ------------------------------------------------------------------ after: caveat + data
  after.innerHTML = `
    <div class="caveat">
      <p><b>A caveat.</b> Google's Trending Now is built to catch sudden jumps. A football match is a new search every time two teams meet, the kind of jump the system is designed to see, while an award show or an election builds over days. So this data may make football look even more dominant than it is; the widest-reach view is the fairer measure.</p>
      <button type="button" class="linkish ap-how" aria-expanded="false">▸ How we measured this</button>
      <div class="ap-how-body" hidden><p>Days are UTC. Hatched days had gaps in Google's collection, so their counts are lower; the sentences count only the ${S.full_days} days with full coverage. A scheduled event is a global moment (15 or more countries within an hour of the third) that was planned in advance; each event counts once, on the day of its scheduled start. An event's reach counts every country where any topic about it trended in its window.</p></div>
    </div>`;
  const how = after.querySelector(".ap-how");
  how.addEventListener("click", () => {
    const body = after.querySelector(".ap-how-body");
    body.hidden = !body.hidden;
    how.setAttribute("aria-expanded", String(!body.hidden));
    how.textContent = `${body.hidden ? "▸" : "▾"} How we measured this`;
  });
  showTheData(after, {
    methodology: "appointments",
    caption: `Scheduled events in 15 or more countries, per UTC day (${days.length} days; gap days flagged)`,
    filename: "scheduled-events-per-day",
    columns: [
      { key: "date", label: "Date" },
      { key: "weekday", label: "Weekday", format: (v) => WD[v] },
      { key: "events", label: "Events", num: true },
      { key: "events_no_football", label: "Without football", num: true },
      { key: "events_no_sport", label: "Without any sport", num: true },
      { key: "widest", label: "Widest event", format: (v) => (v ? v.event : "") },
      { key: "widest", label: "Its reach", num: true, format: (v) => (v ? v.reach : ""), sortValue: (r) => (r.widest ? r.widest.reach : -1) },
      { key: "gap", label: "Gap day", format: (v) => (v ? "yes" : "") },
    ],
    rows: days,
  });
  after.insertAdjacentHTML("beforeend", `<p class="source">Source: GoogleTrendArchive, national Trending Now feeds. Days in UTC. As of ${data.as_of}.</p>`);

  render();
  if (reducedMotion()) { st.filled = true; paint(0); }
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(cal);
}

// ==================================================================== guess first: a league match vs the Oscars
export function mountCompare(root, data) {
  const P = pubu();
  const N = neutral();
  const anchor = data.anchor, q = data.question;
  const all = data.groups;
  let guess = null;

  root.innerHTML = `
    <p class="ap-q">${anchor.event}, a league match on a Sunday in February, trended in ${anchor.reach} countries. <b>How many searched the ${q.event.replace(/ \d{4}$/, "")}?</b> Drag the bar, or use the arrow keys, to guess.</p>
    <div class="cmp-svg"></div>
    <div class="controls"><button type="button" class="cmp-reveal">Reveal</button><button type="button" class="linkish cmp-skip">Skip</button></div>
    <p class="result cmp-text" aria-live="polite"></p>
    <div class="cmp-data"></div>
    <p class="source">Event reach: countries where any topic about the event trended in its window. League matches identified from their searches (a lower bound). Non-sport events: catalogue and hand-verified events only; single-topic units (such as “Samsung” or “BTS”) left out. As of ${data.as_of}.</p>`;
  const wrap = root.querySelector(".cmp-svg");
  const svg = d3.select(wrap).append("svg").attr("role", "img");
  let W, x, revealed = false;

  function drawGuess() {
    W = wrap.clientWidth || 640;
    const L = Math.min(190, W * 0.38);
    x = d3.scaleLinear([0, 125], [L, W - 46]);
    const H = 92;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H)
      .attr("aria-label", `${anchor.event}: ${anchor.reach} countries. Your guess for the ${q.event}: ${guess == null ? "not set" : guess}.`);
    svg.selectAll("*").remove();
    svg.append("g").attr("transform", "translate(0,14)").call(d3.axisTop(x).tickValues([0, 25, 50, 75, 100, 125]).tickSize(0))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll("text").attr("fill", N.faint).attr("font-size", 10));
    const row = (y, label, v, color, bold) => {
      svg.append("text").attr("x", L - 8).attr("y", y + 11).attr("text-anchor", "end").attr("font-size", 12)
        .attr("font-weight", bold ? 700 : 400).attr("fill", N.ink).text(label);
      svg.append("rect").attr("x", x(0)).attr("y", y).attr("width", x(125) - x(0)).attr("height", 14).attr("fill", N.gap);
      if (v != null) {
        svg.append("rect").attr("x", x(0)).attr("y", y).attr("width", x(v) - x(0)).attr("height", 14).attr("fill", color);
        svg.append("text").attr("x", x(v) + 6).attr("y", y + 11).attr("font-size", 12).attr("font-weight", 700).attr("fill", N.ink).text(v);
      }
    };
    row(24, anchor.event, anchor.reach, P[6], true);
    row(50, q.event, guess, P[3], true);
    // drag handle
    const hx = x(guess == null ? 60 : guess);
    const handle = svg.append("circle").attr("class", "cmp-handle").attr("cx", hx).attr("cy", 57).attr("r", 9)
      .attr("fill", N.ink).attr("stroke", N.paper).attr("stroke-width", 2).style("cursor", "ew-resize")
      .attr("tabindex", 0).attr("role", "slider").attr("aria-label", `Your guess for the ${q.event}, in countries`)
      .attr("aria-valuemin", 0).attr("aria-valuemax", 125).attr("aria-valuenow", guess ?? 60);
    svg.append("text").attr("x", x(0)).attr("y", 86).attr("font-size", 11).attr("fill", N.muted)
      .text(guess == null ? "drag the dot to guess →" : `your guess: ${guess}`);
    const setG = (v) => { guess = Math.max(0, Math.min(125, Math.round(v))); drawGuess(); svg.select(".cmp-handle").node().focus(); };
    svg.call(d3.drag().on("start drag", (ev) => { if (!revealed) { guess = Math.max(0, Math.min(125, Math.round(x.invert(ev.x)))); drawGuess(); } }));
    handle.on("keydown", (ev) => {
      if (revealed) return;
      const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[ev.key];
      if (step) { ev.preventDefault(); setG((guess ?? 60) + step); }
    });
  }

  function reveal(skip) {
    if (revealed) return;
    revealed = true;
    if (skip) guess = null;
    root.querySelector(".cmp-reveal").disabled = true;
    root.querySelector(".cmp-skip").disabled = true;
    drawBars();
    const outsideSport = all[2].items.filter((e) => e.reach >= 100).map((e) => `the ${e.event.replace(/ \(.*\)/, "").toLowerCase().replace("grammys", "Grammys")} (${e.reach})`);
    root.querySelector(".cmp-text").textContent =
      `The ${q.event.replace(/ \d{4}$/, "")} reached ${q.reach}.${guess != null ? ` You guessed ${guess}.` : ""} Outside sport, only ${outsideSport.join(" and ")} passed 100. And not every match is huge: a typical one reached ${data.typical_match} countries.`;
  }

  function drawBars() {
    W = wrap.clientWidth || 640;
    const L = Math.min(190, W * 0.38);
    x = d3.scaleLinear([0, 125], [L, W - 46]);
    const rowH = 18;
    let y = 26;
    const rows = [];
    all.forEach((g) => {
      rows.push({ head: g.label, y });
      y += 20;
      g.items.forEach((e) => { rows.push({ e, y }); y += rowH; });
      y += 10;
    });
    const H = y + 10;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H)
      .attr("aria-label", `A regular Spanish league match reached more countries than the Oscars: ${anchor.event} ${anchor.reach}, ${q.event} ${q.reach}. Typical match: ${data.typical_match}.`);
    svg.selectAll("*").remove();
    svg.append("g").attr("transform", "translate(0,14)").call(d3.axisTop(x).tickValues([0, 25, 50, 75, 100, 125]).tickSize(0))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll("text").attr("fill", N.faint).attr("font-size", 10));
    rows.forEach((r) => {
      if (r.head) {
        svg.append("text").attr("x", x(0)).attr("y", r.y + 12).attr("font-size", 11).attr("font-weight", 700).attr("fill", N.ink).text(r.head);
        return;
      }
      const hl = r.e.event === anchor.event && r.e.date === anchor.date || r.e.event === q.event;
      svg.append("text").attr("x", L - 8).attr("y", r.y + 11).attr("text-anchor", "end").attr("font-size", 11)
        .attr("font-weight", hl ? 700 : 400).attr("fill", N.ink).text(r.e.event);
      svg.append("rect").attr("x", x(0)).attr("y", r.y + 2).attr("height", 12).attr("fill", hl ? P[6] : P[3])
        .attr("width", 0).transition().duration(ms(600)).ease(d3.easeCubicInOut).attr("width", x(r.e.reach) - x(0));
      svg.append("text").attr("x", x(r.e.reach) + 5).attr("y", r.y + 12).attr("font-size", 11).attr("font-weight", hl ? 700 : 400)
        .attr("fill", N.ink).text(r.e.reach);
    });
    // typical match (dashed) and the reader's guess
    svg.append("line").attr("x1", x(data.typical_match)).attr("x2", x(data.typical_match)).attr("y1", 20).attr("y2", H - 6)
      .attr("stroke", N.muted).attr("stroke-dasharray", "3 3");
    svg.append("text").attr("class", "halo").attr("x", x(data.typical_match) + 4).attr("y", H - 8).attr("font-size", 10).attr("fill", N.muted).text(`a typical match: ${data.typical_match}`);
    if (guess != null) {
      const qr = rows.find((r) => r.e && r.e.event === q.event);
      svg.append("line").attr("x1", x(guess)).attr("x2", x(guess)).attr("y1", qr.y - 2).attr("y2", qr.y + 18).attr("stroke", N.ink).attr("stroke-width", 2);
      svg.append("text").attr("class", "halo").attr("x", x(guess) + 4).attr("y", qr.y - 3).attr("font-size", 10).attr("fill", N.ink).text(`your guess: ${guess}`);
    }
  }

  root.querySelector(".cmp-reveal").addEventListener("click", () => reveal(false));
  root.querySelector(".cmp-skip").addEventListener("click", () => reveal(true));
  showTheData(root.querySelector(".cmp-data"), {
    methodology: "compare",
    caption: "Event reach of the widest league matches, other sport and non-sport scheduled events",
    filename: "league-match-vs-oscars",
    columns: [{ key: "group", label: "Group" }, { key: "event", label: "Event" }, { key: "date", label: "Date" },
      { key: "reach", label: "Countries", num: true }],
    rows: all.flatMap((g) => g.items.map((e) => ({ group: g.label, ...e }))),
  });
  drawGuess();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => (revealed ? drawBars() : drawGuess()), 150); }).observe(wrap);
}
