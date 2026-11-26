// Chapter 1 · Most searches never leave home (docs/SPEC.md, Chapter 1).
// Guess first; then real searches rain down (step 1) and settle into three piles whose heights are proportional
// to the share of topics that reached 1, 2 to 14, or 15+ countries (step 2).
import * as d3 from "d3";
import { scrolly } from "../lib/scrolly.js";
import { createTooltip } from "../lib/tooltip.js";
import { showTheData, downloadCSV } from "../lib/table.js";
import { searchBox } from "../lib/search.js";
import { ms, reducedMotion, onMotionChange, onEscape } from "../lib/a11y.js";
import { pubu, neutral } from "../lib/colors.js";

const FONT = 10;
const LINE = 13;

export function mountLocal(root, data) {
  const P = pubu();
  const N = neutral();
  const WORD = "#BCC4CF"; // pile words: neutral grey (spec)
  const PILE_COLOR = { "1": P[3], "2-14": P[5], "15+": P[6] }; // how many countries: PuBu, light → dark
  const piles = data.piles;
  const fmtPct = (s) => `${(s * 100).toFixed(1).replace(/\.0$/, "")}%`;
  const fmtK = (n) => (n >= 1000 ? `${Math.round(n / 1000).toLocaleString("en-US")},000` : n.toLocaleString("en-US"));
  const scrollyEl = document.getElementById("local-scrolly");
  const after = document.getElementById("local-after");

  // ------------------------------------------------------------------ guess first
  const answer = piles[0].share;
  const guessEl = document.getElementById("local-guess");
  guessEl.innerHTML = `
    <div class="guess">
      <p class="chart-title" id="lg-q">What share of trending topics never left one country?</p>
      <div class="controls">
        <input type="range" id="lg-range" min="0" max="100" step="1" value="50" aria-labelledby="lg-q" aria-valuetext="50%">
        <output for="lg-range" class="lg-val">50%</output>
        <button type="button" class="lg-submit">Show me</button>
        <button type="button" class="lg-skip linkish">Skip</button>
      </div>
      <div class="lg-answer" hidden>
        <svg class="lg-bar" role="img"></svg>
        <p class="result lg-text" aria-live="polite"></p>
      </div>
    </div>`;
  const gRange = guessEl.querySelector("#lg-range");
  const gVal = guessEl.querySelector(".lg-val");
  gRange.addEventListener("input", () => {
    gVal.textContent = `${gRange.value}%`;
    gRange.setAttribute("aria-valuetext", `${gRange.value}%`);
  });
  function reveal(guess) {
    const box = guessEl.querySelector(".lg-answer");
    box.hidden = false;
    guessEl.querySelector(".lg-submit").disabled = true;
    gRange.disabled = true;
    const W = box.clientWidth || 600;
    const svg = d3.select(box.querySelector("svg")).attr("viewBox", `0 0 ${W} 54`).attr("width", "100%")
      .attr("aria-label", `The answer is ${fmtPct(answer)}${guess != null ? `; you guessed ${guess}%` : ""}.`);
    svg.selectAll("*").remove();
    const x = d3.scaleLinear([0, 1], [0, W - 50]);
    svg.append("rect").attr("x", 0).attr("y", 18).attr("width", x(1)).attr("height", 12).attr("fill", N.gap);
    svg.append("rect").attr("x", 0).attr("y", 18).attr("height", 12).attr("fill", P[5]).attr("width", 0)
      .transition().duration(ms(600)).ease(d3.easeCubicInOut).attr("width", x(answer));
    svg.append("text").attr("x", x(answer) + 6).attr("y", 29).attr("font-size", 14).attr("font-weight", 700)
      .attr("fill", N.ink).text(fmtPct(answer));
    if (guess != null) {
      svg.append("line").attr("x1", x(guess / 100)).attr("x2", x(guess / 100)).attr("y1", 12).attr("y2", 36)
        .attr("stroke", N.ink).attr("stroke-width", 2);
      svg.append("text").attr("x", x(guess / 100)).attr("y", 50).attr("text-anchor", "middle").attr("font-size", 12)
        .attr("fill", N.muted).text(`your guess: ${guess}%`);
    }
    const diff = guess == null ? "" : Math.abs(guess / 100 - answer) < 0.05 ? " You were close."
      : guess / 100 < answer ? " You guessed lower: local is the rule, not the exception." : "";
    guessEl.querySelector(".lg-text").textContent =
      `${fmtPct(answer)} of the ${data.total_topics.toLocaleString("en-US")} topics never left one country.${diff}`;
  }
  guessEl.querySelector(".lg-submit").addEventListener("click", () => reveal(+gRange.value));
  guessEl.querySelector(".lg-skip").addEventListener("click", () => reveal(null));

  // ------------------------------------------------------------------ piles chart
  root.innerHTML = `<div class="lp-svg"></div>`;
  const svgWrap = root.querySelector(".lp-svg");
  const svg = d3.select(svgWrap).append("svg").attr("role", "img")
    .attr("aria-label", `${data.takeaway} Three piles of real searches: ${piles.map((p) => `${fmtPct(p.share)} ${p.label}`).join(", ")}.`);
  const gLabels = svg.append("g").attr("class", "lp-labels");
  const gWords = svg.append("g").attr("class", "lp-words");
  const tip = createTooltip(root);

  let stage = -1; // -1 empty, 0 rain, 1 settled
  let found = null;
  let focusWord = null;
  let laid = [];

  function layout() {
    const W = svgWrap.clientWidth || 720;
    const vh = window.innerHeight;
    const phone = W < 560;
    const gap = phone ? 0 : 24;
    const colW = phone ? W : (W - 2 * gap) / 3;
    const maxH = phone ? Math.min(260, vh * 0.32) : Math.min(470, vh * 0.58);
    const labelH = phone ? 96 : 166;
    // heights proportional to share; the smallest pile is drawn at least one line tall (noted in the source)
    const hs = piles.map((p) => Math.max(LINE, (p.share / piles[0].share) * maxH));
    const ctx = document.createElement("canvas").getContext("2d");
    ctx.font = `${FONT}px "Libre Franklin", sans-serif`;
    const words = phone ? subsetForPhone(data.words) : data.words;
    const out = [];
    let H = 0;
    const boxes = [];
    piles.forEach((p, i) => {
      const x0 = phone ? 0 : i * (colW + gap);
      const yBase = phone ? (boxes.length ? boxes[i - 1].yBase + labelH + hs[i] + 20 : labelH + hs[0]) : labelH + maxH;
      const top = yBase - hs[i];
      boxes.push({ p, x0, top, yBase, w: colW, h: hs[i] });
      // flow words line by line from the bottom of the pile up
      const list = words.filter((w) => w.pile === p.group).sort((a, b) => (b.named - a.named));
      let line = 0, cx = 0;
      for (const w of list) {
        const tw = ctx.measureText(w.text).width;
        if (cx + tw > colW && cx > 0) { line += 1; cx = 0; }
        const y = yBase - line * LINE - 3;
        if (y - FONT < top - 1) break;
        out.push({ w, x: x0 + cx, y, pile: i });
        cx += tw + 7;
      }
      H = Math.max(H, yBase + 8);
    });
    return { W, H, boxes, words: out, phone };
  }
  function subsetForPhone(all) {
    const cap = { "1": 150, "2-14": 40, "15+": 16 };
    const n = {};
    return all.filter((w) => { n[w.pile] = (n[w.pile] || 0) + 1; return n[w.pile] <= cap[w.pile]; });
  }

  let L;
  function render() {
    L = layout();
    svg.attr("viewBox", `0 0 ${L.W} ${L.H}`).attr("width", L.W).attr("height", L.H);
    laid = L.words;
    // rain positions: scattered over the area (deterministic per word)
    const rnd = d3.randomLcg(42);
    laid.forEach((d) => { d.rx = rnd() * (L.W - 80); d.ry = 20 + rnd() * (L.H - 40); d.delay = rnd() * 1800; });

    // labels per pile
    gLabels.selectAll("g.pl").data(L.boxes).join((en) => {
      const g = en.append("g").attr("class", "pl");
      g.append("line").attr("class", "rule");
      g.append("text").attr("class", "num");
      g.append("text").attr("class", "lab");
      g.append("text").attr("class", "cnt");
      [0, 1].forEach((j) => { g.append("text").attr("class", `exn${j}`); g.append("text").attr("class", `exd${j}`); });
      return g;
    }).each(function (b) {
      const g = d3.select(this);
      const col = PILE_COLOR[b.p.group];
      const y = b.top - (L.phone ? 96 : 166);
      const named = data.words.filter((w) => w.pile === b.p.group && w.named);
      g.select(".rule").attr("x1", b.x0).attr("x2", b.x0 + Math.min(b.w, 220)).attr("y1", y).attr("y2", y)
        .attr("stroke", col).attr("stroke-width", 3);
      g.select(".num").attr("x", b.x0).attr("y", y + (L.phone ? 34 : 50)).attr("font-family", "'Source Serif 4', Georgia, serif")
        .attr("font-size", L.phone ? 32 : 50).attr("font-weight", 600).attr("fill", col).text(fmtPct(b.p.share));
      g.select(".lab").attr("x", b.x0).attr("y", y + (L.phone ? 52 : 72)).attr("font-size", 13).attr("font-weight", 700)
        .attr("fill", N.ink).text(b.p.label);
      g.select(".cnt").attr("x", b.x0).attr("y", y + (L.phone ? 66 : 87)).attr("font-size", 12).attr("fill", N.muted)
        .text(`${fmtK(b.p.topics)} topics`);
      // two named examples, each on two short lines: name · countries, then what it is
      // phones: one example per pile, on one line
      g.selectAll("[class^=exn], [class^=exd]").text("");
      named.slice(0, L.phone ? 1 : 2).forEach((w, j) => {
        const y0 = y + (L.phone ? 82 : 106) + j * 30;
        const where = b.p.group === "1" ? (w.country_names[0] || "") : `${w.countries} countries`;
        g.select(`.exn${j}`).attr("x", b.x0).attr("y", y0).attr("font-size", 12).attr("fill", N.ink)
          .html(`<tspan font-weight="700">${esc(w.translation || w.text)}</tspan><tspan fill="${N.muted}"> · ${esc(where)}</tspan>`);
        g.select(`.exd${j}`).attr("x", b.x0).attr("y", y0 + 14).attr("font-size", 12).attr("fill", N.muted)
          .text(L.phone ? "" : w.note || "");
      });
    });

    const sel = gWords.selectAll("text.w").data(laid, (d) => d.w.text + d.pile).join("text")
      .attr("class", "w mark").attr("font-size", FONT)
      .attr("id", (d, i) => `lw-${i}`)
      .text((d) => d.w.text)
      .style("cursor", "pointer");
    bind(sel);
    applyStage(0);
  }
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function wordFill(d) {
    if (found) return d.w === found ? P[5] : WORD;
    if (stage >= 1 && d.w.named) return PILE_COLOR[d.w.pile];
    return WORD;
  }
  function wordOpacity(d) {
    if (stage < 0) return 0;
    if (found) return d.w === found ? 1 : 0.3;
    return 1;
  }
  function applyStage(dur) {
    const words = gWords.selectAll("text.w");
    if (stage <= 0) {
      gLabels.transition().duration(dur ? ms(300) : 0).attr("opacity", 0);
    }
    if (stage < 0) {
      words.interrupt().attr("x", (d) => d.rx).attr("y", -20).attr("opacity", 0);
      return;
    }
    if (stage === 0) {
      words.interrupt();
      if (dur && !reducedMotion()) {
        words.attr("x", (d) => d.rx).attr("y", -20).attr("opacity", 0)
          .transition().delay((d) => d.delay).duration(1200).ease(d3.easeQuadIn)
          .attr("y", (d) => d.ry).attr("opacity", 1);
      } else {
        words.attr("x", (d) => d.rx).attr("y", (d) => d.ry).attr("opacity", 1);
      }
      words.attr("fill", WORD);
      return;
    }
    // settled
    words.interrupt();
    const t = dur && !reducedMotion() ? 800 : 0;
    words.transition().duration(t).ease(d3.easeCubicInOut)
      .attr("x", (d) => d.x).attr("y", (d) => d.y).attr("opacity", wordOpacity).attr("fill", wordFill);
    gLabels.transition().delay(t ? t + 300 : 0).duration(t ? 300 : 0).attr("opacity", 1);
    replay.hidden = reducedMotion();
  }
  function recolor() {
    gWords.selectAll("text.w").transition().duration(ms(300)).attr("fill", wordFill).attr("opacity", wordOpacity)
      .attr("stroke", (d) => (d === focusWord ? N.ink : "none")).attr("stroke-width", 0.6);
  }

  // ------------------------------------------------------------------ tooltip, tap, keyboard
  const pileName = (g) => piles.find((p) => p.group === g).label;
  function html(d) {
    const w = d.w;
    const where = w.countries === 1 ? `Trended in 1 country: ${w.country_names[0]}`
      : `Trended in ${w.countries} countries: ${w.country_names.slice(0, 6).join(", ")}${w.countries > 6 ? ", …" : ""}`;
    return `<div class="tt-title">${esc(w.text)}</div>` +
      (w.translation ? `<div class="tt-muted">${esc(w.translation)}</div>` : "") +
      `<div>${where}</div><div class="tt-muted">Pile: ${pileName(w.pile)} (over 18 months)</div>`;
  }
  function bind(sel) {
    sel.on("pointerenter", (ev, d) => { if (ev.pointerType !== "touch" && stage >= 0) tip.show(html(d), ev); })
      .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
      .on("pointerleave", (ev) => { if (ev.pointerType !== "touch") tip.hide(); })
      .on("click", (ev, d) => { ev.stopPropagation(); if (stage >= 0) tip.show(html(d), ev, ev.currentTarget); });
  }
  // keyboard: Tab to each pile; arrows step through its words; Enter opens the tooltip
  const keyLayer = d3.select(root).append("div").attr("class", "lp-keys sr-focus");
  function keyButtons() {
    keyLayer.selectAll("button").data(piles).join("button").attr("type", "button")
      .attr("class", "lp-key").text((p) => `${fmtPct(p.share)} pile: ${p.label}. Arrow keys step through its words.`)
      .on("keydown", function (ev, p) {
        const list = laid.filter((d) => d.w.pile === p.group);
        if (!list.length) return;
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
        let i = list.indexOf(focusWord);
        if (step) {
          ev.preventDefault();
          i = i < 0 ? 0 : Math.max(0, Math.min(list.length - 1, i + step));
          focusWord = list[i];
          recolor();
          const el = gWords.selectAll("text.w").filter((d) => d === focusWord).node();
          tip.show(html(focusWord), null, el);
        } else if (ev.key === "Enter" && focusWord) {
          ev.preventDefault();
          const el = gWords.selectAll("text.w").filter((d) => d === focusWord).node();
          tip.pin(html(focusWord), el);
        }
      })
      .on("blur", () => { if (!tip.pinned) { focusWord = null; tip.hide(); recolor(); } });
  }
  onEscape(() => { focusWord = null; recolor(); });

  // ------------------------------------------------------------------ after the chart: replay, find, data
  after.innerHTML = `<div class="controls lp-controls"><button type="button" class="lp-replay">↻ Replay the rain</button><span class="lp-search"></span></div><p class="result lp-result" aria-live="polite"></p>
    <p class="source">Source: GoogleTrendArchive, national Trending Now feeds, Nov. 27, 2024 to May 17, 2026. A topic merges every spelling and language of the same thing; a country counts once. Words are a random sample of real searches from each group (at least 3 trends each; hidden topics and people reaching fewer than 15 countries left out), not one per topic. Pile heights are proportional to share (${piles.map((p) => (p.share * 100).toFixed(1)).join(" : ")}); the smallest is drawn one line tall. As of ${data.as_of}.</p>`;
  const replay = after.querySelector(".lp-replay");
  replay.hidden = true;
  replay.addEventListener("click", () => {
    stage = 0; applyStage(1);
    setTimeout(() => { stage = 1; applyStage(1); }, 3200);
  });
  const result = after.querySelector(".lp-result");
  searchBox(after.querySelector(".lp-search"), {
    label: "Find a topic", placeholder: "Find a topic",
    items: data.words.map((w, i) => ({ id: i, name: w.translation ? `${w.text} (${w.translation})` : w.text, w })),
    onPick: (it) => {
      found = it.w;
      if (stage < 1) { stage = 1; applyStage(0); }
      recolor();
      const shown = laid.some((d) => d.w === found);
      result.textContent = `“${found.text}” is in the pile that ${pileName(found.pile)}: ${found.countries === 1 ? `1 country (${found.country_names[0]})` : `${found.countries} countries`}.${shown ? "" : " (Not drawn on this screen size.)"}`;
    },
    onNoMatch: () => { found = null; recolor(); result.textContent = "Not in our sample; try another word."; },
  });
  showTheData(after, {
    caption: `Trending topics by how many countries they reached, Nov. 2024 to May 2026 (${data.total_topics.toLocaleString("en-US")} topics)`,
    filename: "topics-by-countries-reached",
    columns: [
      { key: "label", label: "Group" },
      { key: "topics", label: "Topics", num: true, format: (v) => v.toLocaleString("en-US") },
      { key: "share", label: "Share", num: true, format: (v) => fmtPct(v) },
    ],
    rows: piles,
    extra: [{
      label: "Download the sampled searches",
      onClick: () => downloadCSV("sampled-searches", [
        { key: "text", label: "Search" }, { key: "translation", label: "English" },
        { key: "pile", label: "Countries group" }, { key: "countries", label: "Countries" },
        { key: "country_names", label: "Country names", format: (v) => v.join("; ") },
      ], data.words),
    }],
  });

  // ------------------------------------------------------------------ steps
  render();
  keyButtons();
  stage = reducedMotion() ? 1 : -1;
  applyStage(0);
  scrolly(scrollyEl, (i) => {
    if (reducedMotion()) { stage = 1; applyStage(0); return; }
    stage = i;
    applyStage(1);
  });
  onMotionChange((red) => { if (red) { stage = 1; applyStage(0); } replay.hidden = red || stage < 1; });
  let rt;
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { const s = stage; render(); stage = s; applyStage(0); }, 150); }).observe(svgWrap);
}
