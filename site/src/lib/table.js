import { methodologyHtml } from "../methodology.js";
// "Show the data": a toggle that reveals the plain HTML table behind a chart, sortable, with a CSV download built
// in the browser from the same rows (no CSV file is published).

/**
 * container: element to mount into.
 * columns: [{ key, label, num?: bool, format?: (v, row) => string, sortValue?: (row) => any }]
 * rows: array of objects. caption: string. filename: download name (without .csv).
 */
/** Build a CSV in the browser and download it (no CSV file is published). */
export function downloadCSV(filename, columns, rows, cell = (c, r) => (c.format ? c.format(r[c.key], r) : r[c.key] ?? "")) {
  const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lines = [columns.map((c) => esc(c.label)).join(",")]
    .concat(rows.map((r) => columns.map((c) => esc(cell(c, r))).join(",")));
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

/**
 * extra: [{ label, onClick }] buttons shown next to "Download CSV".
 * methodology: a key of METHODS (src/methodology.js): adds a "Methodology" toggle beside "Show the data".
 */
export function showTheData(container, { columns, rows, caption, filename, label = "Show the data", extra = [], methodology = null }) {
  const wrap = document.createElement("div");
  wrap.className = "show-data";
  wrap.dataset.open = "false";
  const id = `tbl-${Math.random().toString(36).slice(2, 8)}`;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", id);
  toggle.textContent = `▸ ${label}`;

  const tw = document.createElement("div");
  tw.className = "table-wrap";
  tw.id = id;
  const table = document.createElement("table");
  table.className = "data";
  const cap = document.createElement("caption");
  cap.textContent = caption;
  const thead = document.createElement("thead");
  const tbody = document.createElement("tbody");
  table.append(cap, thead, tbody);
  tw.appendChild(table);

  const actions = document.createElement("div");
  actions.className = "table-actions";
  const dl = document.createElement("button");
  dl.type = "button";
  dl.textContent = "Download CSV";
  actions.appendChild(dl);
  extra.forEach((x) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = x.label;
    b.addEventListener("click", x.onClick);
    actions.appendChild(b);
  });

  let sortKey = null;
  let sortDir = 1;
  let data = rows.slice();

  const hr = document.createElement("tr");
  columns.forEach((c) => {
    const th = document.createElement("th");
    th.scope = "col";
    if (c.num) th.className = "num";
    th.setAttribute("aria-sort", "none");
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = c.label;
    b.addEventListener("click", () => {
      sortDir = sortKey === c.key ? -sortDir : 1;
      sortKey = c.key;
      [...hr.children].forEach((x) => x.setAttribute("aria-sort", "none"));
      th.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
      const v = c.sortValue || ((r) => r[c.key]);
      data.sort((a, b2) => {
        const x = v(a), y = v(b2);
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
      });
      render();
    });
    th.appendChild(b);
    hr.appendChild(th);
  });
  thead.appendChild(hr);

  function cell(c, r) {
    const v = r[c.key];
    return c.format ? c.format(v, r) : v == null ? "" : String(v);
  }

  function render() {
    tbody.replaceChildren(...data.map((r) => {
      const tr = document.createElement("tr");
      columns.forEach((c) => {
        const td = document.createElement("td");
        if (c.num) td.className = "num";
        td.textContent = cell(c, r);
        tr.appendChild(td);
      });
      return tr;
    }));
  }

  toggle.addEventListener("click", () => {
    const open = wrap.dataset.open !== "true";
    wrap.dataset.open = String(open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = `${open ? "▾" : "▸"} ${label}`;
    if (open && !tbody.children.length) render();
  });

  dl.addEventListener("click", () => {
    const esc = (s) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
    const lines = [columns.map((c) => esc(c.label)).join(",")]
      .concat(data.map((r) => columns.map((c) => esc(cell(c, r))).join(",")));
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${filename}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  const bar = document.createElement("div");
  bar.className = "sd-toggles";
  bar.appendChild(toggle);
  const parts = [bar, tw, actions];
  if (methodology) {
    const mid = `${id}-m`;
    const mt = document.createElement("button");
    mt.type = "button";
    mt.setAttribute("aria-expanded", "false");
    mt.setAttribute("aria-controls", mid);
    mt.textContent = "▸ Methodology";
    const mp = document.createElement("div");
    mp.className = "methodology";
    mp.id = mid;
    mp.hidden = true;
    mp.innerHTML = methodologyHtml(methodology);
    mt.addEventListener("click", () => {
      mp.hidden = !mp.hidden;
      mt.setAttribute("aria-expanded", String(!mp.hidden));
      mt.textContent = `${mp.hidden ? "▸" : "▾"} Methodology`;
    });
    bar.appendChild(mt);
    parts.push(mp);
  }
  wrap.append(...parts);
  container.appendChild(wrap);
  return { update(newRows) { data = newRows.slice(); if (tbody.children.length) render(); } };
}
