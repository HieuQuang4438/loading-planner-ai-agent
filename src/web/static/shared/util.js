// Small DOM and number helpers shared by every page.

export const $ = (id) => document.getElementById(id);

// Numbers on screen (ui.md §2): decimal comma, a narrow no-break space between thousands (from four integer digits).
export const THIN_SPACE = String.fromCharCode(0x202f);
export const fmt = (x, d = 3) => {
  if (x === null || x === undefined) return '—';
  const [int, frac] = Number(x).toFixed(d).split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN_SPACE);
  return frac === undefined ? grouped : `${grouped},${frac}`;
};
// A number as typed (no fixed digits): 0.05 -> "0,05", 28000 -> "28 000".
export const num = (x) => {
  if (x === null || x === undefined) return '—';
  const [int, frac] = String(Number(x)).split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN_SPACE);
  return frac === undefined ? grouped : `${grouped},${frac}`;
};
// One quantity, one rounding on every screen: sizes 0,70 m (2 decimals), a mass of one piece or a load 285,0 kg (1 decimal),
// a ratio to the lower bound × 2,00 (2 decimals). A non-number gives "—" (fmt) or is shown as typed by the caller.
export const fmtDim = (x) => fmt(x, 2);
export const fmtKg = (x) => fmt(x, 1);
export const fmtRatio = (x) => fmt(x, 2);
export const pct = (r) => (r === null || r === undefined ? '—' : `${fmt(r * 100, 1)}%`);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') node.className = v;
    else if (k === 'style') node.style.cssText = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (k.includes('-')) node.setAttribute(k, v);   // aria-*, data-*: a property of that name would do nothing
    else node[k] = v;
  }
  for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

// localStorage, which may be blocked: reads fall back to null, writes are dropped.
export const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, String(v)); } catch { /* storage may be blocked */ } },
};

// Saves `text` as a file named `filename` through the browser's download.
export function download(filename, text, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = el('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
