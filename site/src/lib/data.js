// Load the aggregated chart data from public/data (works under the GitHub Pages base path).
const cache = new Map();

export function loadData(name) {
  if (!cache.has(name)) {
    const url = `${import.meta.env.BASE_URL}data/${name}`;
    cache.set(name, fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(name);
}
