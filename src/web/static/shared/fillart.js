// Decoration of the solving screen (P6): a small isometric container in which a handful of boxes drop in one after
// the other, then the cycle repeats. Purely decorative and NOT progress: the solver reports no per-piece progress, so
// the picture says "working", never "x of y placed". Pure string output, no DOM, so `node` can test it.
const C = Math.cos(Math.PI / 6), S = Math.sin(Math.PI / 6);
const K = 16, L = 6.0, W = 2.35, H = 2.4, OX = 4, OY = 4;   // pixels per metre and the container, in metres
// x, y, z, dx, dy, dz, tone (a-d)
export const FILL_BOXES = [
  [0, 0, 0, 1.2, 1.1, 1.0, 'a'], [0, 1.15, 0, 1.2, 1.15, 1.0, 'b'], [0, 0, 1.0, 1.2, 1.1, 0.9, 'b'], [0, 1.15, 1.0, 1.2, 1.15, 0.9, 'a'],
  [1.25, 0, 0, 1.5, 1.1, 0.8, 'c'], [1.25, 1.15, 0, 1.5, 1.15, 0.8, 'a'], [1.25, 0, 0.8, 1.5, 1.1, 0.8, 'a'], [1.25, 1.15, 0.8, 1.5, 1.15, 0.8, 'c'],
  [2.8, 0, 0, 1.0, 2.3, 0.6, 'd'], [2.8, 0, 0.6, 1.0, 1.1, 0.7, 'b'], [3.85, 0, 0, 0.9, 1.1, 1.1, 'b'],
];

const p = (x, y, z) => [OX + (x - y) * C * K + W * C * K, OY + (x + y) * S * K - z * K + H * K];
const poly = (pts, cls) => `<polygon class="${cls}" points="${pts.map((q) => p(...q).map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
const line = (a, b, cls) => { const [x1, y1] = p(...a), [x2, y2] = p(...b); return `<line class="${cls}" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`; };

export function fillArtSvg() {
  const out = [poly([[0, 0, 0], [L, 0, 0], [L, W, 0], [0, W, 0]], 'c-floor'), poly([[0, 0, 0], [0, W, 0], [0, W, H], [0, 0, H]], 'c-wall'),
               poly([[0, 0, 0], [L, 0, 0], [L, 0, H], [0, 0, H]], 'c-wall2')];
  for (let i = 1; i < 12; i++) out.push(line([L * i / 12, 0, 0.08], [L * i / 12, 0, H - 0.08], 'c-rib'));
  [...FILL_BOXES].sort((a, b) => (a[0] + a[1] + a[2]) - (b[0] + b[1] + b[2])).forEach(([x, y, z, dx, dy, dz, t], i) => {
    const X = x + dx, Y = y + dy, Z = z + dz;
    out.push(`<g class="bx ${t}" style="--i:${i}">`, poly([[x, y, Z], [X, y, Z], [X, Y, Z], [x, Y, Z]], 't'),
             poly([[X, y, z], [X, Y, z], [X, Y, Z], [X, y, Z]], 'f'), poly([[x, Y, z], [X, Y, z], [X, Y, Z], [x, Y, Z]], 's'), '</g>');
  });
  for (const [a, b] of [[[0, W, 0], [L, W, 0]], [[L, 0, 0], [L, W, 0]], [[0, W, H], [L, W, H]], [[L, 0, H], [L, W, H]], [[0, 0, H], [L, 0, H]],
                        [[0, 0, H], [0, W, H]], [[L, 0, 0], [L, 0, H]], [[L, W, 0], [L, W, H]], [[0, W, 0], [0, W, H]]]) out.push(line(a, b, 'c-edge'));
  const pts = [0, L].flatMap((x) => [0, W].flatMap((y) => [0, H].map((z) => p(x, y, z))));
  const vb = `0 0 ${Math.round(Math.max(...pts.map((q) => q[0])) + 4)} ${Math.round(Math.max(...pts.map((q) => q[1])) + 4)}`;
  return `<svg class="fillart" viewBox="${vb}" aria-hidden="true" focusable="false">${out.join('')}</svg>`;
}
