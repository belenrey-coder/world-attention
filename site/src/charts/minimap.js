// A small Equal Earth map in the Opening's encoding (PuBu by 10-minute refresh after the first country, darkest =
// first; "Later" outlined), with a one-time replay. Used by the Shocks event card.
import * as d3 from "d3";
import { feature } from "topojson-client";
import worldUrl from "world-atlas/countries-50m.json?url";
import { pubu, neutral } from "../lib/colors.js";
import { reducedMotion } from "../lib/a11y.js";

let worldP = null;
let countriesP = null;
const world = () => (worldP ||= fetch(worldUrl).then((r) => r.json()));
const countryList = () => (countriesP ||= fetch(`${import.meta.env.BASE_URL}data/countries.json`).then((r) => r.json()));

export const BIN_LABELS = ["+0", "+10 min", "+20 min", "+30 min", "+40 min", "+50 min", "+60 min", "Later"];

/** el: container; minutes: [[iso2, minutes after the first country], ...]. Returns { replay() }. */
export async function miniMap(el, minutes, { label = "" } = {}) {
  const [w, cl] = await Promise.all([world(), countryList()]);
  const P = pubu();
  const N = neutral();
  const SHADE = [P[6], P[5], P[4], P[3], P[2], P[1], P[0], N.paper];
  const isoById = new Map(cl.countries.map((c) => [c.id, c.iso2]));
  const bin = new Map(minutes.map(([c, m]) => [c, Math.min(7, Math.floor(m / 10))]));
  const land = feature(w, w.objects.countries).features.filter((f) => f.id !== "010");
  const W = el.clientWidth || 360;
  const proj = d3.geoEqualEarth().fitWidth(W, { type: "FeatureCollection", features: land });
  const path = d3.geoPath(proj);
  const H = Math.ceil(path.bounds({ type: "FeatureCollection", features: land })[1][1]) + 2;
  el.replaceChildren();
  const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H)
    .attr("role", "img").attr("aria-label", label);
  const paths = svg.append("g").selectAll("path").data(land).join("path").attr("d", path)
    .attr("stroke", N.paper).attr("stroke-width", 0.4).attr("fill", N.land);
  const counter = d3.select(el).append("p").attr("class", "mm-counter");
  let timer = null;

  function paint(k) {
    paths.attr("fill", (f) => {
      const b = bin.get(isoById.get(f.id));
      return b != null && b <= k ? SHADE[b] : N.land;
    }).attr("stroke", (f) => (bin.get(isoById.get(f.id)) === 7 && k >= 7 ? P[2] : N.paper));
    const n = [...bin.values()].filter((b) => b <= k).length;
    counter.text(k < 0 ? "" : `${k >= 7 ? "Within 24 hours" : BIN_LABELS[k]} · ${n} countries`);
  }
  function replay() {
    clearInterval(timer);
    let k = 0;
    paint(0);
    timer = setInterval(() => { k += 1; paint(k); if (k >= 7) clearInterval(timer); }, reducedMotion() ? 500 : 700);
  }
  paint(7);
  return { replay, stop: () => clearInterval(timer) };
}
