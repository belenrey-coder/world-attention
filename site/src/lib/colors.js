// Read the color tokens from CSS custom properties, so charts never hard-code a hue.
const css = () => getComputedStyle(document.documentElement);
const v = (name) => css().getPropertyValue(name).trim();

/** PuBu, light → dark: for "how many countries" only. */
export function pubu() {
  return [1, 2, 3, 4, 5, 6, 7].map((k) => v(`--pubu-${k}`));
}

/** GnBu steps by name: for "which topic or kind" only. */
export function gnbu() {
  return {
    deep: v("--gnbu-deep"), blue: v("--gnbu-blue"), sky: v("--gnbu-sky"), teal: v("--gnbu-teal"),
    green: v("--gnbu-green"), aqua: v("--gnbu-aqua"), mint: v("--gnbu-mint"),
  };
}

export function neutral() {
  return {
    ink: v("--ink"), muted: v("--muted"), faint: v("--faint"), rule: v("--rule"), land: v("--land"),
    gap: v("--gap"), context: v("--context"), otherData: v("--other-data"), hatch: v("--hatch"), paper: v("--paper"),
    ghost: v("--ghost"), off: v("--off"), own: v("--own"), nodata: v("--nodata"),
    barAppt: v("--bar-appt"), barOther: v("--bar-other"),
  };
}

/** Add the 45° hatch pattern (#DDE1E7 on white) to an SVG once; fill with url(#hatch). */
export function hatchPattern(svg) {
  const n = neutral();
  let defs = svg.select("defs");
  if (defs.empty()) defs = svg.insert("defs", ":first-child");
  if (!defs.select("#hatch").empty()) return "url(#hatch)";
  const p = defs.append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse")
    .attr("width", 6).attr("height", 6).attr("patternTransform", "rotate(45)");
  p.append("rect").attr("width", 6).attr("height", 6).attr("fill", n.paper);
  p.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 6).attr("stroke", n.hatch).attr("stroke-width", 2);
  return "url(#hatch)";
}
