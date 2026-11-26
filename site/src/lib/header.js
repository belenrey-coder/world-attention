// Title screen → article header, linked to the scroll position (docs/SPEC.md, Chapter 0).
// p = 0 at the top of the page: title (64 px) and subtitle (22 px) centered in the viewport, data line pinned to the
// bottom. Over the first d px of scrolling (d ≈ 60% of a screen: what makes the header end flush with the Opening),
// p goes to 1: the block moves to the top (80 px padding) and shrinks to 44 / 20 px, the byline fades in and the data
// line moves up under it. Scrolling back reverses it. At p = 1 the block is a normal header that scrolls away.
// Reduced motion: no in-between states; past 10% of the screen the header state appears.
import { reducedMotion, onMotionChange } from "./a11y.js";

const T0 = 64, T1 = 44;        // title px
const S0 = 22, S1 = 20;        // subtitle px
const PAD_TOP = 80;            // header top padding
const PAD_BOTTOM = 36;         // space between the data line and the Opening
const DATA_BOTTOM = 20;        // the data line's distance from the bottom of the title screen at p = 0

const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (x) => Math.max(0, Math.min(1, x));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2); // cubic in-out

export function titleHeader(section) {
  const head = section.querySelector(".ts-head");
  const title = section.querySelector(".ts-title");
  const sub = section.querySelector(".ts-sub");
  const byline = section.querySelector(".ts-byline");
  const data = section.querySelector(".ts-data");
  const motion = section.querySelector(".ts-motion");
  let vh = 0, d = 1, group0 = 0;

  function setSizes(p) {
    title.style.fontSize = `${lerp(T0, T1, p)}px`;
    sub.style.fontSize = `${lerp(S0, S1, p)}px`;
  }

  // geometry that only changes with the window size (and once the web fonts arrive)
  function measure() {
    vh = section.clientHeight;
    data.style.transform = "";
    setSizes(1);
    const hFinal = head.offsetHeight;                       // title + subtitle + byline + data line at header size
    d = Math.max(1, vh - (PAD_TOP + hFinal + PAD_BOTTOM));  // header ends exactly where the Opening starts
    section.dataset.move = String(Math.round(d));           // scroll distance of the move (read by tests)
    setSizes(0);
    group0 = byline.offsetTop;                              // title + subtitle height at title-screen size
    update();
  }

  function update() {
    const s = Math.max(0, window.scrollY);
    const raw = reducedMotion() ? (s > 0.1 * vh ? 1 : 0) : clamp(s / d);
    const p = reducedMotion() ? raw : ease(raw);
    setSizes(p);
    const y = lerp((vh - group0) / 2, PAD_TOP, p);         // where the title's top sits in the viewport
    // the section scrolls up by s; until the move ends the block is held in place, then it scrolls with the page
    head.style.transform = `translateY(${y + Math.min(s, d)}px)`;
    const fade = clamp((p - 0.55) / 0.45);
    byline.style.opacity = String(fade);
    motion.style.opacity = String(fade);
    motion.dataset.off = String(fade < 0.5);
    motion.style.top = `${byline.offsetTop + (byline.offsetHeight - motion.offsetHeight) / 2}px`;
    // the data line travels from the bottom of the title screen to its place under the byline
    const natural = y + data.offsetTop;
    const start = vh - DATA_BOTTOM - data.offsetHeight;
    data.style.transform = `translateY(${(start - natural) * (1 - p)}px)`;
  }

  let raf = 0;
  const onScroll = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; update(); }); };
  window.addEventListener("scroll", onScroll, { passive: true });
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(measure, 100); });
  onMotionChange(update);
  measure();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
}
