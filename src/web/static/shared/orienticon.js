// Mini oblique box of a placed piece (front, top and +x faces visible) with the item's own H-normal face (its
// original top) filled: the axis of `b.o` that holds H says which of the three faces that is. Used by the viewer's
// item drawer and the lot form's posture preview. b = {l, w, h, o}: sizes along x, y, z and the code.
const SVG_NS = 'http://www.w3.org/2000/svg';
export function orientIcon(b) {
  const S = 24, k = 0.45 * 0.7;
  const px = (x, y, z) => [x + k * y, -z - k * y];   // oblique projection, screen y down
  const pts = [[0, 0, 0], [b.l, 0, 0], [b.l, b.w, 0], [0, b.w, 0], [0, 0, b.h], [b.l, 0, b.h], [b.l, b.w, b.h], [0, b.w, b.h]].map((p) => px(...p));
  const minX = Math.min(...pts.map((p) => p[0])), maxX = Math.max(...pts.map((p) => p[0]));
  const minY = Math.min(...pts.map((p) => p[1])), maxY = Math.max(...pts.map((p) => p[1]));
  const sc = (S - 2) / Math.max(maxX - minX, maxY - minY, 1e-9);
  const offX = 1 + (S - 2 - (maxX - minX) * sc) / 2, offY = 1 + (S - 2 - (maxY - minY) * sc) / 2;
  const at = (i) => `${((pts[i][0] - minX) * sc + offX).toFixed(1)},${((pts[i][1] - minY) * sc + offY).toFixed(1)}`;
  const faces = [   // vertex indices; axis = the axis a face is normal to (0 = +x face, 1 = front, 2 = top)
    { idx: [1, 2, 6, 5], axis: 0, shade: 0.55 }, { idx: [0, 1, 5, 4], axis: 1, shade: 0.8 }, { idx: [4, 5, 6, 7], axis: 2, shade: 1 }];
  const hAxis = b.o.indexOf('H');
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', S); svg.setAttribute('height', S); svg.setAttribute('viewBox', `0 0 ${S} ${S}`);
  for (const f of faces) {
    const poly = document.createElementNS(SVG_NS, 'polygon');
    poly.setAttribute('points', f.idx.map(at).join(' '));
    poly.setAttribute('fill', f.axis === hAxis ? 'var(--accent)' : `color-mix(in srgb, var(--muted) ${Math.round(f.shade * 35)}%, var(--panel))`);
    poly.setAttribute('stroke', 'var(--muted)');
    poly.setAttribute('stroke-width', '0.8');
    poly.setAttribute('stroke-linejoin', 'round');
    svg.append(poly);
  }
  return svg;
}
