// Accessible autocomplete (ARIA combobox): type, arrow through suggestions, Enter picks, Escape closes.

/**
 * container: element to mount into.
 * opts: { label, placeholder, items: [{ id, name, ... }], onPick(item), onNoMatch(query), max }
 */
export function searchBox(container, { label, placeholder = "", items, onPick, onNoMatch, max = 8 }) {
  const wrap = document.createElement("div");
  wrap.className = "search";
  const id = `s-${Math.random().toString(36).slice(2, 8)}`;
  const lab = document.createElement("label");
  lab.className = "sr-only";
  lab.htmlFor = `${id}-in`;
  lab.textContent = label;
  const input = document.createElement("input");
  input.type = "search";
  input.id = `${id}-in`;
  input.placeholder = placeholder;
  input.autocomplete = "off";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${id}-lb`);
  input.setAttribute("aria-autocomplete", "list");
  const list = document.createElement("ul");
  list.id = `${id}-lb`;
  list.setAttribute("role", "listbox");
  list.hidden = true;
  wrap.append(lab, input, list);
  container.appendChild(wrap);

  const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  let matches = [];
  let active = -1;

  function open(q) {
    const n = norm(q);
    matches = n ? items.filter((it) => norm(it.name).includes(n))
      .sort((a, b) => norm(a.name).indexOf(n) - norm(b.name).indexOf(n)).slice(0, max) : [];
    active = -1;
    list.replaceChildren(...matches.map((it, k) => {
      const li = document.createElement("li");
      li.id = `${id}-o${k}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.textContent = it.name;
      li.addEventListener("pointerdown", (ev) => { ev.preventDefault(); pick(k); });
      return li;
    }));
    list.hidden = !matches.length;
    input.setAttribute("aria-expanded", String(!list.hidden));
  }
  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  function setActive(k) {
    active = k;
    [...list.children].forEach((li, j) => li.setAttribute("aria-selected", String(j === k)));
    if (k >= 0) input.setAttribute("aria-activedescendant", `${id}-o${k}`);
  }
  function pick(k) {
    const it = matches[k];
    if (!it) return;
    input.value = it.name;
    close();
    onPick(it);
  }

  input.addEventListener("input", () => open(input.value));
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); if (list.hidden) open(input.value); setActive(Math.min(matches.length - 1, active + 1)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setActive(Math.max(0, active - 1)); }
    else if (ev.key === "Enter") {
      ev.preventDefault();
      if (active >= 0) pick(active);
      else if (matches.length === 1) pick(0);
      else if (input.value.trim()) {
        const exact = items.find((it) => norm(it.name) === norm(input.value));
        if (exact) { close(); onPick(exact); } else { close(); onNoMatch && onNoMatch(input.value); }
      }
    } else if (ev.key === "Escape") { close(); }
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
  return { input, clear() { input.value = ""; close(); } };
}
