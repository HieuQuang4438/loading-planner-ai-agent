// Tooltip over a piece: resting the pointer on a piece shows its type id, its place in the replay order and its
// size, and lights the piece up. Only the pieces shown at the current replay step can be hit (an InstancedMesh raycast
// stops at `count`). One raycast per animation frame at most; nothing is drawn while a button is held (an orbit), so it
// never gets in the way of dragging. The light-up is a temporary instance colour: `paint` puts every colour back.
import * as THREE from 'three';
import { $, el, fmtDim } from './util.js';
import { S } from './state.js';
import { camera, canvas, paint } from './scene.js';
import { swatch } from './panels.js';

const tip = el('div', { id: 'piecetip', role: 'tooltip', hidden: true });
$('viewport').append(tip);
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), tmp = new THREE.Color();
let at = null, frame = 0, shown = -1;

function clear() {
  if (shown >= 0 && S.cur) paint(S.cur);   // paint sets every instance colour again
  shown = -1;
  tip.hidden = true;
}

function probe() {
  frame = 0;
  const c = S.cur;
  if (!at || !c || at.pressed) return clear();
  const r = canvas.getBoundingClientRect();
  ndc.set(((at.x - r.left) / r.width) * 2 - 1, -((at.y - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObject(c.mesh, false)[0];
  const i = hit?.instanceId ?? -1;
  if (i < 0 || i >= c.count) return clear();
  if (i !== shown) {
    if (shown >= 0) paint(c);
    c.mesh.getColorAt(i, tmp);
    c.mesh.setColorAt(i, tmp.lerp(new THREE.Color(0xffffff), 0.4));
    c.mesh.instanceColor.needsUpdate = true;
    shown = i;
    const b = c.order[i];
    tip.replaceChildren(
      el('b', {}, swatch(b.line), b.line),
      el('span', { class: 'muted' }, ` · kiện ${i + 1} / ${c.count}`),
      el('div', {}, `${fmtDim(b.l)} × ${fmtDim(b.w)} × ${fmtDim(b.h)} m`));
  }
  tip.hidden = false;
  const vp = $('viewport').getBoundingClientRect();
  const x = Math.min(at.x - vp.left + 14, vp.width - tip.offsetWidth - 8), y = Math.min(at.y - vp.top + 16, vp.height - tip.offsetHeight - 8);
  tip.style.transform = `translate(${Math.max(8, x)}px, ${Math.max(8, y)}px)`;
}

const schedule = () => { if (!frame) frame = requestAnimationFrame(probe); };
canvas.addEventListener('pointermove', (e) => { at = { x: e.clientX, y: e.clientY, pressed: e.buttons !== 0 }; schedule(); });
canvas.addEventListener('pointerleave', () => { at = null; schedule(); });
canvas.addEventListener('pointerdown', () => { if (at) at.pressed = true; schedule(); });
document.addEventListener('viewer:select', () => { shown = -1; tip.hidden = true; });
// A replay step changes which pieces are shown: drop the light-up and look again under a pointer that has not moved.
document.addEventListener('viewer:step', () => { if (shown >= 0 && S.cur) paint(S.cur); shown = -1; schedule(); });
