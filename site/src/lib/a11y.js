// Reduced motion, keyboard navigation through marks, and small accessibility helpers.

const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
const listeners = new Set();
let override = null; // null = follow the system setting; true / false = reader's choice on this page

try {
  const saved = localStorage.getItem("aao-motion");
  if (saved === "reduced") override = true;
  if (saved === "full") override = false;
} catch (e) { /* storage blocked: follow the system */ }

export function reducedMotion() {
  return override === null ? mq.matches : override;
}

function apply() {
  document.documentElement.dataset.motion = reducedMotion() ? "reduced" : "full";
  listeners.forEach((fn) => fn(reducedMotion()));
}
mq.addEventListener("change", apply);

export function onMotionChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setReducedMotion(value) {
  override = value;
  try { localStorage.setItem("aao-motion", value ? "reduced" : "full"); } catch (e) { /* ignore */ }
  apply();
}

/** Duration helper: 0 under reduced motion. */
export function ms(duration) {
  return reducedMotion() ? 0 : duration;
}

export const DUR = { move: 600, color: 300, tip: 150 };

/** Mount the "Reduce motion" switch (a toggle button) into a container. */
export function motionSwitch(container) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "motion-switch";
  const sync = () => {
    b.setAttribute("aria-pressed", String(reducedMotion()));
    b.textContent = reducedMotion() ? "Motion: reduced" : "Motion: on";
  };
  b.addEventListener("click", () => setReducedMotion(!reducedMotion()));
  onMotionChange(sync);
  sync();
  container.appendChild(b);
  return b;
}

/**
 * Arrow-key navigation through an ordered list of marks inside a focusable chart.
 * The chart element gets tabindex=0 and aria-activedescendant follows the focused mark.
 * opts: { items: () => array of {id, el}, onFocus(item, i), onEnter(item, i), onEscape() }
 */
export function keyNav(chartEl, opts) {
  let i = -1;
  chartEl.tabIndex = 0;
  chartEl.addEventListener("keydown", (ev) => {
    const items = opts.items();
    if (!items.length) return;
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
    if (step) {
      ev.preventDefault();
      i = i < 0 ? 0 : Math.max(0, Math.min(items.length - 1, i + step));
      focusAt(items, i);
    } else if (ev.key === "Home" || ev.key === "End") {
      ev.preventDefault();
      i = ev.key === "Home" ? 0 : items.length - 1;
      focusAt(items, i);
    } else if (ev.key === "Enter" && i >= 0) {
      ev.preventDefault();
      opts.onEnter && opts.onEnter(items[i], i);
    } else if (ev.key === "Escape") {
      opts.onEscape && opts.onEscape();
    }
  });
  chartEl.addEventListener("blur", () => opts.onBlur && opts.onBlur());
  function focusAt(items, k) {
    const it = items[k];
    if (it.el && it.el.id) chartEl.setAttribute("aria-activedescendant", it.el.id);
    opts.onFocus && opts.onFocus(it, k);
  }
  return { reset() { i = -1; chartEl.removeAttribute("aria-activedescendant"); } };
}

/** Escape closes any open tooltip, card or row: one global registry. */
const closers = new Set();
export function onEscape(fn) { closers.add(fn); return () => closers.delete(fn); }
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closers.forEach((fn) => fn());
});

/** Polite live region for generated sentences (search results, counters). */
export function liveRegion(container) {
  const el = document.createElement("p");
  el.className = "sr-only";
  el.setAttribute("aria-live", "polite");
  container.appendChild(el);
  return (text) => { el.textContent = text; };
}

apply();
