// Result screen (tiles, item types, violations), the selected container's panel and its item drawer with
// constraint 7/8 measures and posture icons.
import { $, el, fmt, fmtDim, fmtKg, fmtRatio, num, pct } from './util.js';
import { icon } from './icons.js';
import { S } from './state.js';
import { lineHex, useOf } from './scene.js';
import { setPicked } from './player.js';
import { applyDrawer } from './layout.js';
import { kindOf } from './orient.js';
import { orientIcon } from './orienticon.js';
import { HATCH_DEFS, boxSvg } from './lotpreview.js';

const lineOf = (b) => S.view.lines[S.lineIndex[b.line]];
const alphaText = () => `${fmt(S.view.params.alpha * 100, 0)}%`;
export const swatch = (id) => el('span', { class: 'sw', style: `background:${lineHex(id)}` });

// A piece's real value next to its type's limit (ui.md §3): "tải đè 0 / 285 kg", "tầng 2 / 5", "đỡ 100% / ≥ 80%".
export function loadText(b) {
  const l = lineOf(b);
  if (!l || b.on_top === null) return '—';
  if (l.load === 0) return 'không chồng';
  return `${fmtKg(b.on_top)} / ${l.load === null ? '∞' : fmtKg(l.load)}`;
}

export function tiersText(b) {
  const l = lineOf(b);
  if (!l || b.stack === null) return '—';
  if (l.tiers === 1) return 'chỉ sàn';
  return `${b.stack} / ${l.tiers === null ? '∞' : l.tiers}`;
}

export function supportText(b) {
  if (b.stack === null) return '—';
  return b.supported === null ? 'sàn' : `${pct(b.supported)} / ≥ ${alphaText()}`;
}

function overLimit(b, mode) {
  const u = useOf(b, mode);
  if (u === null) return false;
  return mode === 'support' ? u < S.view.params.alpha - 1e-9 : u > 1 + 1e-9;
}

// ---------------------------------------------------------------- shared pieces
// An orientation code names the item dimension along x, y, z.
// Posture in words; the kind rule (đứng / nằm / dựng cao / lật) lives in orient.js.
// Rotated 90° when the two horizontal letters come in reverse of L, W, H order (WLH, HLW, HWL).
const postureKind = (code, line) => kindOf(code[2], line);
const isRotated = (code) => 'LWH'.indexOf(code[0]) > 'LWH'.indexOf(code[1]);
export const postureWords = (b) => postureKind(b.o, lineOf(b)) + (isRotated(b.o) ? ', xoay 90°' : '');
export const tippableWords = (b) => (lineOf(b)?.tippable ? 'được lật' : 'chỉ đứng');

// Allowed orientations of a line, grouped by kind ("đứng, nằm"); the full codes go in a tooltip.
function allowedWords(l) {
  const kinds = new Set(l.orientations.map((c) => postureKind(c, l)));
  return ['đứng', 'nằm', 'dựng cao', 'lật'].filter((k) => kinds.has(k)).join(', ');
}

const bar = (ratio) => el('div', { class: `bar${ratio > 1 ? ' over' : ''}` },
  el('div', { style: `width:${Math.max(0, Math.min(1, ratio ?? 0)) * 100}%` }));
const kv = (rows) => el('table', { class: 'kv' }, rows.map(([k, v, title]) => el('tr', {}, el('td', title ? { title } : {}, k), el('td', {}, v))));
const chip = (...kids) => el('span', { class: 'chip' }, ...kids);
const infoTip = (text) => {
  const i = el('span', { class: 'info', tabIndex: 0, role: 'note' }, icon('info'));
  i.setAttribute('aria-label', text);
  i.dataset.tip = text;
  return i;
};

// "3 × 45HC, 1 × 20DC": the fleet, container types in order of first use.
export function fleetText(containers) {
  const n = new Map();
  for (const c of containers) n.set(c.type, (n.get(c.type) ?? 0) + 1);
  return [...n].map(([t, k]) => `${k} × ${t}`).join(', ');
}

const limitWords = {
  posture: (l) => (l.tippable ? 'được lật' : 'chỉ đứng'),
  load: (l) => (l.load === 0 ? 'không chồng' : l.load === null ? 'không giới hạn' : `chịu ${fmtKg(l.load)} kg`),
  tiers: (l) => (l.tiers === 1 ? 'chỉ sàn' : l.tiers === null ? 'không giới hạn' : `≤ ${l.tiers} tầng`),
};

// The box of a loại kiện in proportion, as on the lot screen: red stripes on top for "không chồng", a dark foot for "chỉ sàn".
function boxIcon(l) {
  if (!document.getElementById('lf-hatch')) document.body.insertAdjacentHTML('beforeend', HATCH_DEFS);
  return el('span', { class: 'boxicon', innerHTML: boxSvg(l, l.id, { w: 56, h: 44, noStack: l.load === 0, floorOnly: l.tiers === 1 }) });
}

// The item types of the lot as a read-only table; "Nằm ở container" lists where each type went, `currentK` in bold.
export function linesTable(v, currentK = null) {
  const where = (id) => v.containers.flatMap((c, i) => {
    const x = c.lines.find((q) => q.id === id);
    return x ? [el('a', { href: `#/container/${i + 1}`, class: c.k === currentK ? 'cur' : '' }, `#${c.k}: ${x.qty}`)] : [];
  }).flatMap((a, i) => (i ? [' · ', a] : [a]));
  return el('table', { class: 'lines' },
    el('tr', {}, ['Loại kiện', 'Số kiện', 'Kích thước (m)', 'kg / kiện', 'Tư thế', 'Chồng lên trên', 'Số tầng', 'Nằm ở container']
      .map((t, i) => el('th', { class: i === 1 || i === 3 ? 'num' : '' }, t))),
    v.lines.map((l) => el('tr', {},
      el('td', { class: 'nowrap' }, boxIcon(l), el('b', {}, l.id)),
      el('td', { class: 'num' }, l.qty),
      el('td', { class: 'nowrap' }, `${fmtDim(l.L)} × ${fmtDim(l.W)} × ${fmtDim(l.H)}`),
      el('td', { class: 'num' }, fmtKg(l.mass)),
      el('td', {}, chip(limitWords.posture(l)), l.orientations
        ? el('span', { class: 'muted', title: `Mã hướng cho phép: ${l.orientations.join(' ')}` }, ` ${allowedWords(l)}`) : ''),
      el('td', {}, chip(limitWords.load(l))),
      el('td', {}, chip(limitWords.tiers(l))),
      el('td', {}, where(l.id)))));
}

// "Cả lô": the lot's item types in a dialog over the 3D screen; the open container's counts in bold.
export function openLines(k) {
  let d = $('linesdlg');
  if (!d) {
    d = el('dialog', { id: 'linesdlg', class: 'wide' });
    d.addEventListener('click', (e) => { if (e.target === d || e.target.closest('a')) d.close(); });
    document.body.append(d);
  }
  const total = S.view.lines.reduce((n, l) => n + l.qty, 0);
  const close = el('button', { class: 'ghost icon', title: 'Đóng (Esc)', onclick: () => d.close() }, icon('x'));
  close.setAttribute('aria-label', 'Đóng');
  d.replaceChildren(
    el('div', { class: 'dlghead' }, el('h2', {}, 'Loại kiện'),
      el('span', { class: 'muted' }, `${S.view.lines.length} loại · ${total} kiện · đậm: container #${k}`), el('span', { class: 'spacer' }), close),
    el('div', { class: 'dlgbody' }, linesTable(S.view, k)));
  d.showModal();
}

// ---------------------------------------------------------------- side panels
export function renderLegend() {
  const rows = S.view.lines.map((l) => el('tr', {},
    el('td', {}, swatch(l.id), l.id),
    el('td', {}, `${l.qty} × ${fmtDim(l.L)}×${fmtDim(l.W)}×${fmtDim(l.H)} m, ${fmtKg(l.mass)} kg`),
    el('td', {}, [limitWords.posture(l), limitWords.load(l), limitWords.tiers(l)].join(', '))));
  $('legend').replaceChildren(el('table', {}, rows));
}

export function renderContainerInfo() {
  S.itemRows = [];
  if (!S.cur) {
    $('box-cinfo').querySelector('h2').textContent = 'Container';
    $('cinfo').className = 'muted';
    $('cinfo').replaceChildren('Bấm một ô trong lưới container.');
    $('box-clines').hidden = true;
    $('clines').replaceChildren();
    $('drawer').hidden = true;
    $('dbody').replaceChildren();
    return;
  }
  const c = S.cur, d = c.data;
  $('box-cinfo').querySelector('h2').replaceChildren(`Container #${d.k}`, el('span', { class: 'cp-type' }, d.type));
  // Two big numbers; then one label / value pattern (14 px, value bold); a meter is one block: label and percent over a full-width
  // bar, the absolute amounts small under it. `tip`: an (i) next to the label, the explanation in a tooltip (as for δ and α).
  const tileBig = (value, label) => el('div', { class: 'cp-tile' }, el('div', { class: 'cp-big' }, value), el('div', { class: 'cp-lab' }, label));
  const rowOf = (label, value, tip) => el('dl', { class: 'cp-rows' },
    el('dt', { class: tip ? 'tipwrap' : '' }, label, tip ? infoTip(tip) : ''), el('dd', {}, value));
  const meter = (label, ratio, amounts, cls = '') => el('div', { class: 'cp-meter' },
    el('div', { class: 'cp-mhd' }, el('span', {}, label), el('b', { class: `num ${cls}` }, pct(ratio))),
    bar(ratio), el('div', { class: 'cp-amount' }, amounts));
  const summary = [
    el('div', { class: 'cp-tiles' }, tileBig(d.cost === null ? '—' : fmt(d.cost, 2), 'cước'), tileBig(String(c.count), 'kiện')),
    rowOf('Kích thước trong', `${fmtDim(d.L)} × ${fmtDim(d.W)} × ${fmtDim(d.H)} m`),
    meter('Thể tích', d.volume_ratio, `${fmt(d.volume, 1)} / ${fmt(d.L * d.W * d.H, 1)} m³`),
    meter('Khối lượng', d.mass_ratio, `${fmt(d.mass, 0)} / ${fmt(d.max_mass, 0)} kg`, d.mass_ratio > 1 ? 'bad' : ''),
    rowOf('Còn chồng được', `${d.free_tops} kiện`, `Số kiện còn chỗ để chồng thêm một kiện lên mặt trên: mặt trên trống, còn tầng, chịu được tải đè, ` +
      `còn khoảng tới nóc cho kiện thấp nhất của lô (${fmtDim(S.view.min_item_height)} m). Chỉ là ước lượng: chưa xét diện tích, khe hở δ, đỡ, khối lượng.`)];
  const showAll = el('button', { class: 'sm', id: 'alllines', title: 'Xem loại kiện của cả lô', onclick: () => openLines(d.k) }, icon('list'), 'Cả lô');
  const byLine = [
    el('div', { class: 'cihead' }, el('h2', {}, 'Loại kiện trong container'), el('span', { class: 'spacer' }), showAll),
    el('table', {},
      el('tr', {}, ['Loại kiện', 'Kiện', 'kg'].map((t, i) => el('th', { class: i ? 'num' : '' }, t))),
      d.lines.map((l) => el('tr', {},
        el('td', {}, swatch(l.id), l.id), el('td', { class: 'num' }, l.qty), el('td', { class: 'num' }, fmtKg(l.mass)))))];
  S.itemRows = c.order.map((b, i) => el('tr', { class: 'click', tabIndex: 0, onclick: () => setPicked(S.picked === i ? null : i) },
    el('td', { class: 'num' }, i + 1),
    el('td', { class: 'nowrap' }, swatch(b.line), b.item),
    el('td', { class: 'dir', title: `${postureWords(b)}, cao ${fmtDim(b.h)} m. Mã hướng ${b.o}: chiều L, W, H của kiện nằm dọc x, y, z. Mặt tô xanh là mặt trên gốc của kiện (vuông góc với H).` },
      orientIcon(b), `${postureWords(b)} `, el('span', { class: 'muted' }, `· ${tippableWords(b)}`)),
    el('td', { class: 'num' }, `${fmtDim(b.x)} · ${fmtDim(b.y)} · ${fmtDim(b.z)}`),
    el('td', { class: 'num' }, `${fmtDim(b.l)} × ${fmtDim(b.w)} × ${fmtDim(b.h)}`),
    el('td', { class: 'num' }, fmtKg(b.mass)),
    el('td', { class: `num ${overLimit(b, 'load') ? 'bad' : ''}` }, loadText(b)),
    el('td', { class: `num ${overLimit(b, 'tiers') ? 'bad' : ''}` }, tiersText(b)),
    el('td', { class: `num ${overLimit(b, 'support') ? 'bad' : ''}` }, supportText(b))));
  const heads = [['#', 'num'], ['Kiện', ''], ['Tư thế · khả năng lật', ''], ['Vị trí x · y · z (m)', 'num'], ['Kích thước (m)', 'num'], ['kg', 'num'],
    ['Tải đè (kg): thực tế / giới hạn', 'num'], ['Tầng: thực tế / giới hạn', 'num'], ['Đáy được đỡ: thực tế / yêu cầu', 'num']];
  const items = el('div', {}, el('table', {}, el('tr', {}, heads.map(([t, cls]) => el('th', { class: cls }, t))), S.itemRows));
  $('cinfo').className = '';
  $('cinfo').replaceChildren(...summary);
  $('clines').replaceChildren(...byLine);
  $('box-clines').hidden = false;
  $('dbody').replaceChildren(items);
  $('dtoggle').dataset.n = c.count;
  $('drawer').hidden = false;
  applyDrawer();
}

// "bật · 12 kiện lật (nằm 3, dựng cao 9)": the flag and how many pieces are tipped, shown even when the flag is off.
function tippedText(on, t) {
  const flag = on ? 'bật' : 'tắt';
  if (!t.total) return `${flag} · không kiện nào bị lật`;
  const kinds = [['nằm', t.lying], ['dựng cao', t.edge], ['lật', t.tipped]].filter(([, n]) => n > 0);
  return `${flag} · ${t.total} kiện lật (${kinds.map(([k, n]) => `${k} ${n}`).join(', ')})`;
}

// The warning on the result screen when pieces stand taller than upright (`edge`).
export const edgeWarning = (n) => `${n} kiện được đặt dựng cao (cao hơn khi đứng). Kiểm tra hàng có đặt như vậy được không; nếu không, tắt "Cho bộ giải chủ động lật kiện" trong Thiết lập nâng cao, hoặc đổi loại kiện sang "Chỉ đứng", rồi giải lại.`;

const BINDING = { volume: 'thể tích', mass: 'khối lượng', floor: 'diện tích sàn', mixed: 'nhiều ràng buộc', none: 'lô rỗng' };
const tile = (label, value, sub, id, cls = '', card = '') => el('div', { class: `card kpi ${card}`.trim(), id },
  el('div', { class: 'lab' }, label), el('div', { class: `val ${cls}` }, ...[value].flat()), el('div', { class: 'sub' }, sub));

// The result screen (`#/ket-qua`), filled into #resview. mode 'demo' (default): also the engine, seed, source and the
// engine's diagnostics; `runDir` (runs/<run>, where the demo saved it) goes into the folded details. mode 'service': no engine,
// seed, source or diagnostics.
export function renderResult(v, { mode = 'demo', runDir = null } = {}) {
  const service = mode === 'service';
  const ck = v.check, b = v.bound.cost, run = v.run;
  const ratio = ck.cost !== null && b > 0 ? ck.cost / b : null;
  const total = v.lines.reduce((n, l) => n + l.qty, 0);
  $('restop').textContent = `${v.instance} · xong sau ${fmt(run.time, 1)} s (giới hạn ${num(run.time_limit)} s) · khe hở δ ${num(run.delta)} m · đỡ α ${fmt(run.alpha * 100, 0)}%` +
    (service ? '' : ` · ${run.engine ?? '—'}, seed ${run.seed}`);
  $('restiles').replaceChildren(
    tile('Cước', fmt(ck.cost, 2), '', 'tile-cost', '', 'hero'),
    tile('Container', String(v.containers.length), fleetText(v.containers), 'tile-containers'),
    tile('So với cận dưới', ratio === null ? '—' : `× ${fmtRatio(ratio)}`, `không thể rẻ hơn ${fmt(b, 2)} (${BINDING[v.bound.binding] ?? v.bound.binding})`, 'tile-bound'),
    tile('Kiểm tra ràng buộc', ck.ok ? [icon('check'), ' Đạt'] : `Sai: ${ck.n_violations} vi phạm`,
      `${v.placements.length} / ${total} kiện đã xếp · 9 ràng buộc`, 'tile-check', ck.ok ? 'ok' : 'bad'));
  $('reslines').replaceChildren(el('section', { class: 'card' },
    el('div', { class: 'hd' }, el('h2', {}, 'Loại kiện'), el('span', { class: 'muted' }, `${v.lines.length} loại · ${total} kiện`)),
    el('div', { class: 'tablewrap' }, linesTable(v))));

  if (service && $('reswarn')) {   // the flag is on by default, so the warning sits where the user decides
    const n = v.tipped?.edge || 0;
    $('reswarn').replaceChildren(...(n > 0 ? [el('div', { class: 'alert caution', role: 'alert' }, icon('circle-alert'), edgeWarning(n))] : []));
  }
  const extra = [];
  if (ck.violations.length) {
    extra.push(el('section', { class: 'card' }, el('div', { class: 'hd' }, el('h2', {}, `Vi phạm (${ck.violations.length}/${ck.n_violations})`)),
      el('ul', { class: 'viol' }, ck.violations.slice(0, 30).map((x) => el('li', {}, `RB ${x.constraint}${x.k ? `, container ${x.k}` : ''}: ${x.message}`)))));
  }
  const rows = [['Thời gian chạy', `${fmt(run.time, 1)} s (giới hạn ${num(run.time_limit)} s)`], ['Cận dưới', `${fmt(b, 2)} (${v.bound.binding})`]];
  if (!service) rows.push(['Engine, seed', `${run.engine ?? '—'}, ${run.seed}`]);
  if (service) rows.push(['Chủ động lật kiện', tippedText(run.orient, v.tipped || { total: 0 })]);
  rows.push(service ? ['δ, α', `${num(run.delta)}, ${num(run.alpha)}`] : ['δ, α, bảng cước', `${num(run.delta)}, ${num(run.alpha)}, ${run.cost_table}`]);
  if (!service) rows.push(['Nguồn', run.source]);
  if (!service && runDir) rows.push(['Thư mục run', runDir]);
  const diag = service ? [] : Object.entries(run.diagnostics || {});
  extra.push(el('section', { class: 'card' }, el('details', { id: 'resdetails' },
    el('summary', {}, service ? 'Thông tin lần giải' : 'Chi tiết lần chạy'),
    el('table', {}, rows.map(([k, val]) => el('tr', {}, el('td', {}, k), el('td', {}, val)))),
    v.note && !service ? el('div', { class: 'muted' }, v.note) : '',   // the sample-data note is for the demo, not for an app people use
    diag.length ? el('details', {}, el('summary', {}, `Chỉ số của engine (${diag.length})`),
      el('table', {}, diag.map(([k, val]) => el('tr', {}, el('td', {}, k),
        el('td', {}, typeof val === 'number' ? fmt(val, 3).replace(/,?0+$/, '') : String(val)))))) : '')));
  $('resextra').replaceChildren(...extra);
}

// The result screen of a closed solution.
export function clearResultPage() {
  $('restop').textContent = '';
  for (const id of ['restiles', 'reslines', 'resextra']) $(id).replaceChildren();
  if ($('reswarn')) $('reswarn').replaceChildren();
}
