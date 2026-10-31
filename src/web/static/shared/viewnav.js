// Orientation block over the bottom right of the 3D scene: a small 3D cube that turns with the camera (its own
// canvas and renderer), six labelled faces that fly the camera to that side when clicked, a "Góc mặc định" button and
// the "Ẩn vách" switch (hides the floor and the two far walls, keeps the frame). Used by the one-container screen and
// the manual packing scene, which share the viewer. No piece dragging here: the cube only moves the camera.
// Axes (repo x from the closed end to the door, y width, z up; three.js X = x, Y = z, Z = -y): +X is the door, -X the
// closed end, +Y the top, -Y the underside, +Z the left side seen from the door looking in, -Z the right side.
import * as THREE from 'three';
import { $, el } from './util.js';
import { icon } from './icons.js';
import { S } from './state.js';
import { FIT_MARGIN, VIEWS, autoFit, camera, controls, fit, flyTo, frameHooks, skin } from './scene.js';

// In the order of the faces of a three.js BoxGeometry: +X, -X, +Y, -Y, +Z, -Z.
const FACES = [
  { view: 'door', lines: ['CỬA'], label: 'Nhìn từ cửa' },
  { view: 'end', lines: ['ĐẦU', 'KÍN'], label: 'Nhìn từ đầu kín, đáy trong của container' },
  { view: 'top', lines: ['TRÊN'], label: 'Nhìn từ trên' },
  { view: 'bottom', lines: ['ĐÁY'], label: 'Nhìn từ dưới sàn' },
  { view: 'left', lines: ['CẠNH', 'TRÁI'], label: 'Nhìn từ cạnh trái, khi đứng ở cửa nhìn vào' },
  { view: 'right', lines: ['CẠNH', 'PHẢI'], label: 'Nhìn từ cạnh phải, khi đứng ở cửa nhìn vào' },
];
const SIZE = 120;   // CSS px of the cube canvas
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function faceTexture(face) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = face.view === 'door' ? css('--gold-soft') : face.view === 'top' ? css('--surface') : css('--sunken');
  g.fillRect(0, 0, 128, 128);
  g.strokeStyle = face.view === 'door' ? css('--gold') : css('--line2');
  g.lineWidth = 6;
  g.strokeRect(3, 3, 122, 122);
  g.fillStyle = css('--ink2');
  g.font = `700 ${face.lines.length > 1 ? 30 : 34}px ${css('--font')}`;
  g.textAlign = 'center'; g.textBaseline = 'middle';
  face.lines.forEach((t, i) => g.fillText(t, 64, 64 + (i - (face.lines.length - 1) / 2) * 34));
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

export function mountViewNav() {
  const canvas = el('canvas', { class: 'vcube', width: SIZE, height: SIZE, 'aria-hidden': 'true' });
  const names = el('div', { class: 'sr-only', role: 'group', 'aria-label': 'Khối định hướng: chọn một mặt để xoay camera' },
    ...FACES.map((f) => el('button', { type: 'button', 'data-view': f.view, 'aria-pressed': 'false', 'aria-label': f.label })));
  const home = el('button', { type: 'button', class: 'sm', id: 'vhome', title: 'Về góc nhìn mặc định' }, icon('house'), 'Góc mặc định');
  const walls = el('button', { type: 'button', class: 'sm', id: 'vwalls', 'aria-pressed': 'false', title: 'Ẩn hoặc hiện sàn và hai vách xa; khung vẫn còn' });
  const box = el('div', { class: 'vtools', id: 'vtools' }, canvas, names, el('div', { class: 'vbtns' }, home, walls));
  $('viewport').append(box);

  // the cube: one canvas texture per face, its own renderer, turned by the main camera's rotation every frame
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.setSize(SIZE, SIZE, false);
  const scene = new THREE.Scene();
  const mats = FACES.map((f) => new THREE.MeshBasicMaterial({ map: faceTexture(f) }));
  const cube = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mats);
  cube.add(new THREE.LineSegments(new THREE.EdgesGeometry(cube.geometry), new THREE.LineBasicMaterial({ color: new THREE.Color(css('--line2')) })));
  scene.add(cube);
  const view = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
  const TINT = { hover: new THREE.Color(0xbfd4ff), on: new THREE.Color(0xdbe7ff), none: new THREE.Color(0xffffff) };
  let hover = -1, current = -1;
  const tint = () => mats.forEach((m, i) => m.color.copy(i === hover ? TINT.hover : i === current ? TINT.on : TINT.none));
  frameHooks.push(() => {
    view.quaternion.copy(camera.quaternion);
    view.position.set(0, 0, 3.4).applyQuaternion(camera.quaternion);
    renderer.render(scene, view);
  });

  const buttons = [...names.querySelectorAll('button')];
  const mark = (name) => {
    current = FACES.findIndex((f) => f.view === name);
    buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(i === current)));
    tint();
  };
  const go = (name) => {
    if (!S.cur) return;
    autoFit.dir = VIEWS[name];
    autoFit.on = true;   // a window or panel resize re-frames from the same side until the user orbits
    // the pose is worked out on a spare camera, then the real one flies there
    const spare = camera.clone(), goal = { target: new THREE.Vector3() };
    fit(spare, S.cur.pick, goal, FIT_MARGIN, VIEWS[name]);
    flyTo(spare.position, goal.target);
    mark(name === 'home' ? null : name);
  };

  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const faceAt = (e) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, view);
    cube.updateMatrixWorld();
    return ray.intersectObject(cube, false)[0]?.face?.materialIndex ?? -1;
  };
  canvas.addEventListener('pointermove', (e) => { hover = faceAt(e); canvas.style.cursor = hover >= 0 ? 'pointer' : ''; tint(); });
  canvas.addEventListener('pointerleave', () => { hover = -1; tint(); });
  canvas.addEventListener('click', (e) => { const i = faceAt(e); if (i >= 0) go(FACES[i].view); });
  buttons.forEach((b, i) => {
    b.addEventListener('click', () => go(b.dataset.view));
    b.addEventListener('focus', () => { hover = i; tint(); });
    b.addEventListener('blur', () => { hover = -1; tint(); });
  });

  const drawWalls = () => {
    walls.replaceChildren(icon(skin.walls ? 'eye-off' : 'eye'), skin.walls ? 'Ẩn vách' : 'Hiện vách');
    walls.setAttribute('aria-pressed', String(!skin.walls));
    if (S.cur?.walls) S.cur.walls.visible = skin.walls;
  };
  home.addEventListener('click', () => go('home'));
  walls.addEventListener('click', () => { skin.walls = !skin.walls; drawWalls(); });
  controls.addEventListener('start', () => mark(null));
  document.addEventListener('viewer:select', () => { mark(null); drawWalls(); });
  drawWalls();
}
