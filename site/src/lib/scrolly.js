// Scroll engine (v1.1). Every chart's state depends only on where the reader is:
//  - the current step is computed from positions (the last step card whose top is above the offset line, 50% of the
//    viewport), on load, on resize, on Scrollama events and on any scroll (so jumps with the scroll bar are caught);
//  - onStep(index, direction, { animate, prev, past }) runs whenever that index changes: index -1 = before the first
//    step, the last index also covers "past the last step" (past = true once the container's end has gone by);
//  - animate is true only when the reader moves forward into the very next step by scrolling; loading mid-page,
//    jumping several steps or scrolling back all get animate = false, so charts cut straight to the end state.
import scrollama from "scrollama";
import { reducedMotion } from "./a11y.js";

const syncs = new Set();
let lastY = window.scrollY;
let loaded = false;
let raf = 0;

function runAll(source) {
  const delta = window.scrollY - lastY;
  const down = delta >= 0;
  lastY = window.scrollY;
  // a move of more than half a screen in one frame is a jump (scroll bar, keyboard End, a link), not reading
  const src = source === "scroll" && Math.abs(delta) > window.innerHeight * 0.5 ? "jump" : source;
  syncs.forEach((fn) => fn(src, down));
}
let pending = null;
function schedule(source) {
  // a real scroll in the same frame wins over a layout change, so the reader's scroll can still animate
  if (pending !== "scroll") pending = source;
  if (raf) return;
  const run = () => { if (!raf) return; cancelAnimationFrame(raf); clearTimeout(raf2); raf = 0; const src = pending; pending = null; runAll(src); };
  raf = requestAnimationFrame(run);
  raf2 = setTimeout(run, 120); // fallback when frames are throttled (background tabs)
}
let raf2 = 0;
window.addEventListener("scroll", () => schedule("scroll"), { passive: true });
let rt;
window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => runAll("resize"), 150); });
// charts mount at different times and change the page height: re-sync when the layout changes
new ResizeObserver(() => schedule("resize")).observe(document.body);
// first sync after layout; from then on the reader's scrolling can animate
requestAnimationFrame(() => requestAnimationFrame(() => { runAll("load"); loaded = true; }));

const line = (offset) => window.innerHeight * offset;

/** Scroll steps: container is a .scrolly with .step children. */
export function scrolly(container, onStep, { offset = 0.5 } = {}) {
  const steps = [...container.querySelectorAll(".step")];
  let cur = null;
  let wasPast = false;
  function indexNow() {
    const y = line(offset);
    let idx = -1;
    steps.forEach((s, k) => { if (s.getBoundingClientRect().top <= y) idx = k; });
    return idx;
  }
  function sync(source, down) {
    const idx = indexNow();
    const past = container.getBoundingClientRect().bottom <= line(offset);
    if (idx === cur && past === wasPast) return;
    const prev = cur;
    const animate = loaded && source === "scroll" && down && prev !== null && idx === prev + 1 && !reducedMotion();
    cur = idx;
    wasPast = past;
    steps.forEach((el, k) => el.classList.toggle("is-active", k === idx));
    if (idx !== prev) onStep(idx, down ? "down" : "up", { animate, prev, past });
    else if (past) onStep(idx, down ? "down" : "up", { animate: false, prev, past });
  }
  syncs.add(sync);
  const s = scrollama();
  s.setup({ step: steps, offset }).onStepEnter(() => schedule("scroll")).onStepExit(() => schedule("scroll"));
  if (loaded) requestAnimationFrame(() => sync("load", true));
  return { current: () => cur, sync: () => sync("load", true) };
}

/**
 * "Enters view" triggers: fn(animate) runs once when the element's top reaches the offset line, or right away (with
 * animate = false) if the reader is already past that point on load, after a resize or after a jump.
 */
export function onEnterView(el, fn, { offset = 0.5 } = {}) {
  let done = false;
  function sync(source, down) {
    if (done) return;
    if (el.getBoundingClientRect().top > line(offset)) return;
    done = true;
    syncs.delete(sync);
    // animate only if the reader scrolled it into view (not on load, not after a jump)
    fn(loaded && source === "scroll" && down && !reducedMotion());
  }
  syncs.add(sync);
  if (loaded) requestAnimationFrame(() => sync("load", true));
}
