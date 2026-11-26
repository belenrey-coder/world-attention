// Title screen → article header (docs/SPEC.md, Chapter 0). The page opens on the title and subtitle alone, centered;
// on the first scroll they move up and shrink into the header (600 ms) and the byline appears. One way only; a reload
// in the same visit, a link into the page or reduced motion shows the header in place.
import { reducedMotion } from "./a11y.js";

export function titleHeader(el) {
  const root = document.documentElement;
  const done = () => root.dataset.header === "1";

  function collapse(animate) {
    if (done()) return;
    const parts = [...el.querySelectorAll("h1, .dek, .dataline")];
    const before = parts.map((p) => p.getBoundingClientRect());
    root.dataset.header = "1";
    try { sessionStorage.setItem("aao-header", "1"); } catch (e) { /* private mode: fine */ }
    off();
    if (!animate || reducedMotion() || !el.animate) return;
    const ease = "cubic-bezier(.65,0,.35,1)";
    parts.forEach((p, i) => {
      const a = before[i];
      const b = p.getBoundingClientRect();
      const s = p.tagName === "H1" && b.height ? a.height / b.height : 1;
      p.style.transformOrigin = "0 0";
      p.animate([{ transform: `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${s})` }, { transform: "none" }],
        { duration: 600, easing: ease });
    });
    el.querySelector(".byline").animate([{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 300, easing: ease, fill: "backwards" });
  }

  const onScroll = () => { if (window.scrollY > 0) collapse(true); };
  // keyboard readers: moving focus into the page (past the data link) brings the header in too
  const onFocus = (ev) => { if (!ev.target.closest(".dataline")) collapse(true); };
  function off() {
    window.removeEventListener("scroll", onScroll);
    document.removeEventListener("focusin", onFocus);
  }
  if (done()) return;
  if (window.scrollY > 0) { collapse(false); return; }
  window.addEventListener("scroll", onScroll, { passive: true });
  document.addEventListener("focusin", onFocus);
}
