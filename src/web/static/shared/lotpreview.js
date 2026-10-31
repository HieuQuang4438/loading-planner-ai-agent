// The box of one loại kiện as an isometric SVG in proportion to L × W × H (step 4): colour from the id through
// linecolor.js (the colour of the result screens), red stripes on the top for "không chồng", a brown band at the foot for
// "chỉ nằm sàn". Pure strings, no WebGL: a list of 1 000 loại kiện is 1 000 small SVGs, no GPU contexts. The stripes are
// one shared pattern, `HATCH_DEFS`, which the page puts in the document once.
import { lineHue, lineLightness, LINE_SATURATION } from './linecolor.js';
import { escapeHtml } from './lotrules.js';

export const HATCH_ID = 'lf-hatch';
export const HATCH_DEFS = `<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
<pattern id="${HATCH_ID}" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="8" fill="#b91c1c" fill-opacity=".65"/></pattern></defs></svg>`;

const C = 0.866, S = 0.5;
const P = (x, y, z) => [(x - y) * C, (x + y) * S - z];

// hsl() of the line's colour with the lightness moved by `delta` points; no id: a neutral grey.
function shade(id, delta) {
  if (id === undefined || id === null || String(id) === '') return `hsl(215 12% ${55 + delta}%)`;
  return `hsl(${Math.round(lineHue(id) * 360)} ${Math.round(LINE_SATURATION * 100)}% ${Math.round(lineLightness(id) * 100) + delta}%)`;
}

// boxSvg({L, W, H}, id, { w, h, label, noStack, floorOnly }) -> '<svg …>…</svg>'. `dims` not all positive numbers: ''.
// `label`: the id written on the three visible faces (the big preview of the edit dialog).
export function boxSvg(dims, id, { w = 56, h = 44, label = false, noStack = false, floorOnly = false } = {}) {
  const { L, W, H } = dims ?? {};
  if (![L, W, H].every((x) => typeof x === 'number' && Number.isFinite(x) && x > 0)) return '';
  const pts = [P(0, 0, 0), P(L, 0, 0), P(L, W, 0), P(0, W, 0), P(0, 0, H), P(L, 0, H), P(L, W, H), P(0, W, H)];
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  const pad = label ? 18 : 3;
  const k = Math.min((w - 2 * pad) / (Math.max(...xs) - Math.min(...xs)), (h - 2 * pad) / (Math.max(...ys) - Math.min(...ys)));
  const ox = (w - (Math.max(...xs) + Math.min(...xs)) * k) / 2, oy = (h - (Math.max(...ys) + Math.min(...ys)) * k) / 2;
  const T = ([u, v]) => [u * k + ox, v * k + oy];
  const stroke = label ? 1.4 : 0.8;
  const poly = (ps, fill, extra = '') =>
    `<polygon points="${ps.map((q) => T(q).map((n) => n.toFixed(1)).join(',')).join(' ')}" fill="${fill}" ${extra}stroke="#0f172a" stroke-opacity=".55" stroke-width="${stroke}" stroke-linejoin="round"/>`;
  const top = [P(0, 0, H), P(L, 0, H), P(L, W, H), P(0, W, H)];
  const front = [P(0, W, 0), P(L, W, 0), P(L, W, H), P(0, W, H)];
  const side = [P(L, 0, 0), P(L, W, 0), P(L, W, H), P(L, 0, H)];
  let out = `<svg class="lfbox" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">`
    + poly(front, shade(id, 3)) + poly(side, shade(id, -8)) + poly(top, shade(id, 12));
  if (noStack) out += poly(top, `url(#${HATCH_ID})`);
  if (floorOnly) {   // a dark band at the foot of the two visible sides
    const band = Math.min(H * 0.14, 0.12);
    out += poly([P(0, W, 0), P(L, W, 0), P(L, W, band), P(0, W, band)], '#4a2c0a', 'fill-opacity=".55" ');
    out += poly([P(L, 0, 0), P(L, W, 0), P(L, W, band), P(L, 0, band)], '#4a2c0a', 'fill-opacity=".55" ');
  }
  const text = id === undefined || id === null ? '' : String(id);
  if (label && text) {
    // text laid on a face: ax, ay are the screen directions of the face's two axes, len1 / len2 its sides in metres
    const face = (o, ax, ay, len1, len2) => {
      const [cx, cy] = T(o);
      const fs = Math.max(10, Math.min(len1 * 0.9 / Math.max(1, text.length * 0.62), len2 * 0.7) * k);
      return `<text transform="matrix(${ax[0]},${ax[1]},${ay[0]},${ay[1]},${cx.toFixed(1)},${cy.toFixed(1)})" font-size="${fs.toFixed(1)}" font-weight="800" text-anchor="middle" dominant-baseline="central" fill="#0f172a" fill-opacity=".75">${escapeHtml(text)}</text>`;
    };
    out += face(P(L / 2, W, H / 2), [C, S], [0, 1], L, H);
    out += face(P(L, W / 2, H / 2), [C, -S], [0, 1], W, H);
    out += face(P(L / 2, W / 2, H), [C, S], [-C, S], L, W);
  }
  return `${out}</svg>`;
}
