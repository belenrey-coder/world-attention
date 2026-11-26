// One tooltip per chart. Desktop: follows the pointer. Phones (< 700 px or a coarse pointer): docks to the bottom of
// the chart. Tap shows it (tap equivalent of hover); tapping elsewhere or Escape closes it. Enter can pin it.
import { onEscape } from "./a11y.js";

const phone = () => window.matchMedia("(max-width: 699px), (pointer: coarse)").matches;

export function createTooltip(chartEl) {
  const host = chartEl.closest(".chart") || chartEl;
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.setAttribute("role", "status");
  tip.setAttribute("aria-live", "polite");
  const body = document.createElement("div");
  const close = document.createElement("button");
  close.type = "button";
  close.className = "tt-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  tip.append(close, body);
  host.appendChild(tip);
  let pinned = false;

  function place(ev, anchor) {
    if (phone()) {
      tip.classList.add("is-docked");
      tip.style.left = tip.style.top = "";
      return;
    }
    tip.classList.remove("is-docked");
    const hb = host.getBoundingClientRect();
    let x, y;
    if (ev && ev.clientX != null && !pinned) {
      x = ev.clientX - hb.left + 14;
      y = ev.clientY - hb.top + 14;
    } else if (anchor) {
      const ab = anchor.getBoundingClientRect();
      x = ab.right - hb.left + 8;
      y = ab.top - hb.top;
    } else return;
    const w = tip.offsetWidth || 240;
    const h = tip.offsetHeight || 80;
    if (x + w > hb.width) x = Math.max(0, x - w - 28);
    if (y + h > hb.height + 40) y = Math.max(0, y - h - 28);
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }

  const api = {
    /** html: string; ev: pointer event (desktop placement); anchor: element (keyboard / tap placement). */
    show(html, ev, anchor) {
      body.innerHTML = html;
      tip.classList.add("is-on");
      place(ev, anchor);
    },
    move(ev) { if (!pinned) place(ev); },
    pin(html, anchor) {
      pinned = true;
      tip.classList.add("is-pinned");
      api.show(html, null, anchor);
    },
    hide(force = false) {
      if (pinned && !force) return;
      pinned = false;
      tip.classList.remove("is-on", "is-pinned");
    },
    get pinned() { return pinned; },
    el: tip,
  };
  close.addEventListener("click", () => api.hide(true));
  onEscape(() => api.hide(true));
  // tap elsewhere closes
  document.addEventListener("pointerdown", (ev) => {
    if (!host.contains(ev.target)) api.hide(true);
  });
  return api;
}

/** Wire a set of marks: hover shows, tap toggles, leaving hides. getHtml(datum) -> string. */
export function bindTooltip(tip, selection, getHtml, { onEnter, onLeave } = {}) {
  selection
    .on("pointerenter", (ev, d) => {
      if (ev.pointerType === "touch") return;
      tip.show(getHtml(d), ev);
      onEnter && onEnter(d);
    })
    .on("pointermove", (ev) => { if (ev.pointerType !== "touch") tip.move(ev); })
    .on("pointerleave", (ev, d) => {
      if (ev.pointerType === "touch") return;
      tip.hide();
      onLeave && onLeave(d);
    })
    .on("click", (ev, d) => {
      // tap equivalent of hover (also a mouse click pins nothing; it just shows)
      ev.stopPropagation();
      tip.show(getHtml(d), ev, ev.currentTarget);
      onEnter && onEnter(d);
    });
}
