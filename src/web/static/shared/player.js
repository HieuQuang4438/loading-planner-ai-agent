// One solution on the stage: grid or one container in 3D, replay piece by piece, picking a piece from the item
// table, keys ←/→/Esc. Pages call buildScene to show a payload and closeView to drop it.
import { $, el, fmt, fmtDim } from './util.js';
import { icon } from './icons.js';
import { S } from './state.js';
import { FIT_MARGIN, autoFit, camera, controls, dispose, disposeLabelAtlas, buildContainer, fit, lineColor, marker, paint, pickMarker, resize, scene } from './scene.js';
import { mountViewNav } from './viewnav.js';
import './hover.js';
import { pumpThumbs, renderGrid, resetGrid } from './grid.js';
import { clearResultPage, loadText, postureWords, renderContainerInfo, renderLegend, supportText, swatch, tiersText, tippableWords } from './panels.js';

mountViewNav();

export function clearCurrent() {
  stopPlay();
  if (S.cur) { scene.remove(S.cur.group); dispose(S.cur.group); }
  S.cur = null;
  S.itemRows = [];
  marker.visible = false;
  setPicked(null);
}

// Highlight one piece in the 3D view without moving the replay; picking it again clears it.
export function setPicked(i) {
  S.picked = i;
  S.itemRows.forEach((r, j) => r.classList.toggle('hl', j === i));
  if (i === null || !S.cur) {
    pickMarker.visible = false;
    $('pickinfo').style.display = 'none';
    return;
  }
  const b = S.cur.order[i];
  pickMarker.visible = true;
  pickMarker.scale.set(b.l, b.h, b.w);
  pickMarker.position.set(b.x + b.l / 2, b.z + b.h / 2, S.cur.group.position.z - (b.y + b.w / 2));
  updatePickInfo();
}

export function updatePickInfo() {
  if (S.picked === null || !S.cur) return;
  const b = S.cur.order[S.picked];
  $('pickinfo').style.display = '';
  $('pickinfo').textContent = `Đang chọn (xanh lơ): #${S.picked + 1} ${b.item}, (${fmtDim(b.x)}; ${fmtDim(b.y)}; ${fmtDim(b.z)}) m, ` +
    `tải đè ${loadText(b)}, tầng ${tiersText(b)}, đỡ ${supportText(b)}` +
    (S.picked >= S.step ? ' — chưa đặt ở bước tua hiện tại' : '') + '. Bấm lại dòng đó để bỏ chọn.';
}

export function buildScene(v) {
  clearCurrent();
  disposeLabelAtlas();
  S.view = v;
  S.lineIndex = Object.fromEntries(v.lines.map((l, i) => [l.id, i]));
  S.colors = v.lines.map((l) => lineColor(l.id));
  renderLegend();
  renderGrid();
  showGrid();
}

export function showGrid() {
  clearCurrent();
  S.selected = null;
  $('stage').classList.remove('in3d');
  $('grid').style.display = '';
  $('canvas').style.visibility = 'hidden';
  $('hud').style.display = 'none';
  $('nav').style.display = 'none';
  $('bannertext').textContent = '';
  renderContainerInfo();
  pumpThumbs();
  document.dispatchEvent(new CustomEvent('viewer:select'));   // manual packing follows the shown container
}

export function select(index) {
  if (!S.view || index < 0 || index >= S.view.containers.length) return;
  clearCurrent();
  S.selected = index;
  $('stage').classList.add('in3d');
  $('grid').style.display = 'none';
  $('canvas').style.visibility = 'visible';
  S.cur = buildContainer(S.view.containers[index], true, true);
  paint(S.cur);
  scene.add(S.cur.group);
  const c = S.cur;
  $('hud').style.display = '';
  $('nav').style.display = S.view.containers.length > 1 ? '' : 'none';   // one container: nothing to step through
  $('navpos').textContent = `${index + 1}/${S.view.containers.length}`;
  $('prevc').disabled = index === 0;
  $('nextc').disabled = index === S.view.containers.length - 1;
  $('slider').max = c.count;
  const rebuilt = c.data.replay_source !== 'engine';
  $('ordernote').textContent = rebuilt
    ? 'Thứ tự dựng lại, không phải của bộ giải (z, rồi x, rồi y tăng dần; thứ tự của bộ giải có kiện đứng trước kiện đỡ nó).'
    : 'Thứ tự bộ giải đặt kiện, không phải thứ tự bốc xếp.';
  $('ordernote').className = rebuilt ? 'warn' : 'muted';
  $('bannertext').textContent = '';
  renderContainerInfo();   // shows the item drawer, a card under the scene
  resize();
  fit(camera, c.pick, controls, FIT_MARGIN);   // the replay bar is under the scene, not over it
  autoFit.dir = undefined;
  autoFit.on = true;   // keep it framed while the layout settles (panel, replay bar), until the user moves the camera
  goTo(c.count);
  document.dispatchEvent(new CustomEvent('viewer:select'));
}

function setCount(c, n) {
  c.mesh.count = n;
  c.edges.geometry.setDrawRange(0, n * 24);
  if (c.labels) c.labels.count = n * 5;
}

export function goTo(n) {
  if (!S.cur) return;
  const c = S.cur;
  S.step = Math.max(0, Math.min(c.count, n));
  setCount(c, S.step);
  $('slider').value = S.step;
  $('slider').style.setProperty('--p', `${c.count ? (S.step / c.count) * 100 : 0}%`);   // the filled part of the track
  S.itemRows.forEach((r, i) => r.classList.toggle('cur', i === S.step - 1));
  updatePickInfo();
  document.dispatchEvent(new CustomEvent('viewer:step'));   // the piece tooltip looks again under the pointer
  if (S.step === 0) {
    marker.visible = false;
    $('stepinfo').replaceChildren(el('span', { class: 'lead' }, `Kiện 0 / ${c.count}`), 'Container trống. Bấm Phát hoặc ▸ để tua lại từng kiện.');
    return;
  }
  const b = c.order[S.step - 1];
  marker.visible = true;
  marker.scale.set(b.l, b.h, b.w);
  marker.position.set(b.x + b.l / 2, b.z + b.h / 2, c.group.position.z - (b.y + b.w / 2));
  $('stepinfo').replaceChildren(...stepLabels(b, S.step, c.count));
}

// The label of a replay step: the piece, its posture, position and its real values next to the limits of its type.
function stepLabels(b, step, count) {
  const chip = (...kids) => el('span', { class: 'chip' }, ...kids);
  return [
    el('span', { class: 'lead' }, `Kiện ${step} / ${count}`),
    chip(swatch(b.line), b.item),
    chip(`${postureWords(b)} `, el('span', { class: 'muted' }, `· ${tippableWords(b)}`), ` · cao ${fmtDim(b.h)} m`),
    chip(`x ${fmtDim(b.x)} · y ${fmtDim(b.y)} · z ${fmtDim(b.z)} m`),
    chip(`kích thước ${fmtDim(b.l)} × ${fmtDim(b.w)} × ${fmtDim(b.h)} m`),
    chip(loadText(b) === 'không chồng' ? 'không chồng' : `tải đè ${loadText(b)} kg`),
    chip(tiersText(b) === 'chỉ sàn' ? 'chỉ sàn' : `tầng ${tiersText(b)}`),
    chip(b.supported === null && b.stack !== null ? 'trên sàn' : `đỡ ${supportText(b)}`),
  ];
}
$('colorby').onchange = () => { if (S.cur) paint(S.cur); };
$('showlabels').onchange = () => { if (S.cur?.labels) S.cur.labels.visible = $('showlabels').checked; };

export function stopPlay() {
  if (S.playTimer) clearInterval(S.playTimer);
  S.playTimer = null;
  setPlayLabel(false);
}
function setPlayLabel(playing) {
  $('play').replaceChildren(icon(playing ? 'pause' : 'play'), playing ? 'Dừng phát' : 'Phát');
}
function togglePlay() {
  if (S.playTimer) return stopPlay();
  const c = S.cur;
  if (S.step >= c.count) goTo(0);
  setPlayLabel(true);
  S.playTimer = setInterval(() => {
    if (S.step >= c.count) return stopPlay();
    goTo(S.step + 1);
  }, Number($('speed').value));
}

$('play').onclick = togglePlay;
$('next').onclick = () => { stopPlay(); goTo(S.step + 1); };
$('prev').onclick = () => { stopPlay(); goTo(S.step - 1); };
$('first').onclick = () => { stopPlay(); goTo(0); };
$('last').onclick = () => { stopPlay(); goTo(S.cur.count); };
$('slider').oninput = () => { stopPlay(); goTo(Number($('slider').value)); };
$('speed').onchange = () => { if (S.playTimer) { stopPlay(); togglePlay(); } };
$('back').onclick = showGrid;
$('prevc').onclick = () => select(S.selected - 1);
$('nextc').onclick = () => select(S.selected + 1);

// ←/→ move between containers, Esc goes back to the grid. Text fields and selects keep their keys; the replay
// slider does not (it would otherwise swallow ←/→ after one drag).
document.addEventListener('keydown', (e) => {
  if (S.selected === null || e.altKey || e.ctrlKey || e.metaKey) return;
  if (document.querySelector('dialog[open]')) return;   // a dialog ("Cả lô", a confirmation) keeps its own Esc
  const t = e.target;
  if (t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || (t.tagName === 'INPUT' && t.type !== 'range')) return;
  if (e.key === 'Escape') showGrid();
  else if (e.key === 'ArrowLeft') select(S.selected - 1);
  else if (e.key === 'ArrowRight') select(S.selected + 1);
  else return;
  e.preventDefault();
});

// Drop the scene and results; the lock (`source`) is not touched.
export function closeView() {
  S.selected = null;
  clearCurrent();
  resetGrid();
  clearResultPage();
  $('stage').classList.remove('in3d');
  $('grid').style.display = '';
  $('canvas').style.visibility = 'hidden';
  $('hud').style.display = 'none';
  $('nav').style.display = 'none';
  S.view = null;
  disposeLabelAtlas();
  S.drawerOpen = false;
  $('bannertext').textContent = '';
  $('result').className = 'muted'; $('result').replaceChildren('Chưa có.');
  $('legend').className = 'muted'; $('legend').replaceChildren('Chưa có.');
  renderContainerInfo();
}
