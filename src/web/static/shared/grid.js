// Grid of containers: one cell per container with its numbers and a 3D thumbnail drawn with the stage
// renderer, only once the cell scrolls into view, one per animation frame.
import * as THREE from 'three';
import { $, el, fmt, pct } from './util.js';
import { S } from './state.js';
import { FOV, buildContainer, dispose, fit, lineColor, lit, renderer } from './scene.js';
import { select } from './player.js';
import { swatch } from './panels.js';

const THUMB_W = 520, THUMB_H = 200;   // about the shape of a 40 ft container seen from a corner
const thumbScene = lit(new THREE.Scene());
const thumbCamera = new THREE.PerspectiveCamera(FOV, THUMB_W / THUMB_H, 0.1, 2000);
let thumbQueue = [], thumbBusy = false, thumbObserver = null, cells = [];

// Draw one container into its cell's 2D canvas with the shared renderer (one WebGL context for the page).
function drawThumb(index) {
  const cell = cells[index];
  if (!cell || cell.drawn) return;
  const c = buildContainer(S.view.containers[index], false);
  thumbScene.add(c.group);
  fit(thumbCamera, c.pick);
  renderer.setSize(THUMB_W, THUMB_H, false);
  renderer.render(thumbScene, thumbCamera);
  cell.canvas.getContext('2d').drawImage(renderer.domElement, 0, 0, cell.canvas.width, cell.canvas.height);
  thumbScene.remove(c.group);
  dispose(c.group);
  cell.drawn = true;
}

// One thumbnail per animation frame, so scrolling a big fleet does not stall the page.
export function pumpThumbs() {
  if (thumbBusy) return;
  thumbBusy = true;
  requestAnimationFrame(function next() {
    if (S.selected !== null || !thumbQueue.length) { thumbBusy = false; return; }
    drawThumb(thumbQueue.shift());
    requestAnimationFrame(next);
  });
}

export function renderGrid() {
  thumbObserver?.disconnect();
  thumbQueue = [];
  const dpr = window.devicePixelRatio || 1;
  cells = S.view.containers.map((d, i) => {
    const cv = el('canvas', { width: Math.round(THUMB_W * dpr), height: Math.round(THUMB_H * dpr) });
    const row = (label, ratio, text, bad) => el('div', { class: 'mrow' }, el('span', {}, label),
      el('div', { class: `bar${ratio > 1 ? ' over' : ''}` }, el('div', { style: `width:${Math.max(0, Math.min(1, ratio ?? 0)) * 100}%` })),
      el('span', { class: `num ${bad ? 'bad' : ''}` }, text));
    const node = el('div', { class: 'cell', tabIndex: 0, role: 'button', onclick: () => select(i), title: 'Xem 3D và tua lại' },
      cv,
      el('div', { class: 'cellbody' },
        el('div', { class: 'cellhead' }, el('b', {}, `#${d.k} ${d.type}`),
           d.replay_source === 'engine' ? '' : el('span', { class: 'warn' }, 'dựng lại'),
           el('span', { class: 'muted' }, `${d.replay.length} kiện`), el('span', { class: 'spacer' }),
           d.cost === null ? '' : el('span', { class: 'cellcost' }, 'cước ', el('strong', {}, fmt(d.cost, 2)))),
        row('Thể tích', d.volume_ratio, pct(d.volume_ratio)),
        row('Khối lượng', d.mass_ratio, `${fmt(d.mass, 0)} / ${fmt(d.max_mass, 0)} kg`, d.mass_ratio > 1),
        el('div', { class: 'chips' }, d.lines.map((l) => el('span', { class: 'chip' }, swatch(l.id), `${l.id} × ${l.qty}`)))));
    node.dataset.index = i;
    return { node, canvas: cv, drawn: false };
  });
  $('grid').replaceChildren(...cells.map((c) => c.node));
  thumbObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const i = Number(e.target.dataset.index);
      if (e.isIntersecting && !cells[i].drawn && !thumbQueue.includes(i)) thumbQueue.push(i);
    }
    pumpThumbs();
  }, { root: $('resview'), rootMargin: '200px' });
  cells.forEach((c) => thumbObserver.observe(c.node));
}

// The thumbnail of container `index` of `view` into `canvas`, for a page that draws its own cards (the planner's result
// and compare screens): the same picture as a grid cell, `view` set as the shown solution only while it is drawn.
export function drawThumbInto(canvas, view, index) {
  const keep = [S.view, S.lineIndex, S.colors];
  S.view = view;
  S.lineIndex = Object.fromEntries(view.lines.map((l, i) => [l.id, i]));
  S.colors = view.lines.map((l) => lineColor(l.id));
  try {
    const c = buildContainer(view.containers[index], false);
    thumbScene.add(c.group);
    fit(thumbCamera, c.pick);
    renderer.setSize(THUMB_W, THUMB_H, false);
    renderer.render(thumbScene, thumbCamera);
    canvas.getContext('2d').drawImage(renderer.domElement, 0, 0, canvas.width, canvas.height);
    thumbScene.remove(c.group);
    dispose(c.group);
  } finally {
    [S.view, S.lineIndex, S.colors] = keep;
  }
}
export const THUMB_SIZE = [THUMB_W, THUMB_H];

// Forget the grid of the closed solution.
export function resetGrid() {
  thumbObserver?.disconnect();
  thumbQueue = []; cells = [];
  $('grid').replaceChildren();
}
