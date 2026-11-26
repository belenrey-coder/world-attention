// Chapter 4 · Waves (docs/SPEC.md, Chapter 4): Iran day by day, two returns on one clock, and an 18-row ridgeline of
// the stories the world kept returning to (scroll steps light one group at a time; then hover, open, filter).
import * as d3 from "d3";
import { scrolly, onEnterView } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData } from "../lib/table.js";
import { keyNav, ms, reducedMotion, onEscape, liveRegion } from "../lib/a11y.js";
import { pubu, gnbu, neutral, hatchPattern } from "../lib/colors.js";

const fmtDay = d3.utcFormat("%a, %B %-d, %Y");
const fmtMonth = d3.utcFormat("%B %Y");
const shortMonth = d3.utcFormat("%b");

// ==================================================================== Iran, day by day
export function mountIran(root, data) {
  const P = pubu();
  const N = neutral();
  const days = data.days.map((d) => ({ ...d, t: new Date(d.date) }));
  root.innerHTML = `
    <p class="chart-title">Iran kept coming back</p>
    <p class="chart-sub">Countries where any search about Iran trended, each day. Hover or tap a day to see what people searched; hatched days had gaps in the data.</p>
    <div class="ir-svg"></div>
    <p class="source">Iran and Iran–Israel war topics merged. Days in UTC. As of ${data.as_of}.</p>`;
  const wrap = root.querySelector(".ir-svg");
  const svg = d3.select(wrap).append("svg").attr("role", "img")
    .attr("aria-label", `${data.takeaway} Area chart of countries per day, November 2024 to May 2026; arrow keys move day by day.`);
  const hatch = hatchPattern(svg);
  const tip = createTooltip(root);
  let x, y, W, H, M, focusI = -1;
  const gGap = svg.append("g"), gArea = svg.append("g"), gAxis = svg.append("g"), gNote = svg.append("g");
  const cursor = svg.append("line").attr("stroke", N.ink).attr("stroke-width", 1).attr("opacity", 0);
  const overlay = svg.append("rect").attr("fill", "transparent").style("cursor", "crosshair");
  const clipId = `ir-clip-${Math.random().toString(36).slice(2, 7)}`;
  const clip = svg.append("defs").append("clipPath").attr("id", clipId).append("rect");

  function render() {
    W = wrap.clientWidth || 1100;
    H = W < 560 ? 220 : 280;
    M = { t: 24, r: 10, b: 28, l: 32 };
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    x = d3.scaleUtc([days[0].t, d3.utcDay.offset(days[days.length - 1].t, 1)], [M.l, W - M.r]);
    y = d3.scaleLinear([0, 125], [H - M.b, M.t]);
    const dw = x(d3.utcDay.offset(days[0].t, 1)) - x(days[0].t);
    gGap.selectAll("rect").data(days.filter((d) => d.gap)).join("rect")
      .attr("x", (d) => x(d.t)).attr("width", Math.max(1, dw)).attr("y", M.t).attr("height", H - M.t - M.b).attr("fill", hatch);
    gAxis.selectAll("*").remove();
    gAxis.append("g").attr("transform", `translate(0,${H - M.b})`)
      .call(d3.axisBottom(x).ticks(W < 560 ? d3.utcMonth.every(3) : d3.utcMonth.every(2)).tickFormat((d) => (d.getUTCMonth() === 0 ? d3.utcFormat("%b %Y")(d) : shortMonth(d))).tickSize(0).tickPadding(8))
      .call((g) => g.select(".domain").attr("stroke", N.rule)).call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    gAxis.append("g").attr("transform", `translate(${M.l},0)`)
      .call(d3.axisLeft(y).tickValues([0, 25, 50, 75, 100, 125]).tickSize(-(W - M.l - M.r)).tickPadding(6))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll(".tick line").attr("stroke", N.rule).attr("opacity", 0.7))
      .call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    const area = d3.area().curve(d3.curveStepAfter).x((d) => x(d.t)).y0(y(0)).y1((d) => y(d.countries));
    clip.attr("x", 0).attr("y", 0).attr("height", H).attr("width", W);
    gArea.attr("clip-path", `url(#${clipId})`).selectAll("path").data([days]).join("path")
      .attr("d", area).attr("fill", P[4]).attr("stroke", P[6]).attr("stroke-width", 0.75);
    // notes: the biggest days, and the January 2026 gap
    gNote.selectAll("*").remove();
    const jan = days.find((d) => d.date === "2026-01-15");
    gNote.append("text").attr("class", "halo").attr("x", x(jan.t)).attr("y", M.t + 12).attr("text-anchor", "middle").attr("font-size", 11)
      .attr("fill", N.muted).text(W < 560 ? "Jan 2026: 5 days of data" : "January 2026 had only 5 days of data");
    const peaks = [["2025-06-13", "Israel–Iran war"], ["2026-02-28", "the war escalates"]];
    peaks.forEach(([dt, lab]) => {
      const d = days.find((z) => z.date === dt);
      if (!d) return;
      gNote.append("text").attr("class", "halo").attr("x", x(d.t) + 4).attr("y", y(d.countries) - 4).attr("font-size", 11)
        .attr("font-weight", 700).attr("fill", N.ink).text(`${lab} · ${d.countries}`);
    });
    overlay.attr("x", M.l).attr("y", M.t).attr("width", W - M.l - M.r).attr("height", H - M.t - M.b);
  }
  const html = (d) => `<div class="tt-title">${fmtDay(d.t)}</div>` +
    (d.gap ? `<div class="tt-muted">Collection gap: the count is a lower bound.</div>` : "") +
    `<div>${d.countries} ${d.countries === 1 ? "country" : "countries"}</div>` +
    (d.searches.length ? `<div class="tt-muted">Searched as ${d.searches.map((q) => `“${q}”`).join(", ")}</div>` : "");
  function at(i, ev, el) {
    focusI = i;
    const d = days[i];
    cursor.attr("x1", x(d.t)).attr("x2", x(d.t)).attr("y1", M.t).attr("y2", H - M.b).attr("opacity", 1);
    tip.show(html(d), ev, el || cursor.node());
  }
  const idxAt = (ev) => Math.max(0, Math.min(days.length - 1, d3.bisectLeft(days.map((d) => d.t), x.invert(d3.pointer(ev, svg.node())[0])) - 1));
  overlay.on("pointermove", (ev) => at(idxAt(ev), ev)).on("pointerleave", () => { cursor.attr("opacity", 0); tip.hide(); })
    .on("click", (ev) => { ev.stopPropagation(); at(idxAt(ev), ev, cursor.node()); });
  keyNav(svg.node(), {
    items: () => days.map((d) => ({ d, el: null })),
    onFocus: (it, i) => at(i, null, cursor.node()),
    onEnter: (it, i) => tip.pin(html(days[i]), cursor.node()),
    onEscape: () => { tip.hide(true); cursor.attr("opacity", 0); },
    onBlur: () => { if (!tip.pinned) { tip.hide(); cursor.attr("opacity", 0); } },
  });
  showTheData(root, {
    caption: "Countries where Iran trended, per UTC day", filename: "iran-per-day",
    columns: [{ key: "date", label: "Date" }, { key: "countries", label: "Countries", num: true },
      { key: "gap", label: "Gap day", format: (v) => (v ? "yes" : "") }, { key: "searches", label: "Top searches", format: (v) => v.join("; ") }],
    rows: days,
  });
  render();
  // draws left to right when it enters view
  if (!reducedMotion()) {
    clip.attr("width", 0);
    onEnterView(wrap, () => clip.transition().duration(1200).ease(d3.easeCubicInOut).attr("width", W));
  }
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(wrap);
}

// ==================================================================== two returns on one clock
export function mountSpeed(root, data) {
  const G = gnbu();
  const N = neutral();
  const COLOR = { Iran: G.deep, Syria: G.teal };
  const LABEL = { Syria: "spread over half a day", Iran: "50 countries within the hour" };
  const R = data.returns;
  root.innerHTML = `
    <p class="chart-title">Searches move at the speed of the news</p>
    <p class="chart-sub">Two returns on the same clock. When Damascus fell after a days-long advance, searches spread over half a day. When the United States struck Iran, 50 countries were searching within the hour.</p>
    <div class="sp-svg"></div>
    <p class="source">Countries already searching in the 24 hours before are left out (Syria: ${R.find((r) => r.key === "Syria").already_trending}; Iran on June 22: ${R.find((r) => r.key === "Iran").already_trending}). Each line counts all the story's topics, timed from the third new country. As of ${data.as_of}.</p>`;
  const wrap = root.querySelector(".sp-svg");
  const svg = d3.select(wrap).append("svg").attr("role", "img").attr("aria-label", `${data.takeaway} Line chart of new countries over 24 hours; arrow keys move through the hours.`);
  const tip = createTooltip(root);
  const gAxis = svg.append("g"), gL = svg.append("g").attr("fill", "none"), gLab = svg.append("g");
  const cursor = svg.append("line").attr("stroke", N.ink).attr("opacity", 0);
  const overlay = svg.append("rect").attr("fill", "transparent");
  let x, y, W, H, M;
  const mins = R[0].curve.map((c) => c[0]);
  const val = (r, m) => { let v = 0; for (const [mm, c] of r.curve) { if (mm <= m) v = c; } return v; };
  function render() {
    W = wrap.clientWidth || 640;
    H = 300;
    M = { t: 20, r: W < 560 ? 10 : 172, b: 30, l: 32 };
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    x = d3.scaleLinear([0, 24], [M.l, W - M.r]);
    y = d3.scaleLinear([0, 80], [H - M.b, M.t]);
    gAxis.selectAll("*").remove();
    gAxis.append("g").attr("transform", `translate(0,${H - M.b})`)
      .call(d3.axisBottom(x).tickValues([0, 6, 12, 18, 24]).tickFormat((d) => (d === 0 ? "start" : `${d} hours`)).tickSize(0).tickPadding(8))
      .call((g) => g.select(".domain").attr("stroke", N.rule)).call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    gAxis.append("g").attr("transform", `translate(${M.l},0)`)
      .call(d3.axisLeft(y).tickValues([0, 20, 40, 60, 80]).tickSize(-(W - M.l - M.r)).tickPadding(6))
      .call((g) => g.select(".domain").remove()).call((g) => g.selectAll(".tick line").attr("stroke", N.rule))
      .call((g) => g.selectAll("text").attr("fill", N.muted).attr("font-size", 11));
    gAxis.append("text").attr("class", "halo").attr("x", M.l + 4).attr("y", M.t - 6).attr("font-size", 12).attr("fill", N.ink).text("new countries searching");
    const line = d3.line().curve(d3.curveStepAfter).x((c) => x(c[0] / 60)).y((c) => y(c[1]));
    gL.selectAll("path").data(R, (r) => r.key).join("path").attr("d", (r) => line(r.curve))
      .attr("stroke", (r) => COLOR[r.key]).attr("stroke-width", 3).attr("stroke-linejoin", "round");
    const labs = R.map((r) => ({ r, y: y(r.curve[r.curve.length - 1][1]) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labs.length; i++) labs[i].y = Math.max(labs[i].y, labs[i - 1].y + 34);
    gLab.selectAll("g").data(labs, (d) => d.r.key).join((en) => { const g = en.append("g"); g.append("text").attr("class", "a halo"); g.append("text").attr("class", "b halo"); return g; })
      .attr("transform", (d) => (W < 560 ? `translate(${x(d.r.key === "Iran" ? 1.2 : 8)},${d.r.key === "Iran" ? y(55) : y(30)})` : `translate(${W - M.r + 8},${d.y})`))
      .call((g) => g.select(".a").attr("font-size", 12).attr("font-weight", 700).attr("fill", (d) => COLOR[d.r.key]).attr("dy", "0.32em").text((d) => ({ Syria: "Syria · fall of Assad", Iran: "Iran · US strikes" })[d.r.key]))
      .call((g) => g.select(".b").attr("font-size", 11).attr("fill", N.muted).attr("dy", "1.5em").text((d) => LABEL[d.r.key]));
    overlay.attr("x", M.l).attr("y", M.t).attr("width", W - M.l - M.r).attr("height", H - M.t - M.b);
  }
  const html = (m) => `<div class="tt-title">${m < 60 ? `${m} minutes` : `${(m / 60).toFixed(m % 60 ? 1 : 0)} hours`} after the start</div>` +
    R.map((r) => `<div><b style="color:${COLOR[r.key]}">${r.key}</b>: ${val(r, m)} countries</div>`).join("");
  function at(m, ev) {
    cursor.attr("x1", x(m / 60)).attr("x2", x(m / 60)).attr("y1", M.t).attr("y2", H - M.b).attr("opacity", 1);
    tip.show(html(m), ev, cursor.node());
  }
  const near = (ev) => { const h = x.invert(d3.pointer(ev, svg.node())[0]) * 60; return mins.reduce((a, b) => (Math.abs(b - h) < Math.abs(a - h) ? b : a)); };
  overlay.on("pointermove", (ev) => at(near(ev), ev)).on("pointerleave", () => { cursor.attr("opacity", 0); tip.hide(); })
    .on("click", (ev) => { ev.stopPropagation(); at(near(ev), ev); });
  keyNav(svg.node(), {
    items: () => mins.map((m) => ({ m, el: null })),
    onFocus: ({ m }) => at(m, null),
    onEnter: ({ m }) => tip.pin(html(m), cursor.node()),
    onEscape: () => { tip.hide(true); cursor.attr("opacity", 0); },
    onBlur: () => { if (!tip.pinned) { tip.hide(); cursor.attr("opacity", 0); } },
  });
  showTheData(root, {
    caption: "New countries searching after the start: Syria (fall of Assad) and Iran (US strikes)", filename: "two-returns",
    columns: [{ key: "m", label: "Minutes after the start", num: true }, { key: "Syria", label: "Syria", num: true }, { key: "Iran", label: "Iran", num: true }],
    rows: mins.map((m) => ({ m, Syria: val(R.find((r) => r.key === "Syria"), m), Iran: val(R.find((r) => r.key === "Iran"), m) })),
  });
  render();
  if (!reducedMotion()) {
    gL.selectAll("path").attr("opacity", 0);
    onEnterView(wrap, () => {
      ["Syria", "Iran"].forEach((k, i) => {
        gL.selectAll("path").filter((r) => r.key === k).each(function () {
          const L = this.getTotalLength();
          d3.select(this).attr("opacity", 1).attr("stroke-dasharray", `${L} ${L}`).attr("stroke-dashoffset", L)
            .transition("draw").delay(i * 1300).duration(1000).ease(d3.easeCubicInOut).attr("stroke-dashoffset", 0)
            .on("end", function () { d3.select(this).attr("stroke-dasharray", null); });
        });
      });
    });
  }
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(render, 150); }).observe(wrap);
}

// ==================================================================== the ridgeline: 18 stories
export function mountRidge(root, data) {
  const G = gnbu();
  const N = neutral();
  const P = pubu();
  const GC = { crises: G.blue, stars: G.teal, tech: G.green };
  const ORDER = ["crises", "stars", "tech"];
  const stories = ORDER.flatMap((g) => data.stories.filter((s) => s.group === g).sort((a, b) => d3.max(b.countries_per_month) - d3.max(a.countries_per_month)));
  const months = data.months.map((m) => new Date(`${m}-01`));
  const cov = data.months.map((m) => data.coverage[m]);
  const partial = data.months.map((m, i) => cov[i][0] < cov[i][1]);
  const days = data.days.map((d) => new Date(d));
  const gapSet = new Set(data.gap_days);
  const scrollyEl = document.getElementById("waves-scrolly");
  const after = document.getElementById("waves-after");
  const announce = liveRegion(root);

  root.innerHTML = `
    <div class="controls rd-controls" role="group" aria-label="Show only">
      <span class="rd-show">Show only:</span>
      <button type="button" data-g="all" aria-pressed="true" disabled>All</button>
      ${ORDER.map((g) => `<button type="button" data-g="${g}" aria-pressed="false" disabled><i class="swatch" style="background:${GC[g]}"></i> ${data.groups[g]}</button>`).join("")}
    </div>
    <div class="rd-svg"></div>`;
  const wrap = root.querySelector(".rd-svg");
  const svg = d3.select(wrap).append("svg").attr("role", "img").attr("aria-roledescription", "ridgeline chart")
    .attr("aria-label", `${data.takeaway} 18 rows, one per story, countries per month from November 2024 to May 2026. Up and down arrows move between rows, left and right through months; Enter opens a row.`);
  const hatch = hatchPattern(svg);
  const gBand = svg.append("g"), gGap = svg.append("g"), gAxis = svg.append("g"), gRows = svg.append("g");
  const tip = createTooltip(root);
  const st = { step: 0, group: null, open: null, unlocked: false, focusRow: -1, focusMonth: -1 };
  let W, x, rowH, labelW, phone, yPos, H, openH = 170;

  const lit = (s) => (st.group ? s.group === st.group : st.step === 1 ? s.group === "crises" : st.step === 2 ? s.group === "stars" : st.step === 3 ? s.group === "tech" : false);

  function render() {
    W = wrap.clientWidth || 720;
    phone = W < 560;
    labelW = phone ? 0 : 150;
    rowH = phone ? 44 : 30;
    x = d3.scaleUtc([months[0], months[months.length - 1]], [labelW + 8, W - 54]);
    layoutRows(0);
  }
  function rowTop(i) {
    let y = 30;
    for (let k = 0; k < i; k++) y += rowH + (phone ? 14 : 0) + (st.open === k ? openH : 0) + (k > 0 && stories[k].group !== stories[k - 1].group ? 10 : 0);
    if (i > 0 && stories[i].group !== stories[i - 1].group) y += 10;
    return y + (phone ? 14 : 0);
  }
  function layoutRows(dur) {
    const n = stories.length;
    H = rowTop(n - 1) + rowH + (st.open === n - 1 ? openH : 0) + 44;
    svg.attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    const peakScale = d3.scaleLinear([0, 125], [0, rowH * 1.8]);
    // partial months, hatched, with their days
    const mw = x(months[1]) - x(months[0]);
    gGap.selectAll("g").data(data.months.map((m, i) => ({ m, i })).filter((d) => partial[d.i]), (d) => d.m).join((en) => {
      const g = en.append("g"); g.append("rect"); g.append("text"); return g;
    }).call((g) => {
      g.select("rect").attr("x", (d) => x(months[d.i]) - mw / 2).attr("width", mw).attr("y", 22).attr("height", H - 50).attr("fill", hatch).attr("opacity", 0.8);
      g.select("text").attr("x", (d) => x(months[d.i])).attr("y", 16).attr("text-anchor", "middle").attr("font-size", 10).attr("fill", N.muted)
        .text((d) => `${cov[d.i][0]}/${cov[d.i][1]}`);
    });
    // month axis
    gAxis.selectAll("*").remove();
    data.months.forEach((m, i) => {
      if (phone ? i % 3 !== 1 : false) return;
      gAxis.append("text").attr("x", x(months[i])).attr("y", H - 24).attr("text-anchor", "middle").attr("font-size", 10).attr("fill", N.muted)
        .text(shortMonth(months[i]));
      if (months[i].getUTCMonth() === 0) gAxis.append("text").attr("x", x(months[i])).attr("y", H - 11).attr("text-anchor", "middle")
        .attr("font-size", 10).attr("font-weight", 700).attr("fill", N.ink).text(months[i].getUTCFullYear());
    });
    // rows
    const area = (s) => d3.area().curve(d3.curveMonotoneX).x((v, i) => x(months[i])).y0(0).y1((v) => -peakScale(v))(s.countries_per_month);
    const rows = gRows.selectAll("g.row").data(stories, (s) => s.story).join((en) => {
      const g = en.append("g").attr("class", "row").attr("id", (s, i) => `rd-${i}`).style("cursor", "pointer");
      g.append("path").attr("class", "ar mark");
      g.append("line").attr("class", "base");
      g.append("text").attr("class", "name");
      g.append("text").attr("class", "peak halo");
      g.append("g").attr("class", "open");
      g.append("rect").attr("class", "hit").attr("fill", "transparent");
      return g;
    });
    rows.transition("layout").duration(dur).ease(d3.easeCubicInOut).attr("transform", (s, i) => `translate(0,${rowTop(i) + rowH})`);
    rows.select(".ar").attr("d", area);
    rows.select(".base").attr("x1", x(months[0])).attr("x2", x(months[months.length - 1])).attr("stroke", N.rule);
    rows.select(".name").attr("x", phone ? x(months[0]) : labelW).attr("y", phone ? -rowH - 2 : -4)
      .attr("text-anchor", phone ? "start" : "end").attr("font-size", 12).attr("fill", N.ink).text((s) => s.story.replace(" (Nicolás Maduro)", " (Maduro)"));
    rows.select(".hit").attr("x", phone ? 0 : 0).attr("width", W).attr("y", -rowH * 1.2).attr("height", rowH * 1.2 + 4);
    rows.each(function (s, i) { drawOpen(d3.select(this).select(".open"), s, i); });
    restyle(dur ? ms(300) : 0);
  }
  function restyle(dur = ms(300)) {
    const rows = gRows.selectAll("g.row");
    rows.select(".ar").transition("style").duration(dur)
      .attr("fill", (s) => GC[s.group]).attr("fill-opacity", (s) => (lit(s) ? 0.85 : 0.14))
      .attr("stroke", (s) => (st.focusRow >= 0 && stories[st.focusRow] === s ? N.ink : GC[s.group]))
      .attr("stroke-width", (s) => (st.focusRow >= 0 && stories[st.focusRow] === s ? 2 : 1));
    rows.select(".name").attr("font-weight", (s) => (lit(s) ? 700 : 400));
    const nearRight = (s) => x(new Date(`${s.peak_month}-01`)) > W * 0.68;
    rows.select(".peak").attr("text-anchor", (s) => (nearRight(s) ? "end" : "start"))
      .attr("x", (s) => x(new Date(`${s.peak_month}-01`)) + (nearRight(s) ? -6 : 4)).attr("y", (s) => -Math.min(rowH * 1.8, (s.peak_countries / 125) * rowH * 1.8) - 3)
      .attr("font-size", 11).attr("font-weight", 700).attr("fill", N.ink)
      .text((s) => (lit(s) ? `${s.peak_label} · ${s.peak_countries}` : ""));
    drawBands();
  }
  function drawBands() {
    gBand.selectAll("*").remove();
    const band = (a, b, label) => {
      const x0 = x(new Date(`${a}-01`)) - 8, x1 = x(new Date(`${b}-01`)) + 8;
      gBand.append("rect").attr("x", x0).attr("width", x1 - x0).attr("y", 22).attr("height", H - 50).attr("fill", N.gap);
      gBand.append("text").attr("x", (x0 + x1) / 2).attr("y", 32).attr("text-anchor", "middle").attr("font-size", 10).attr("font-weight", 700).attr("fill", N.muted).text(label);
    };
    if (st.step === 2 && !st.group) { band("2025-01", "2025-03", "awards season"); band("2026-01", "2026-03", "awards season"); }
    if (st.step === 3 && !st.group) band("2025-01", "2025-01", "January 2025");
  }

  // an open row: that story day by day, with its biggest return
  function drawOpen(g, s, i) {
    g.selectAll("*").remove();
    if (st.open !== i) return;
    const top = 8, h = openH - 56;
    const xd = d3.scaleUtc([days[0], days[days.length - 1]], [x(months[0]), x(months[months.length - 1])]);
    const yd = d3.scaleLinear([0, Math.max(10, d3.max(s.daily))], [top + h, top]);
    const bw = Math.max(1, (xd(days[1]) - xd(days[0])) - 0.3);
    g.append("rect").attr("x", x(months[0]) - 4).attr("width", x(months[months.length - 1]) - x(months[0]) + 8).attr("y", 0).attr("height", openH - 8).attr("fill", N.paper).attr("stroke", N.rule);
    g.selectAll("rect.d").data(s.daily.map((v, k) => ({ v, t: days[k], gap: gapSet.has(data.days[k]) }))).join("rect").attr("class", "d")
      .attr("x", (d) => xd(d.t)).attr("width", bw).attr("y", (d) => yd(d.v)).attr("height", (d) => yd(0) - yd(d.v))
      .attr("fill", (d) => (d.gap ? N.hatch : GC[s.group]));
    g.append("text").attr("x", x(months[0])).attr("y", top + h + 14).attr("font-size", 11).attr("fill", N.muted)
      .text(`Countries per day (max ${d3.max(s.daily)})`);
    const b = s.biggest_return;
    if (b) {
      const kind = b.kind === "neither" ? "built over hours" : b.kind === "shock" ? "a shock" : "scheduled";
      g.append("text").attr("x", x(months[0])).attr("y", top + h + 29).attr("font-size", 11).attr("fill", N.ink)
        .text(`Biggest return: ${d3.utcFormat("%b %-d, %Y")(new Date(b.start_utc))} · ${b.total_72h} countries in 72 h · ${b.at_1h} in the first hour · ${kind}`);
    }
  }

  // ------------------------------------------------------------------ hover, tap, keyboard
  const monthIdx = (ev) => {
    const t = x.invert(d3.pointer(ev, svg.node())[0]);
    return Math.max(0, Math.min(months.length - 1, d3.leastIndex(months, (m) => Math.abs(m - t))));
  };
  function html(s, i) {
    const c = s.countries_per_month[i];
    const why = s.drivers[data.months[i]];
    return `<div class="tt-title">${s.story} · ${fmtMonth(months[i])}</div><div>${c} countries</div>` +
      (why && c >= 15 ? `<div class="tt-muted">${why}</div>` : "") +
      (partial[i] ? `<div class="tt-muted">${cov[i][0]} of ${cov[i][1]} days collected; counts are a lower bound.</div>` : "");
  }
  function bindRows() {
    gRows.selectAll("g.row")
      .on("pointermove", function (ev, s) { if (ev.pointerType === "touch") return; const i = stories.indexOf(s); st.focusRow = i; restyle(0); tip.show(html(s, monthIdx(ev)), ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType === "touch") return; st.focusRow = -1; restyle(0); tip.hide(); })
      .on("click", function (ev, s) { ev.stopPropagation(); toggle(stories.indexOf(s)); });
  }
  function toggle(i) {
    st.open = st.open === i ? null : i;
    tip.hide(true);
    layoutRows(ms(400));
    bindRows();
    announce(st.open == null ? "Closed." : `${stories[i].story}: opened, day by day.`);
  }
  onEscape(() => { if (st.open != null) toggle(st.open); });
  const svgEl = svg.node();
  svgEl.tabIndex = 0;
  svgEl.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      st.focusRow = Math.max(0, Math.min(stories.length - 1, st.focusRow + (ev.key === "ArrowDown" ? 1 : -1)));
      if (st.focusMonth < 0) st.focusMonth = data.months.indexOf(stories[st.focusRow].peak_month);
    } else if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      ev.preventDefault();
      if (st.focusRow < 0) st.focusRow = 0;
      st.focusMonth = Math.max(0, Math.min(months.length - 1, (st.focusMonth < 0 ? 0 : st.focusMonth) + (ev.key === "ArrowRight" ? 1 : -1)));
    } else if (ev.key === "Enter" && st.focusRow >= 0) { ev.preventDefault(); toggle(st.focusRow); return; } else return;
    restyle(0);
    const s = stories[st.focusRow];
    tip.show(html(s, st.focusMonth), null, document.getElementById(`rd-${st.focusRow}`));
    announce(`${s.story}, ${fmtMonth(months[st.focusMonth])}: ${s.countries_per_month[st.focusMonth]} countries`);
  });
  svgEl.addEventListener("blur", () => { st.focusRow = -1; restyle(0); tip.hide(); });

  // ------------------------------------------------------------------ group filter (after the steps)
  const gb = root.querySelectorAll("[data-g]");
  gb.forEach((b) => b.addEventListener("click", () => {
    st.group = b.dataset.g === "all" ? null : b.dataset.g;
    if (!st.group) st.step = 0;
    gb.forEach((x2) => x2.setAttribute("aria-pressed", String(x2 === b)));
    restyle();
  }));

  // ------------------------------------------------------------------ steps
  function fadeInRows() {
    if (reducedMotion()) return;
    gRows.selectAll("g.row").attr("opacity", 0).transition("fade").delay((s, i) => i * 40).duration(300).attr("opacity", 1);
  }
  let started = false;
  scrolly(scrollyEl, (i) => {
    if (!started) { started = true; fadeInRows(); }
    st.step = i;
    if (i === 3 && !st.unlocked) { st.unlocked = true; gb.forEach((b) => { b.disabled = false; }); }
    if (!st.group) restyle();
  });

  // ------------------------------------------------------------------ after
  after.innerHTML = `<p class="source">Hover over a story to see what brought it back; tap a story to see it day by day. The 18 stories were hand-checked as recurring (Venezuela and Nicolás Maduro merged); they come from the top of a list ranked by months with 15 or more countries, so they favor long-running stories. Hatched months were partly collected (days shown at the top); their values are lower bounds. As of ${data.as_of}.</p>`;
  showTheData(after, {
    caption: "Countries per month for the 18 wave stories", filename: "wave-stories-per-month",
    columns: [{ key: "story", label: "Story" }, { key: "group", label: "Group", format: (v) => data.groups[v] }]
      .concat(data.months.map((m, i) => ({ key: `m${i}`, label: m, num: true })))
      .concat([{ key: "peak_label", label: "Widest return" }]),
    rows: stories.map((s) => ({ ...s, ...Object.fromEntries(s.countries_per_month.map((v, i) => [`m${i}`, v])) })),
  });

  render();
  bindRows();
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { render(); bindRows(); }, 150); }).observe(wrap);
}
