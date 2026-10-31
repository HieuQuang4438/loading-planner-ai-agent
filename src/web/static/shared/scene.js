// three.js side of the viewer: the stage renderer and scene, one container as instanced boxes with edges, door,
// face labels, colour modes, camera fit. Repo axes (x length to the door, y width, z up) map to
// three.js X = x, Y = z, Z = -y.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { $ } from './util.js';
import { S } from './state.js';
import { LINE_SATURATION, lineHue, lineLightness } from './linecolor.js';
import { groundGrid } from './groundgrid.js';

export const canvas = $('canvas');
export const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
const background = new THREE.Color(getComputedStyle(document.body).backgroundColor);
export function lit(scene) {
  scene.background = background;
  scene.add(new THREE.AmbientLight(0xffffff, 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.3);
  sun.position.set(15, 30, 4);
  scene.add(sun);
  return scene;
}
export const scene = lit(new THREE.Scene());
scene.background = new THREE.Color(0xffffff);   // the stage scene is white, with the ground grid
// Narrow perspective (about 28 degrees): near-parallel edges, a container that reads as an object rather than a corridor.
export const FOV = 28;
export const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 2000);
camera.position.set(20, 20, 30);
export const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
export const marker = new THREE.LineSegments(
  new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
  new THREE.LineBasicMaterial({ color: 0xff7a00 }));
marker.visible = false;
scene.add(marker);
// The piece picked in the item table: drawn through other boxes so it shows wherever it sits.
export const pickMarker = new THREE.Group();
pickMarker.add(
  new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshBasicMaterial({ color: 0x00b8d4, transparent: true, opacity: 0.45, depthTest: false })),
  new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
    new THREE.LineBasicMaterial({ color: 0x00e5ff, depthTest: false })));
pickMarker.renderOrder = 10;
pickMarker.children.forEach((o) => { o.renderOrder = 10; });
pickMarker.visible = false;
scene.add(pickMarker);

export function resize() {
  const r = canvas.getBoundingClientRect();
  if (!r.width || !r.height) return;
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
}
// After a layout change (side panel, replay bar, window) the container is framed again, until the user moves the camera.
export const FIT_MARGIN = 0.92;
export const autoFit = { on: false, dir: undefined };   // dir: the view direction kept while re-framing (viewnav.js)
export const skin = { walls: true };   // the "Ẩn vách" switch, kept from one container to the next
controls.addEventListener('start', () => { autoFit.on = false; fly = null; });   // a drag or the wheel cancels a flight

// Camera flight: the camera moves to another pose in about 0.9 s, ease-in-out. The direction from the target turns
// along the shortest arc, the distance and the target are interpolated, so the camera never cuts through the container.
// prefers-reduced-motion: the pose is taken at once.
const FLY_MS = 900;
let fly = null;
export const isFlying = () => fly !== null;
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
function placeCamera(position, target, dist) {
  camera.position.copy(position);
  controls.target.copy(target);
  camera.lookAt(target);
  camera.near = dist / 100;
  camera.far = dist * 10;
  camera.updateProjectionMatrix();
}
export function flyTo(position, target) {
  const dist1 = position.distanceTo(target);
  if (reducedMotion()) { fly = null; placeCamera(position, target, dist1); return; }
  const from = controls.target.clone(), dist0 = camera.position.distanceTo(from);
  const dir0 = camera.position.clone().sub(from).normalize(), dir1 = position.clone().sub(target).normalize();
  fly = { t0: performance.now(), from, to: target.clone(), dist0, dist1, dir0, turn: new THREE.Quaternion().setFromUnitVectors(dir0, dir1) };
}
function stepFly(now) {
  if (!fly) return;
  const k = Math.min(1, (now - fly.t0) / FLY_MS), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  const target = fly.from.clone().lerp(fly.to, e), dist = fly.dist0 + (fly.dist1 - fly.dist0) * e;
  const dir = fly.dir0.clone().applyQuaternion(new THREE.Quaternion().slerpQuaternions(new THREE.Quaternion(), fly.turn, e));
  placeCamera(target.clone().addScaledVector(dir, dist), target, dist);
  if (k >= 1) fly = null;
}
new ResizeObserver(() => {
  if (S.selected === null) return;
  resize();
  if (autoFit.on && S.cur) fit(camera, S.cur.pick, controls, FIT_MARGIN, autoFit.dir);
}).observe($('viewport'));
export const frameHooks = [];   // called after each frame of the stage scene (the orientation cube turns with the camera)
(function loop() {
  requestAnimationFrame(loop);
  if (S.selected === null) return;   // the grid shows still thumbnails; the 3D canvas is hidden
  stepFly(performance.now());
  controls.update();
  renderer.render(scene, camera);
  for (const hook of frameHooks) hook();
})();

// Colour of an item type by its id (linecolor.js): the same in every view and unaffected by the other types.
export const lineColor = (id) => new THREE.Color().setHSL(lineHue(id), LINE_SATURATION, lineLightness(id));
export const lineHex = (id) => `#${lineColor(id).getHexString()}`;

function textSprite(text, color) {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.font = 'bold 34px system-ui, sans-serif';
  g.fillStyle = color; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 128, 32);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  s.scale.set(3, 0.75, 1);
  return s;
}

// repo axes (x length to the door, y width, z up) -> three.js (X = x, Y = z, Z = -y): a rotation, no mirror
const FRAME_BLUE = 0x3b82f6, DOOR_GOLD = 0xeab308, DOOR_BAR = 0.07;
const BOX_EDGES = [[0,0,0,1,0,0],[1,0,0,1,0,1],[1,0,1,0,0,1],[0,0,1,0,0,0],[0,1,0,1,1,0],[1,1,0,1,1,1],[1,1,1,0,1,1],[0,1,1,0,1,0],
                   [0,0,0,0,1,0],[1,0,0,1,1,0],[1,0,1,1,1,1],[0,0,1,0,1,1]];

export function dispose(group) {
  group.traverse((o) => {
    o.geometry?.dispose?.();
    if (o.material?.userData?.shared) return;   // the face-label material and atlas live per view (buildScene)
    o.material?.map?.dispose?.();
    o.material?.dispose?.();
  });
}

// Constraint 7/8 use of a piece, for the colour modes: share of the limit used (load, tiers), or
// supported share of the base (support); null when there is no limit (load unlimited, base on the floor).
export function useOf(b, mode) {
  const l = S.view.lines[S.lineIndex[b.line]];
  if (!l || b.stack === null) return null;
  if (mode === 'load') return l.load === null ? null : l.load === 0 ? (b.on_top > 1e-6 ? Infinity : 1) : b.on_top / l.load;
  if (mode === 'tiers') return b.stack / l.tiers;
  return b.supported;
}

const GREY = new THREE.Color(0x9a9a9a), OVER = new THREE.Color(0xc026d3), FLAGGED = new THREE.Color(0xff0000);

function colorOf(b, mode) {
  if (S.flagged?.has(b.item)) return FLAGGED;   // a piece the checker flags in manual packing, in every colour mode
  if (mode === 'line') return S.colors[S.lineIndex[b.line]] ?? new THREE.Color(0x888888);
  const u = useOf(b, mode);
  if (u === null) return GREY;
  if (mode === 'support') {
    const a = S.view.params.alpha;
    if (u < a - 1e-9) return OVER;
    return new THREE.Color().setHSL((a >= 1 ? 1 : (u - a) / (1 - a)) / 3, 0.7, 0.5);   // red at α, green at 1
  }
  if (u > 1 + 1e-9) return OVER;
  return new THREE.Color().setHSL((1 - u) / 3, 0.7, 0.5);   // green: room left, red: at the limit
}

const COLOR_KEYS = {
  line: '',
  load: 'xanh: còn dư sức chịu · đỏ: chạm load · tím: vượt · xám: load không giới hạn',
  tiers: 'xanh: còn tầng · đỏ: chạm tiers · tím: vượt',
  support: 'xanh: đỡ 100% · đỏ: đỡ đúng α · tím: dưới α · xám: nằm trên sàn',
};

export function paint(c) {
  const mode = $('colorby').value;
  c.order.forEach((b, i) => c.mesh.setColorAt(i, colorOf(b, mode)));
  if (c.mesh.instanceColor) c.mesh.instanceColor.needsUpdate = true;
  $('colorkey').textContent = COLOR_KEYS[mode];
  $('colorkey').style.display = mode === 'line' ? 'none' : '';
}

// Face labels: one InstancedMesh of planes per container, 5 per piece (top and four sides, no bottom), text
// taken from one canvas atlas with a cell per line id. The plane count follows `mesh.count` (x5), so replay
// stepping needs no extra state. A face with a side under LABEL_MIN_SIDE gets a zero-scale (invisible) plane.
const LABEL_CELL_W = 256, LABEL_CELL_H = 64, LABEL_FONT = 52, LABEL_GLYPH = 38, LABEL_MIN_SIDE = 0.15, LABEL_LIFT = 0.001;
let labelAtlas = null;

function makeLabelAtlas(ids) {
  const cols = Math.max(1, Math.min(ids.length, 8)), rows = Math.max(1, Math.ceil(ids.length / cols));
  const cv = document.createElement('canvas');
  cv.width = cols * LABEL_CELL_W; cv.height = rows * LABEL_CELL_H;
  const g = cv.getContext('2d');
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.lineJoin = 'round';
  const cells = ids.map((id, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    let px = LABEL_FONT;
    g.font = `bold ${px}px system-ui, sans-serif`;
    const w0 = g.measureText(id).width;
    if (w0 > LABEL_CELL_W - 16) { px = LABEL_FONT * (LABEL_CELL_W - 16) / w0; g.font = `bold ${px}px system-ui, sans-serif`; }
    const cx = col * LABEL_CELL_W + LABEL_CELL_W / 2, cy = row * LABEL_CELL_H + LABEL_CELL_H / 2;
    g.lineWidth = 7; g.strokeStyle = 'rgba(255,255,255,0.92)'; g.strokeText(id, cx, cy);
    g.fillStyle = '#111'; g.fillText(id, cx, cy);
    return { col, row, textW: g.measureText(id).width, glyphH: LABEL_GLYPH * px / LABEL_FONT };
  });
  const texture = new THREE.CanvasTexture(cv);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  const material = new THREE.MeshBasicMaterial({ map: texture, alphaTest: 0.4, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  material.userData.shared = true;
  const grid = new THREE.Vector2(cols, rows);
  material.onBeforeCompile = (shader) => {   // pick the atlas cell per instance (attribute aCell = column, row)
    shader.uniforms.uGrid = { value: grid };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute vec2 aCell;\nuniform vec2 uGrid;')
      .replace('#include <uv_vertex>', '#include <uv_vertex>\nvMapUv = vec2((aCell.x + uv.x) / uGrid.x, 1.0 - (aCell.y + 1.0 - uv.y) / uGrid.y);');
  };
  return { texture, material, cells };
}

export function disposeLabelAtlas() {
  labelAtlas?.texture.dispose();
  labelAtlas?.material.dispose();
  labelAtlas = null;
}

// Side faces in three.js axes (X = x, Y = z up, Z = -y): outward normal n and text direction u; text up is +Y, so
// u x v = n and the text reads left to right from outside. The top face runs its text along the longer side.
const SIDE_FACES = [
  { n: [1, 0, 0], u: [0, 0, -1] }, { n: [-1, 0, 0], u: [0, 0, 1] },
  { n: [0, 0, 1], u: [1, 0, 0] }, { n: [0, 0, -1], u: [-1, 0, 0] },
];

function buildFaceLabels(boxes) {
  const n = boxes.length;
  labelAtlas ??= makeLabelAtlas(S.view.lines.map((l) => l.id));
  const cellAttr = new Float32Array(Math.max(1, n) * 5 * 2);
  const geo = new THREE.PlaneGeometry(1, 1);
  geo.setAttribute('aCell', new THREE.InstancedBufferAttribute(cellAttr, 2));
  const mesh = new THREE.InstancedMesh(geo, labelAtlas.material, Math.max(1, n) * 5);
  const m = new THREE.Matrix4(), un = new THREE.Vector3(), vn = new THREE.Vector3(), nn = new THREE.Vector3(), pos = new THREE.Vector3();
  const zero = new THREE.Matrix4().makeScale(0, 0, 0);
  boxes.forEach((b, i) => {
    const cell = labelAtlas.cells[S.lineIndex[b.line]] ?? labelAtlas.cells[0];
    const lx = b.l >= b.w;
    const faces = [{ n: [0, 1, 0], u: lx ? [1, 0, 0] : [0, 0, 1], v: lx ? [0, 0, -1] : [1, 0, 0],
                     along: Math.max(b.l, b.w), vert: Math.min(b.l, b.w), half: b.h / 2 }];
    for (const f of SIDE_FACES) {
      const alongX = f.n[0] !== 0;   // a face normal to x spans y (width) and z
      faces.push({ n: f.n, u: f.u, v: [0, 1, 0], along: alongX ? b.w : b.l, vert: b.h, half: (alongX ? b.l : b.w) / 2 });
    }
    faces.forEach((f, j) => {
      const idx = i * 5 + j;
      cellAttr[idx * 2] = cell.col; cellAttr[idx * 2 + 1] = cell.row;
      const short = Math.min(f.along, f.vert);
      if (short < LABEL_MIN_SIDE) { mesh.setMatrixAt(idx, zero); return; }
      let gh = 0.6 * short;   // glyph height: 60% of the short side, shrunk to keep the text inside 90% of the long side
      const tw = gh * cell.textW / cell.glyphH;
      if (tw > 0.9 * f.along) gh *= 0.9 * f.along / tw;
      const k = gh / cell.glyphH;   // world metres per atlas pixel
      un.fromArray(f.u).multiplyScalar(LABEL_CELL_W * k);
      vn.fromArray(f.v).multiplyScalar(LABEL_CELL_H * k);
      nn.fromArray(f.n);
      pos.set(b.x + b.l / 2, b.z + b.h / 2, -(b.y + b.w / 2)).addScaledVector(nn, f.half + LABEL_LIFT);
      m.makeBasis(un, vn, nn).setPosition(pos);
      mesh.setMatrixAt(idx, m);
    });
  });
  mesh.count = n * 5;
  mesh.instanceMatrix.needsUpdate = true;
  return mesh;
}

// One container as a three.js group; `labels` adds the name and "cửa" sprites and `faceLabels` the line ids on the
// faces (neither on thumbnails: the sprites need the stage, the face labels cost a draw call per thumbnail).
export function buildContainer(data, labels, faceLabels = false) {
  const n = data.replay.length;
  const group = new THREE.Group();
  group.position.set(0, 0, data.W);   // y in [0, W] maps to Z in [-W, 0]
  const boxes = data.replay.map((i) => S.view.placements[i]);

  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshLambertMaterial(), Math.max(1, n));
  const m = new THREE.Matrix4();
  const edgePos = new Float32Array(n * 24 * 3);
  boxes.forEach((b, i) => {
    m.compose(new THREE.Vector3(b.x + b.l / 2, b.z + b.h / 2, -(b.y + b.w / 2)), new THREE.Quaternion(),
              new THREE.Vector3(b.l, b.h, b.w));
    mesh.setMatrixAt(i, m);
    mesh.setColorAt(i, S.colors[S.lineIndex[b.line]] ?? new THREE.Color(0x888888));
    BOX_EDGES.forEach((e, j) => {
      const o = (i * 12 + j) * 6;
      edgePos[o] = b.x + e[0] * b.l; edgePos[o + 1] = b.z + e[1] * b.h; edgePos[o + 2] = -(b.y + e[2] * b.w);
      edgePos[o + 3] = b.x + e[3] * b.l; edgePos[o + 4] = b.z + e[4] * b.h; edgePos[o + 5] = -(b.y + e[5] * b.w);
    });
  });
  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  group.add(mesh);
  const lbl = faceLabels ? buildFaceLabels(boxes) : null;
  if (lbl) { lbl.visible = $('showlabels').checked; group.add(lbl); }

  const edgeGeo = new THREE.BufferGeometry();
  edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgePos, 3));
  const edges = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95 }));
  group.add(edges);

  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(data.L, data.H, data.W)),
                                       new THREE.LineBasicMaterial({ color: FRAME_BLUE }));
  frame.position.set(data.L / 2, data.H / 2, -data.W / 2);
  group.add(frame);
  // The door frame: four yellow bars (box meshes, a line stays one pixel wide). Stage only, like the grid and the glass.
  let walls = null;
  if (labels) {
    walls = new THREE.Group();
    const glass = (w, h, opacity) => new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: FRAME_BLUE, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false }));
    const floor = glass(data.L, data.W, 0.22);
    floor.rotation.x = -Math.PI / 2; floor.position.set(data.L / 2, 0.001, -data.W / 2);
    const back = glass(data.W, data.H, 0.13);   // the inner end wall, opposite the door
    back.rotation.y = Math.PI / 2; back.position.set(0, data.H / 2, -data.W / 2);
    const side = glass(data.L, data.H, 0.13);   // the long wall far from the default camera
    side.position.set(data.L / 2, data.H / 2, -data.W);
    walls.add(floor, back, side);
    walls.visible = skin.walls;
    group.add(walls);
    const gold = new THREE.MeshBasicMaterial({ color: DOOR_GOLD }), t = DOOR_BAR;
    const bar = (sx, sy, sz, x, y, z) => { const b = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), gold); b.position.set(x, y, z); return b; };
    group.add(bar(t, data.H, t, data.L, data.H / 2, 0), bar(t, data.H, t, data.L, data.H / 2, -data.W),
              bar(t, t, data.W, data.L, data.H, -data.W / 2), bar(t, t, data.W, data.L, 0, -data.W / 2));
    const ground = groundGrid();
    ground.position.set(data.L / 2, -0.002, -data.W / 2);
    group.add(ground);
  }

  const pick = new THREE.Mesh(new THREE.BoxGeometry(data.L, data.H, data.W),
                              new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
  pick.position.copy(frame.position);
  if (labels) pick.userData.fitPoints = [new THREE.Vector3(data.L + 3.8, data.H / 2, -data.W / 2)];
  group.add(pick);

  if (labels) {   // no container name in the scene (the toolbar and the card have it); "cửa" outside the door, on top
    const doorLabel = textSprite('cửa', '#b45309');
    doorLabel.position.set(data.L + 2.2, data.H / 2, -data.W / 2);
    doorLabel.scale.set(3.2, 0.8, 1);
    doorLabel.renderOrder = 999;
    group.add(doorLabel);
  }
  return { data, group, mesh, edges, pick, walls, labels: lbl, order: boxes, count: n };
}

// Aim `cam` at `object` from direction `dir` (default: a three-quarter view), as close as keeps its box inside `margin`
// of the frame; `ctl` (orbit controls) then orbits around the box centre. The first distance comes from the bounding
// sphere and the camera field of view and aspect; a few passes on the projected box corners then tighten it (the box is
// long, so the sphere alone leaves the container small in a wide frame).
const VIEW_DIR = new THREE.Vector3(-0.3, 0.55, 1).normalize();
export const VIEWS = {   // the named views of the orientation block (viewnav.js)
  home: VIEW_DIR,
  top: new THREE.Vector3(0, 1, 0.02).normalize(),
  bottom: new THREE.Vector3(0, -1, 0.02).normalize(),
  left: new THREE.Vector3(0, 0.12, 1).normalize(),    // three +Z: the side on the left seen from the door
  right: new THREE.Vector3(0, 0.12, -1).normalize(),
  door: new THREE.Vector3(1, 0.12, 0).normalize(),
  end: new THREE.Vector3(-1, 0.12, 0).normalize(),    // the closed end
};
export function fit(cam, object, ctl, margin = 0.9, dir = VIEW_DIR) {
  object.updateWorldMatrix(true, false);
  const box = new THREE.Box3().expandByObject(object);
  // Points outside the box that must stay in the frame too (the door label), in the object's parent space.
  for (const p of object.userData.fitPoints ?? []) box.expandByPoint(p.clone().applyMatrix4(object.parent.matrixWorld));
  const center = box.getCenter(new THREE.Vector3());
  const corners = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
  const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
  const vfov = (cam.fov * Math.PI) / 180, hfov = 2 * Math.atan(Math.tan(vfov / 2) * cam.aspect);
  let dist = radius / Math.sin(Math.min(vfov, hfov) / 2) / margin;
  for (let pass = 0; pass < 4; pass++) {   // perspective: the needed distance depends on the distance, so iterate
    cam.position.copy(center).addScaledVector(dir, dist);
    cam.lookAt(center);
    cam.near = dist / 100;
    cam.far = dist * 10;
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    const extent = Math.max(...corners.map((p) => { const q = p.clone().project(cam); return Math.max(Math.abs(q.x), Math.abs(q.y)); }));
    dist *= extent / margin;
  }
  cam.position.copy(center).addScaledVector(dir, dist);
  cam.lookAt(center);
  cam.updateProjectionMatrix();
  if (ctl) ctl.target.copy(center);
}
