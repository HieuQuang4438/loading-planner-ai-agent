// The app's screens (docs/product/ux.md §3–§5): hash routes, a lot's documents, its data and the points
// to confirm, the chat, the run setup, the result and the comparison. Built from the prototype on the design
// system; the 3D of a container is the container screen, mounted once in #scr-view.
import { $, el, fmt, fmtDim, fmtKg, num, store, download } from './util.js';
import { icon as lucide, iconHtml as ic } from './icons.js';
import { boxSvg, HATCH_DEFS, HATCH_ID } from './lotpreview.js';
import { TIME_LEVELS, levelHint, massPerItem, massShown, numberOrRaw, promiseText, showNumber } from './lotrules.js';
import { lineCss } from './linecolor.js';
import { askText, confirmDelete, popover, toast } from './shell.js';
import { containerTitle, mountViewer, setChrome } from './stage.js';
import { fillArtSvg } from './fillart.js';
import { comparable, csvPlan, fileKind, fleetText, parseDecimal, runCompare, runNumbers, runOutcome, solveClock, totals,
  valueText } from './plannerrules.js';

const app = $('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const usd = (x) => (x === null || x === undefined ? '—' : `${fmt(x, 2)} USD`);
const POLL_MS = 1500;
const CHAT_KEY = 'planner:chatmin';

// ---- server -------------------------------------------------------------------------------------------------------
async function api(path, { method = 'GET', body } = {}) {
  const r = await fetch(path, {
    method, credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { location.assign('/login'); throw new Error('Cần đăng nhập'); }
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : null;
  if (!r.ok) {
    const e = new Error(data?.message || `Lỗi ${r.status}`);
    e.status = r.status;
    e.data = data;
    throw e;
  }
  return data;
}

const fileData = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

async function upload(lotId, files) {
  const list = [];
  for (const f of files) list.push({ name: f.name, data: await fileData(f) });
  return api(`/api/lots/${lotId}/documents`, { method: 'POST', body: { files: list } });
}

// ---- state --------------------------------------------------------------------------------------------------------
const S = { editPoints: false, lot: null, chat: [], live: null, sending: false, point: null, pollTimer: null, error: null, runs: {}, mode: 'a', fill: null,
  draft: {}, allRuns: false };
let me = '';
let uploading = false;

// ---- drawing ------------------------------------------------------------------------------------------------------
// Every screen is drawn whole into #app; a lot's screen is drawn again on each change. The chat's draft is kept
// per lot as it is typed (`S.draft`), so a redraw does not lose it; focus goes back to the same control (by id, else
// its data-* attributes, else the same action), and to the title when that control is gone or the screen is new.
let newScreen = false;
function focusKeys(node) {
  if (!node || node === app || !app.contains(node)) return [];
  if (node.id) return [`#${CSS.escape(node.id)}`];
  const attrs = Object.entries(node.dataset).map(([k, v]) => `[data-${k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${CSS.escape(v)}"]`);
  const tag = node.tagName.toLowerCase();
  return attrs.length ? [`${tag}${attrs.join('')}`, ...(node.dataset.act ? [`${tag}[data-act="${CSS.escape(node.dataset.act)}"]`] : [])] : [];
}
// Runs `draw` (which replaces the chat input) keeping the input's focus and caret.
function keepChatInput(draw) {
  const box = $('chattext');
  const typing = box && document.activeElement === box ? [box.selectionStart, box.selectionEnd] : null;
  draw();
  const next = $('chattext');
  if (typing && next) { next.focus({ preventScroll: true }); next.setSelectionRange(...typing); }
}
function paint(html) {
  const keys = newScreen ? [] : focusKeys(document.activeElement);
  const fresh = newScreen;
  newScreen = false;
  keepChatInput(() => { app.innerHTML = html; });
  scrollChat();
  if (document.activeElement === $('chattext') && !fresh) return;
  const back = keys.map((k) => app.querySelector(k)).find((n) => n && !n.disabled);
  if (back) back.focus({ preventScroll: true });
  else if (fresh || keys.length) app.querySelector('h1')?.focus({ preventScroll: !fresh });
}

function setChatMin(on) {
  document.body.classList.toggle('chatmin', on);
  store.set(CHAT_KEY, on ? '1' : '0');
}
document.body.classList.toggle('chatmin', store.get(CHAT_KEY) === '1');

// ---- shared pieces ------------------------------------------------------------------------------------------------
const STATUS = {
  confirmed: ['ok', 'circle-check', 'Đã xác nhận'],
  extracted: ['ex', 'circle-alert', 'Trích xuất, các nguồn khớp'],
  needs_review: ['rv', 'triangle-alert', 'Cần xác nhận'],
};
const FIELDS = [['qty', 'Số lượng'], ['dims', 'Dài × rộng × cao (m)'], ['mass', 'Khối lượng một kiện, cả bì (kg)'],
  ['posture', 'Tư thế'], ['stacking', 'Chồng'], ['fragile', 'Dễ vỡ']];
const FIELD_WORD = { qty: 'số lượng', dims: 'kích thước', mass: 'khối lượng', posture: 'tư thế', stacking: 'chồng', fragile: 'dễ vỡ' };
// A row that opens something: the whole row is the target, ending in a chevron; its link stays the keyboard way in.
const ROW_GO = `<td class="rowgo" aria-hidden="true">${ic('chevron-right')}</td>`;

// A screen's toolbar: a back button to the last crumb, the trail (only when it goes further than the back button), the
// title (with `acts` beside it), then `rest`.
function toolbar(crumbs, title, rest = '', acts = '') {
  const trail = crumbs.map(([href, text]) => `<a href="${href}">${esc(text)}</a>`).join('<span aria-hidden="true">/</span>');
  const [backHref, backText] = crumbs[crumbs.length - 1];
  return `<div class="wstool"><a class="backbtn" href="${backHref}" title="Quay lại ${esc(backText)}">${ic('arrow-left')}<span>Quay lại</span></a>
    <div class="ttl">${crumbs.length > 1 ? `<nav class="crumbs" aria-label="Vị trí">${trail}</nav>` : ''}<div class="ttlrow"><h1 tabindex="-1">${esc(title)}</h1>${acts}</div></div>${rest}</div>`;
}
const lotActs = (x) => `<button class="ghost icon sm" data-act="rename-lot" data-id="${x.id}" data-name="${esc(x.name)}" aria-label="Đổi tên lô ${esc(x.name)}" title="Đổi tên">${ic('pencil')}</button>
  <button class="ghost icon sm" data-act="del-lot" data-id="${x.id}" data-name="${esc(x.name)}" aria-label="Xóa lô ${esc(x.name)}" title="Xóa lô">${ic('trash')}</button>`;
const workspace = (tool, body) => `<div class="ws"><div class="wsmain">${tool}<div class="wsbody">${body}</div></div>${chatColumn()}</div>`;
const lotCrumbs = (body) => [['#/lo-hang', 'Lô hàng'], [`#/lo/${body.id}`, body.name]];

function openPointOf(lot) {
  const map = {};
  for (const p of lot.points) if (!p.resolved_at) for (const f of p.fields) map[f] = p.id;
  return map;
}

function statusOf(body) {
  const docs = body.documents;
  if (docs.some((d) => d.status === 'waiting' || d.status === 'reading')) return 'reading';
  const lot = body.lot;
  if (!lot.lines.length) return 'empty';
  if (lot.points.some((p) => !p.resolved_at)) return 'points';
  const all = lot.lines.every((l) => FIELDS.every(([n]) => l[n].status === 'confirmed'));
  return all ? 'confirmed' : 'rest';
}

function statusFlag(body) {
  const open = body.lot.points.filter((p) => !p.resolved_at).length;
  return {
    reading: `<span class="flag">${ic('clock')}Đang đọc tài liệu</span>`,
    empty: `<span class="flag">${ic('file-plus')}Chưa có dữ liệu</span>`,
    points: `<span class="flag warnf">${ic('triangle-alert')}${open} câu hỏi cần trả lời</span>`,
    rest: `<span class="flag warnf">${ic('triangle-alert')}Chờ xác nhận dữ liệu lô</span>`,
    confirmed: `<span class="flag ok">${ic('circle-check')}Đã xác nhận</span>`,
  }[statusOf(body)];
}

const RUN_WHY = {
  reading: 'Đang đọc tài liệu', empty: 'Thêm tài liệu hoặc nhập dòng thì mới chạy được',
  points: 'Trả lời hết các câu hỏi thì mới chạy được', rest: 'Xác nhận dữ liệu lô thì mới chạy được', confirmed: '',
};

function runButton(body) {
  const why = RUN_WHY[statusOf(body)];
  return `<span class="spacer"></span>${why ? `<span class="runreason">${why}</span>` : ''}
    <button class="primary" ${why ? 'disabled' : ''} data-go="#/lo/${body.id}/chay">${ic('play')}Xếp lô hàng</button>`;
}

// ---- 1. lots ------------------------------------------------------------------------------------------------------
async function screenLots() {
  const lots = await api('/api/lots');
  const flag = (x) => (x.open_points ? `<span class="flag warnf">${ic('triangle-alert')}${x.open_points} câu hỏi cần trả lời</span>`
    : x.confirmed ? `<span class="flag ok">${ic('circle-check')}Đã xác nhận</span>`
      : x.lines ? `<span class="flag warnf">${ic('triangle-alert')}Chờ xác nhận</span>` : `<span class="flag">${ic('file-plus')}Chưa có dữ liệu</span>`);
  const run = (r) => `${r.mode === 'b' ? 'Container có sẵn' : 'Container rẻ nhất'} · ${esc(runOutcome(r))}`;
  const rows = lots.map((x) => `<tr data-name="${esc(x.name.toLowerCase())}" data-href="#/lo/${x.id}"><td><a class="rowlink" href="#/lo/${x.id}">${esc(x.name)}</a></td>
      <td>${x.documents} tài liệu</td><td>${flag(x)}</td><td>${x.last_run ? `<a href="#/lo/${x.last_run.lot_id ?? x.id}/ket-qua/${esc(x.last_run.job_id)}">${run(x.last_run)}</a>` : '—'}</td><td class="muted">${when(x.updated_at)}</td>
      <td class="rowacts">${lotActs(x)}</td>${ROW_GO}</tr>`).join('');
  paint(`<div class="page lotspage"><div class="pagehead"><h1 tabindex="-1">Lô hàng</h1><span class="spacer"></span>
      <input type="search" id="lotsearch" style="width:260px" aria-label="Tìm lô" placeholder="Tìm theo tên lô">
      <button class="primary" data-go="#/lo/moi">${ic('plus')}Lô mới</button></div>
    <section class="box flush">${lots.length ? `<table class="cmp lots"><thead><tr><th>Tên lô</th><th>Tài liệu</th><th>Dữ liệu</th><th>Lần chạy gần nhất</th><th>Cập nhật</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table>
      <p class="empty" id="lotnone" role="status" hidden></p>`
    : `<div class="empty">Chưa có lô nào. Bấm "Lô mới" rồi thả tài liệu của lô vào.</div>`}</section></div>`);
  $('lotsearch')?.addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    let shown = 0;
    for (const tr of app.querySelectorAll('tbody tr')) { tr.hidden = q !== '' && !tr.dataset.name.includes(q); shown += !tr.hidden; }
    const none = $('lotnone');
    if (none) { none.hidden = shown > 0; none.textContent = shown ? '' : `Không có lô nào khớp "${e.target.value.trim()}".`; }
  });
}

function when(stamp) {
  if (!stamp) return '';
  const d = new Date(stamp);
  const today = new Date();
  const hm = d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === today.toDateString() ? `hôm nay ${hm}` : `${d.toLocaleDateString('vi-VN')} ${hm}`;
}

// ---- 2. new lot ---------------------------------------------------------------------------------------------------
function screenNew() {
  S.lot = null;
  S.chat = [];
  const tool = toolbar([['#/lo-hang', 'Lô hàng']], 'Lô mới', `<span class="spacer"></span><span class="runreason">Thêm tài liệu hoặc nhập dòng thì mới chạy được</span><button class="primary" disabled>${ic('play')}Xếp lô hàng</button>`);
  const body = `<label class="namefield">Tên lô<input id="lotname" type="text" placeholder="Ví dụ: Lô xuất T11 — điện gia dụng"></label>
    <div class="bigdrop" id="bigdrop">${ic('upload')}<b>Kéo thả tài liệu của lô vào đây</b>
      <span>Bảng kê hàng (packing list; Excel, CSV), thông số kỹ thuật (spec; PDF), ảnh nhãn thùng. Thả nhiều file một lần được.</span>
      <button class="primary" data-act="pick">${ic('folder-open')}Chọn file</button>
      <div class="ordiv" aria-hidden="true">hoặc</div>
      <button data-act="manual-new">${ic('pencil')}Nhập tay từng mã hàng</button><div id="newmsg"></div></div>
    <ol class="steps"><li><b>Đọc</b> Trợ lý đọc từng tài liệu và ghi lại nguồn của mỗi giá trị.</li>
      <li><b>Đối chiếu</b> Chỗ nào thiếu hoặc các tài liệu ghi khác nhau thì trợ lý đặt câu hỏi cho bạn; không tự chọn, không tự điền.</li>
      <li><b>Xếp</b> Xác nhận đủ thì xếp lô hàng: ít cước nhất với bảng cước của bạn.</li></ol>`;
  paint(workspace(tool, body));
}

// A lot with no document, its rows typed one by one: the lot screen opens on the form of a new row.
async function createManual() {
  const name = $('lotname')?.value.trim() || `Lô ${new Date().toLocaleDateString('vi-VN')}`;
  try {
    const lot = await api('/api/lots', { method: 'POST', body: { name } });
    S.openAdd = true;
    location.hash = `#/lo/${lot.id}`;
  } catch (e) {
    $('newmsg').innerHTML = `<div class="alert bad">${esc(e.message)}</div>`;
  }
}

async function createWithFiles(files) {
  const name = $('lotname')?.value.trim() || `Lô ${new Date().toLocaleDateString('vi-VN')}`;
  try {
    const lot = await api('/api/lots', { method: 'POST', body: { name } });
    await upload(lot.id, files);
    location.hash = `#/lo/${lot.id}`;
  } catch (e) {
    uploadBusy(false);
    $('newmsg').innerHTML = `<div class="alert bad">${esc(e.message)}</div>`;
  }
}

// Files on their way up: the screen says so and its file buttons wait, so the same files are not sent twice.
function uploadBusy(on, n = 0) {
  uploading = on;
  for (const b of app.querySelectorAll('[data-act="pick"], [data-act="manual-new"]')) b.disabled = on;
  app.querySelector('.upmsg')?.remove();
  $('bigdrop')?.toggleAttribute('aria-busy', on);
  if (!on) return;
  const msg = `<span class="upmsg" role="status">${ic('refresh-cw')}Đang tải lên ${n} tệp…</span>`;
  if ($('newmsg')) $('newmsg').innerHTML = msg;
  else app.querySelector('.docs')?.insertAdjacentHTML('beforeend', msg);
}

// ---- 3. a lot -----------------------------------------------------------------------------------------------------
async function loadLot(id) {
  const [body, chat] = await Promise.all([api(`/api/lots/${id}`), api(`/api/lots/${id}/chat`)]);
  if (S.lot?.id !== body.id) { S.point = null; S.editPoints = false; S.allRuns = false; }
  S.lot = body;
  S.chat = chat;
  return body;
}

// Documents still being read, or read but not merged into the lot yet (the server says: `settled`).
const waiting = (body) => statusOf(body) === 'reading' || body.settled === false;

function schedulePoll(id) {
  clearTimeout(S.pollTimer);
  if (!S.lot || !waiting(S.lot)) return;
  S.pollTimer = setTimeout(async () => {
    if (!location.hash.startsWith(`#/lo/${id}`)) return;
    const body = await api(`/api/lots/${id}`);
    if (body.rev !== S.lot.rev || JSON.stringify(body.documents) !== JSON.stringify(S.lot.documents)) {
      S.lot = body;
      drawLot();
    }
    schedulePoll(id);
  }, POLL_MS);
}

async function screenLot(id) {
  await loadLot(id);
  drawLot();
}

function docsStrip(body) {
  const st = (d) => ({
    waiting: '<span class="dst">Chờ</span>',
    reading: `<span class="dst run">${ic('refresh-cw')}Đang đọc</span>`,
    read: `<span class="dst ok">${ic('check')}Đã đọc</span>`,
    failed: `<span class="dst bad">${ic('circle-alert')}Lỗi</span>`,
  }[d.status]);
  const busy = body.documents.some((d) => d.status === 'waiting' || d.status === 'reading');
  const docs = body.documents.map((d) => {
    const [icon, kind] = fileKind(d.name);
    return `<div class="doc">${ic(icon)}<div><b>${esc(d.name)}</b><span class="muted">${kind} · ${fmt(d.size / 1024, 0)} KB</span>
      ${d.error ? `<span class="dmsg">${esc(d.error)}</span>` : ''}</div>${st(d)}
      ${d.status === 'failed' ? `<button class="sm" data-act="reread-doc" data-id="${d.id}" ${busy ? 'disabled' : ''}>${ic('refresh-cw')}Đọc lại</button>` : ''}
      <button class="ghost icon sm docdel" data-act="del-doc" data-id="${d.id}" data-name="${esc(d.name)}" aria-label="Xóa tài liệu ${esc(d.name)}"
        title="${busy ? 'Đợi đọc xong rồi xóa' : 'Xóa tài liệu'}" ${busy ? 'disabled' : ''}>${ic('trash')}</button></div>`;
  }).join('');
  return `<section class="box docsbox"><h2>Tài liệu <span class="muted">${body.documents.length}</span></h2><div class="docs">${docs}
    <button class="docadd" data-act="pick">${ic('upload')}Thêm tài liệu</button></div></section>`;
}

function cell(line, name, pts) {
  const f = line[name];
  const [cls, icon, stText] = STATUS[f.status];
  const text = valueText(name, f.value, line.unit);
  const pt = pts[`${line.id}.${name}`];
  const list = f.sources.length
    ? f.sources.map((x) => `<li><b>${esc(x.file)} · ${esc(x.where)}</b>${x.raw === null ? '<span class="na">trống</span>' : `<q>${esc(x.raw)}</q>`}</li>`).join('')
    : '<li class="na">Không tài liệu nào ghi.</li>';
  const by = f.confirmed_by ? `<li class="na">Xác nhận bởi ${esc(f.confirmed_by)} lúc ${when(f.confirmed_at)}</li>` : '';
  const label = `${line.sku} ${FIELD_WORD[name]}`;
  const pop = `src-${String(line.id).replace(/[^A-Za-z0-9_-]/g, '_')}-${name}`;  // beside the button, not in it
  return `<span class="cvw"><button class="cv ${cls}" aria-expanded="false" aria-controls="${pop}" aria-label="${esc(label)}: ${esc(text)}, ${stText}. Xem nguồn">${ic(icon)}<span>${esc(text)}</span>${pt ? `<span class="pt" aria-hidden="true">${qid(pt)}</span>` : ''}</button>
    <div class="srcpop" id="${pop}" role="dialog" aria-label="Nguồn của ${esc(label)}" hidden><h3>${ic(icon)}${stText}${pt ? ` · câu hỏi ${qid(pt)}` : ''}</h3>
    <div class="sv">${esc(text)}</div><ul>${list}${by}</ul></div></span>`;
}

const isManual = (l) => FIELDS.every(([n]) => !l[n].sources.length);  // a row the user added (src.lot.edit)

function lotTable(body) {
  const pts = openPointOf(body.lot);
  const rows = body.lot.lines.map((l) => `<tr><td class="stripe"><span style="background:${lineCss(l.sku)}"></span></td>
      <td><span class="code">${esc(l.sku)}</span><div class="muted">${esc(l.description)}${isManual(l) ? `${l.description ? ' · ' : ''}người dùng nhập` : ''}</div></td>
      ${FIELDS.map(([n]) => `<td>${cell(l, n, pts)}</td>`).join('')}
      <td class="rowacts"><button class="ghost icon sm" data-act="edit-line" data-id="${esc(l.id)}" aria-label="Sửa dòng ${esc(l.sku)}" title="Sửa dòng">${ic('pencil')}</button>
        <button class="ghost icon sm" data-act="drop-line" data-id="${esc(l.id)}" aria-label="Bỏ dòng ${esc(l.sku)}" title="Bỏ dòng">${ic('trash')}</button></td></tr>`).join('');
  return `<table class="dtab"><thead><tr><th></th><th class="skucol">Mã hàng</th>${FIELDS.map(([, t]) => `<th>${t}</th>`).join('')}<th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

// The form of a row: code and quantity,
// size, mass per piece or for all, the handling rules as segmented buttons, and a box in proportion beside it.
// `line` null adds a row. Fields an open point settles are locked (answered there); a row read from the documents keeps
// its code and description. Resolves {sku, description, unit, values, then} or null; `then`: 'again' (save and add
// another), 'drop' (the row is to be taken out).
function lineDialog(line, pts) {
  const manual = !line || isManual(line);
  const lock = (n) => (line ? pts[`${line.id}.${n}`] : undefined);
  const cur = (n) => line?.[n].value;
  const w = {
    sku: line?.sku || '', description: line?.description || '', unit: line?.unit || 'carton',
    qty: cur('qty') ?? '', L: cur('dims')?.L ?? '', W: cur('dims')?.W ?? '', H: cur('dims')?.H ?? '', mass: cur('mass') ?? '',
    posture: cur('posture') || 'upright', stacking: cur('stacking') || { kind: 'free', tiers: null }, fragile: Boolean(cur('fragile')),
  };
  let massMode = 'piece';
  const text = (v) => (v === '' || v === null || v === undefined ? '' : showNumber(String(v)));
  const dialog = el('dialog', { class: 'ed' });
  const title = el('h2', {});
  const swatch = el('span', { class: 'lfsw' });
  const preview = el('div', { class: 'lfprev' });
  const previewDims = el('div', { class: 'lfprevdims' });
  const previewFlags = el('div', { class: 'lfflags' });
  const massHint = el('span', { class: 'muted' });
  const lockNote = (n) => (lock(n) ? el('span', { class: 'muted' }, `Đang chờ trả lời ở câu hỏi ${qid(lock(n))}.`) : '');
  function input(key, field, extra = {}) {
    const node = el('input', { type: 'text', value: key === 'sku' || key === 'description' ? w[key] : text(w[key]),
      inputMode: key === 'sku' || key === 'description' ? 'text' : 'decimal', spellcheck: false, ...extra });
    node.dataset.f = key;
    if (field && lock(field)) node.disabled = true;
    node.addEventListener('input', () => { w[key] = node.value; sync(); });
    return node;
  }
  const skuInput = input('sku', null, { disabled: !manual, maxLength: 100 });
  const descInput = input('description', null, { disabled: !manual, maxLength: 300 });
  const qtyInput = input('qty', 'qty');
  const stepQty = (d) => {
    const q = numberOrRaw(String(w.qty));
    w.qty = String(Math.max(1, (typeof q === 'number' ? q : 0) + d));
    qtyInput.value = w.qty;
    sync();
  };
  const dimInputs = ['L', 'W', 'H'].map((k) => input(k, 'dims'));
  const massInput = input('mass', 'mass');
  massInput.addEventListener('input', () => {
    const per = massPerItem(massInput.value, String(w.qty), massMode);
    w.mass = per ?? '';
    sync(per === null);
  });
  const seg = (items, value, pick, disabled = false) => {
    const box = el('div', { class: 'seg' });
    for (const [v, label, cls, icon] of items) {
      box.append(el('button', { type: 'button', class: `${cls || ''}${v === value ? ' on' : ''}`, 'aria-pressed': String(v === value), disabled,
        onclick: () => pick(v) }, icon ? lucide(icon) : '', label));
    }
    return box;
  };
  const massSeg = el('div');
  function drawMassSeg() {
    massSeg.replaceChildren(seg([['piece', 'mỗi kiện'], ['total', 'tất cả']], massMode, (m) => {
      massMode = m;
      massInput.value = text(massShown(String(w.mass), String(w.qty), massMode));
      drawMassSeg();
      sync();
    }, Boolean(lock('mass'))));
  }
  const rules = el('div', { class: 'lfrules' });
  function drawRules() {
    const rule = (head, sub, field, ...ctl) => el('div', { class: 'rule' }, el('div', {}, el('b', {}, head), el('span', {}, sub)),
      el('div', { class: 'ctl' }, ...ctl, lockNote(field)));
    const tiers = el('input', { type: 'text', inputMode: 'numeric', value: w.stacking.tiers ?? '', placeholder: 'số tầng', disabled: Boolean(lock('stacking')) });
    tiers.addEventListener('input', () => { w.stacking = { kind: 'limited', tiers: tiers.value }; sync(); });
    rules.replaceChildren(
      rule('Tư thế', 'Xoay quanh trục đứng luôn được', 'posture',
        seg([['upright', 'Chỉ đứng', '', 'arrow-up'], ['tippable', 'Được lật', '', 'rotate-ccw']], w.posture,
          (v) => { w.posture = v; drawRules(); sync(); }, Boolean(lock('posture')))),
      rule('Chồng lên trên', 'Số kiện cao nhất, tính cả kiện này', 'stacking',
        seg([['free', 'Tự do'], ['limited', 'Tối đa n tầng'], ['none', 'Không chồng', 'red', 'ban']], w.stacking.kind,
          (v) => { w.stacking = { kind: v, tiers: v === 'limited' ? (w.stacking.tiers || 2) : null }; drawRules(); sync(); }, Boolean(lock('stacking'))),
        ...(w.stacking.kind === 'limited' ? [tiers, el('span', { class: 'small' }, 'tầng')] : [])),
      rule('Dễ vỡ', 'Ghi cho người xếp; bộ giải không đọc', 'fragile',
        seg([[false, 'Không'], [true, 'Dễ vỡ', 'red']], w.fragile, (v) => { w.fragile = v; drawRules(); sync(); }, Boolean(lock('fragile')))));
  }
  const dimsOf = () => {
    const [L, W, H] = ['L', 'W', 'H'].map((k) => numberOrRaw(String(w[k])));
    return [L, W, H].every((x) => typeof x === 'number' && x > 0) ? { L, W, H } : null;
  };
  function sync(massPending = false) {
    const code = String(w.sku).trim();
    swatch.style.background = code ? lineCss(code) : 'var(--line2)';
    title.textContent = line ? `Sửa dòng ${line.sku}` : `Thêm dòng${code ? ` ${code}` : ''}`;
    const d = dimsOf();
    const noStack = w.stacking.kind === 'none';
    const floorOnly = w.stacking.kind === 'limited' && Number(w.stacking.tiers) === 1;
    preview.innerHTML = boxSvg(d, code, { w: 300, h: 230, label: true, noStack, floorOnly }) || '<div class="muted lfprevnone">Nhập kích thước để xem trước</div>';
    previewDims.textContent = d ? `${fmtDim(d.L)} × ${fmtDim(d.W)} × ${fmtDim(d.H)} m · ${num(Math.round(d.L * d.W * d.H * 1000) / 1000)} m³ mỗi kiện` : '';
    previewFlags.innerHTML = [w.posture === 'tippable' ? `<span class="flag blue">${ic('rotate-ccw')}Được lật</span>` : `<span class="flag">${ic('arrow-up')}Chỉ đứng</span>`,
      noStack ? `<span class="flag red">${ic('ban')}Không chồng</span>` : w.stacking.kind === 'limited' ? `<span class="flag">≤ ${esc(w.stacking.tiers)} tầng</span>` : '',
      w.fragile ? '<span class="flag red">Dễ vỡ</span>' : ''].join('');
    const one = numberOrRaw(String(w.mass)), qty = numberOrRaw(String(w.qty));
    if (massPending) massHint.textContent = 'Nhập số lượng (từ 1) để đổi ra khối lượng mỗi kiện.';
    else if (typeof one !== 'number') massHint.textContent = '';
    else if (massMode === 'piece') massHint.textContent = typeof qty === 'number' && qty > 0 ? `Tất cả: ${num(Math.round(one * qty * 1000) / 1000)} kg` : '';
    else massHint.textContent = `Mỗi kiện: ${num(Math.round(one * 1000) / 1000)} kg`;
  }
  const unitSel = el('select', {}, ...[['carton', 'Thùng'], ['piece', 'Kiện'], ['pallet', 'Pallet']].map(([v, t]) => el('option', { value: v, selected: v === w.unit }, t)));
  unitSel.addEventListener('change', () => { w.unit = unitSel.value; });
  let then = null;
  let answer = null;
  const values = () => {
    const out = {};
    if (!lock('qty')) out.qty = numberOrRaw(String(w.qty));
    if (!lock('dims')) out.dims = { L: numberOrRaw(String(w.L)), W: numberOrRaw(String(w.W)), H: numberOrRaw(String(w.H)) };
    if (!lock('mass')) out.mass = numberOrRaw(String(w.mass));
    if (!lock('posture')) out.posture = w.posture;
    if (!lock('stacking')) out.stacking = w.stacking.kind === 'limited' ? { kind: 'limited', tiers: numberOrRaw(String(w.stacking.tiers)) } : { kind: w.stacking.kind, tiers: null };
    if (!lock('fragile')) out.fragile = w.fragile;
    for (const [k, v] of Object.entries(out)) if (v === '') out[k] = null;
    // an edit sends only what changed: opening the form does not confirm a field
    if (line) for (const k of Object.keys(out)) if (JSON.stringify(out[k]) === JSON.stringify(line[k].value ?? null)) delete out[k];
    return out;
  };
  const save = (next) => {
    answer = { values: values(), then: next };
    if (manual) {
      if (!line || w.sku.trim() !== line.sku) answer.sku = w.sku.trim();
      if (!line || w.description.trim() !== line.description) answer.description = w.description.trim();
    }
    if (!line) answer.unit = w.unit;
    dialog.close();
  };
  const close = () => dialog.close();
  dialog.replaceChildren(
    el('div', { class: 'ehd' }, swatch, title, el('span', { class: 'grow' }),
      el('button', { type: 'button', class: 'ghost sm icon', 'aria-label': 'Đóng', title: 'Đóng (Esc)', onclick: close }, lucide('x'))),
    el('div', { class: 'ebd' },
      el('div', { class: 'eform' },
        el('div', { class: 'lfidqty' },
          el('label', {}, 'Mã hàng', skuInput),
          el('div', { class: 'field' }, el('label', {}, 'Số lượng (kiện)'),
            el('div', { class: 'stepper' },
              el('button', { type: 'button', 'aria-label': 'Bớt một', disabled: Boolean(lock('qty')), onclick: () => stepQty(-1) }, lucide('minus')), qtyInput,
              el('button', { type: 'button', 'aria-label': 'Thêm một', disabled: Boolean(lock('qty')), onclick: () => stepQty(1) }, lucide('plus'))), lockNote('qty'))),
        line ? el('div', { class: 'field' }, el('label', {}, 'Mô tả'), descInput)
          : el('div', { class: 'lfidqty' }, el('label', {}, 'Mô tả', descInput), el('label', {}, 'Đơn vị kiện', unitSel)),
        manual ? '' : el('span', { class: 'muted' }, 'Mã và mô tả lấy từ tài liệu, không sửa được. Giá trị bạn lưu thành đã xác nhận; nguồn vẫn giữ để xem.'),
        el('div', { class: 'field' }, el('label', {}, 'Kích thước một kiện (m)'),
          el('div', { class: 'three' }, el('label', {}, 'Dài', dimInputs[0]), el('label', {}, 'Rộng', dimInputs[1]), el('label', {}, 'Cao (khi đứng)', dimInputs[2])), lockNote('dims')),
        el('div', { class: 'field' }, el('label', {}, 'Khối lượng, cả bì'),
          el('div', { class: 'lfmass' }, massInput, el('span', {}, 'kg'), massSeg), massHint, lockNote('mass')),
        rules),
      el('div', { class: 'eprev' }, preview, previewDims, previewFlags,
        el('div', { class: 'muted lfprevhint' }, 'Hình đúng tỉ lệ, cùng màu với mã này trong kết quả. Mặt trên sọc đỏ: không chồng. Dải nâu dưới chân: chỉ sàn.'))),
    el('div', { class: 'efoot' },
      line ? el('button', { type: 'button', class: 'danger', onclick: () => { then = 'drop'; answer = { values: {}, then }; dialog.close(); } }, lucide('trash'), 'Bỏ dòng') : '',
      el('span', { class: 'grow' }),
      el('button', { type: 'button', onclick: close }, 'Hủy'),
      line ? '' : el('button', { type: 'button', onclick: () => save('again') }, 'Lưu và thêm dòng khác'),
      el('button', { type: 'button', class: 'primary lfsave', onclick: () => save(null) }, line ? 'Lưu' : 'Thêm dòng')));
  if (!document.getElementById(HATCH_ID)) document.body.insertAdjacentHTML('beforeend', HATCH_DEFS);
  document.body.append(dialog);
  drawMassSeg();
  drawRules();
  sync();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
    dialog.showModal();
    (line ? (manual ? skuInput : dialog.querySelector('input:not(:disabled)')) : skuInput)?.focus();
  });
}

async function lineChange(path, body) {
  try {
    S.lot = await api(`/api/lots/${S.lot.id}/${path}`, { method: 'POST', body: { rev: S.lot.rev, ...body } });
    S.point = null;
    drawLot();
    return true;
  } catch (e) {
    if (e.status === 409) { await loadLot(S.lot.id); drawLot(); toast('Lô vừa được sửa ở chỗ khác; đã tải lại.'); return false; }
    toast(e.message);
    return false;
  }
}

const legend = `<div class="legend" aria-hidden="true">${Object.values(STATUS).map(([c, i, t]) => `<span class="lg ${c}">${ic(i)}${t}</span>`).join('')}<span class="lg"><span class="pt">H1</span>Mã câu hỏi cần trả lời</span></div>`;

// The point shown: the one picked (open or already answered, to choose again), else the first open one.
function currentPoint(lot) {
  const picked = lot.points.find((p) => p.id === S.point);
  if (picked) return picked;
  const open = lot.points.filter((p) => !p.resolved_at);
  return open[0] || null;
}

// "Giá trị khác" of a point: a row per line, a column per field asked; a cell the point does not ask is "—".
const FIELD_ORDER = ['qty', 'dims', 'mass', 'posture', 'stacking', 'fragile'];
const FIELD_HEAD = { qty: 'Số lượng', dims: 'Dài × rộng × cao (m)', mass: 'Khối lượng (kg)', posture: 'Tư thế', stacking: 'Chồng', fragile: 'Dễ vỡ' };
function customInput(f, lineId, name) {
  const lab = esc(`${lineId} ${FIELD_WORD[name]}`);
  const at = `data-f="${esc(f)}"`;
  if (name === 'dims') return ['L', 'W', 'H'].map((k, i) => `<input ${at} data-part="${k}" inputmode="decimal" placeholder="${['dài', 'rộng', 'cao'][i]}" class="cvdim" aria-label="${lab} ${['dài', 'rộng', 'cao'][i]}">`).join('<span class="muted">×</span>');
  if (name === 'posture') return `<select ${at} aria-label="${lab}"><option value="upright">Chỉ đứng</option><option value="tippable">Được lật</option></select>`;
  if (name === 'fragile') return `<select ${at} aria-label="${lab}"><option value="false">Không dễ vỡ</option><option value="true">Dễ vỡ</option></select>`;
  if (name === 'stacking') return `<select ${at} aria-label="${lab}" data-act="cv-stack"><option value="free">Chồng tự do</option><option value="none">Không chồng</option><option value="limited">Tối đa n tầng</option></select>
      <span class="cvtiers" hidden><input ${at} data-part="tiers" inputmode="numeric" class="cvnum" aria-label="${lab}: số tầng"> tầng</span>`;
  return `<input ${at} inputmode="${name === 'qty' ? 'numeric' : 'decimal'}" class="cvnum" aria-label="${lab}">`;
}

// The fields an option leaves to enter: asked by the point, still to review, not set by the option, on a row the
// option keeps. A pallet's mass no document gives is one; the option then carries its own input for it.
function optionMissing(p, o) {
  const lines = Object.fromEntries(S.lot.lot.lines.map((x) => [x.id, x]));
  return p.fields.filter((f) => {
    const [lineId, name] = [f.slice(0, f.lastIndexOf('.')), f.slice(f.lastIndexOf('.') + 1)];
    return !(f in o.sets) && !(`${lineId}.line` in o.sets) && lines[lineId]?.[name]?.status === 'needs_review';
  });
}
const optionInputs = (fields) => `<span class="custom optmore">${fields.map((f) => {
  const [lineId, name] = [f.slice(0, f.lastIndexOf('.')), f.slice(f.lastIndexOf('.') + 1)];
  return `<span class="cvcell"><span class="muted">${esc(lineId)} · ${FIELD_HEAD[name].toLowerCase()}</span>${customInput(f, lineId, name)}</span>`;
}).join('')}</span>`;

function customInputs(p) {
  const split = (f) => [f.slice(0, f.lastIndexOf('.')), f.slice(f.lastIndexOf('.') + 1)];
  const lines = [...new Set(p.fields.map((f) => split(f)[0]))];
  const names = FIELD_ORDER.filter((n) => p.fields.some((f) => split(f)[1] === n));
  const rows = lines.map((lineId) => `<tr><th scope="row">${esc(lineId)}</th>${names.map((n) => {
    const f = `${lineId}.${n}`;
    return `<td>${p.fields.includes(f) ? `<span class="cvcell">${customInput(f, lineId, n)}</span>` : '<span class="muted">—</span>'}</td>`;
  }).join('')}</tr>`).join('');
  return `<table class="cvt"><thead><tr><th>Mã</th>${names.map((n) => `<th>${FIELD_HEAD[n]}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
}

function readCustom(root) {
  const values = {};
  for (const node of root.querySelectorAll('[data-f]')) {
    const f = node.dataset.f;
    const name = f.slice(f.lastIndexOf('.') + 1);
    const part = node.dataset.part;
    if (name === 'dims') {
      values[f] = values[f] || {};
      values[f][part] = parseDecimal(node.value);
    } else if (name === 'stacking') {
      values[f] = values[f] || {};
      if (part === 'tiers') values[f].tiers = node.value.trim() ? Number(node.value) : null;
      else values[f].kind = node.value;
    } else if (name === 'posture') values[f] = node.value;
    else if (name === 'fragile') values[f] = node.value === 'true';
    else if (name === 'qty') values[f] = node.value.trim() ? Number(node.value.trim()) : null;
    else values[f] = parseDecimal(node.value);
  }
  for (const v of Object.values(values)) if (v && v.kind && v.kind !== 'limited') v.tiers = null;
  return values;
}

function reviewPanel(body) {
  const lot = body.lot;
  const p = currentPoint(lot);
  const done = lot.points.filter((x) => x.resolved_at).length;
  const total = lot.points.length;
  const items = lot.points.map((x) => `<li><button class="rvitem" data-act="goto-point" data-id="${x.id}" ${p && x.id === p.id ? 'aria-current="step"' : ''}>
      ${x.resolved_at ? `<span class="pt" style="background:var(--ok)">${ic('check')}</span>` : `<span class="pt">${qid(x.id)}</span>`}
      <span><b>${esc(x.title)}</b><span class="muted">${x.resolved_at ? `Đã xác nhận bởi ${esc(x.resolved_by)}` : esc(x.question.slice(0, 90))}</span></span></button></li>`).join('');
  const open = lot.points.filter((x) => !x.resolved_at);
  const idx = p ? open.indexOf(p) : -1;
  const next = open[idx + 1] || open.find((x) => x !== p);
  const redo = Boolean(p?.resolved_at);
  const picked = redo ? p.chosen : 0;  // an answer of the user's own (chosen null) shows "Giá trị khác"
  const opts = p ? p.options.map((o, i) => `<label class="opt${o.sources.length ? '' : ' nosrc'}"><input type="radio" name="opt" value="${i}" ${i === picked ? 'checked' : ''}><span class="ov">${esc(o.label)}</span>
      <span class="os">${o.sources.map((s) => `${ic('link')}${esc(s.file)} · ${esc(s.where)}${s.raw ? ` <q>${esc(s.raw)}</q>` : ''}`).join(' · ')}${(() => { const m = optionMissing(p, o); return m.length ? optionInputs(m) : ''; })()}</span></label>`).join('') : '';
  const bodyHtml = p ? `<div class="rvhd"><span class="pt">${qid(p.id)}</span><h3>${esc(p.title)}</h3><span class="spacer"></span>
        <button class="sm icon" data-act="prev-point" aria-label="Câu hỏi trước" ${idx <= 0 ? 'disabled' : ''}>${ic('chevron-left')}</button>
        <button class="sm icon" data-act="next-point" aria-label="Câu hỏi sau" ${idx >= open.length - 1 ? 'disabled' : ''}>${ic('chevron-right')}</button></div>
      <p class="rvq">${esc(p.question)}</p>
      ${redo ? `<p class="muted">${ic('circle-check')}Đã xác nhận bởi ${esc(p.resolved_by)} lúc ${when(p.resolved_at)}. Chọn lại rồi lưu để đổi.</p>` : ''}
      <fieldset class="opts" id="opts"><legend class="sr-only">${esc(p.title)}</legend>${opts}
        <label class="opt optcustom"><input type="radio" name="opt" value="custom" ${p.options.length && picked !== null ? '' : 'checked'}><span class="ov">Giá trị khác</span><span class="os custom">${customInputs(p)}</span></label></fieldset>
      <div class="rvacts"><button class="primary" data-act="answer" data-id="${p.id}">${ic('check')}${redo ? 'Lưu lựa chọn mới' : next ? `Xác nhận và sang ${qid(next.id)}` : 'Xác nhận'}</button>
        ${next && !redo ? `<button class="ghost" data-act="later" data-id="${next.id}">Để sau</button>` : ''}
        <span class="spacer"></span><span class="muted">Trả lời trong chat cũng được.</span></div><div id="rverr" class="err" role="alert"></div>`
    : `<div class="rvdone"><p>Mọi câu hỏi đã trả lời. Kiểm tra bảng dữ liệu bên dưới; các ô còn lại do tài liệu ghi khớp nhau.</p>
      <button class="primary" data-act="confirm-lot">${ic('circle-check')}Xác nhận dữ liệu lô</button><div id="rverr" class="err" role="alert"></div></div>`;
  return `<section class="box rvpanel" aria-labelledby="rvh"><div class="rvlist"><div class="rvlhd"><h2 id="rvh">Câu hỏi</h2><span class="muted">${done} / ${total} xong</span></div>
      <div class="bar" aria-hidden="true"><div style="width:${total ? (100 * done) / total : 100}%"></div></div><ol>${items}</ol></div>
    <div class="rvbody">${bodyHtml}</div></section>`;
}

function excludedBox(lot) {
  if (!lot.excluded.length) return '';
  const rows = lot.excluded.map((e) => {
    const dropped = e.reason.match(/^Người dùng bỏ dòng (.+) khỏi lô$/)?.[1];  // src.lot.review.DROPPED_REASON
    const back = dropped ? ` <button class="sm" data-act="restore-line" data-id="${esc(dropped)}">${ic('undo')}Đưa lại vào lô</button>` : '';
    return `<p><b>${esc(e.sku)}</b> ${esc(e.description)}: ${esc(e.reason)}${e.sources.length ? ` (${e.sources.map((s) => `${esc(s.file)} · ${esc(s.where)}`).join('; ')})` : ''}.${back}</p>`;
  }).join('');
  return `<details class="box excl"><summary>Không đưa vào lô <span class="muted">${lot.excluded.length} mã</span></summary>${rows}
    <p class="help">Một mã chỉ thành câu hỏi khi các tài liệu ghi mâu thuẫn về nó.</p></details>`;
}

// The empty data table: why it is empty, when documents are there.
function emptyText(body) {
  const docs = body.documents;
  if (docs.some((d) => d.status === 'failed')) return 'Chưa có dòng nào: có tài liệu chưa đọc được. Bấm "Đọc lại" ở tài liệu đó, hoặc nhập tay từng mã hàng.';
  if (docs.length) return 'Chưa có bảng kê hàng: số lượng của mỗi mã lấy từ bảng kê hàng. Thả bảng kê hàng vào đây, hoặc nhập tay từng mã hàng.';
  return 'Thả bảng kê hàng, thông số kỹ thuật hoặc ảnh nhãn thùng vào đây, hoặc nhập tay từng mã hàng.';
}

function drawLot() {
  const body = S.lot;
  const state = statusOf(body);
  const t = totals(body.lot);
  const tool = toolbar([['#/lo-hang', 'Lô hàng']], body.name, `${statusFlag(body)}${body.parent_id ? `<span class="src">Bản thử: ${esc(body.note || '')}</span>` : ''}${runButton(body)}`, lotActs(body));
  let top = '';
  if (state === 'points' || state === 'rest') top = reviewPanel(body);
  else if (state === 'confirmed') {
    const edit = body.lot.points.length
      ? `<button class="sm" data-act="edit-points" aria-expanded="${S.editPoints}">${ic('pencil')}${S.editPoints ? 'Đóng các câu hỏi đã trả lời' : 'Sửa câu trả lời'}</button>` : '';
    top = `<div class="alert okay"><div class="ahd">${ic('circle-check')}Dữ liệu lô đã xác nhận</div>
      <span>${t.lines} dòng · ${fmt(t.pieces, 0)} kiện · ${fmt(t.kg, 0)} kg · ${fmt(t.m3, 1)} m³</span><span class="spacer"></span><span class="muted">Mỗi trường giữ nguồn và người xác nhận</span>${edit}</div>
      ${S.editPoints && body.lot.points.length ? reviewPanel(body) : ''}`;
  }
  let table;
  if (!body.lot.lines.length) {
    const sk = Array.from({ length: 4 }, () => '<div class="skrow"><span class="sk" style="width:6px;height:28px"></span><span class="sk" style="width:120px;height:14px"></span><span class="sk" style="width:80px;height:14px"></span><span class="sk" style="width:140px;height:14px"></span><span class="sk" style="width:60px;height:14px"></span></div>').join('');
    table = waiting(body)
      ? `<section class="box flush" aria-busy="true"><div class="boxhd"><h2>Dữ liệu lô</h2><span class="muted">đang trích xuất…</span></div>${sk}</section>`
      : `<section class="box"><div class="empty">${emptyText(body)}
        <div class="emptyacts"><button data-act="pick">${ic('folder-open')}Chọn file</button><button class="primary" data-act="add-line">${ic('plus')}Thêm dòng</button></div></div></section>`;
  } else {
    table = `<section class="box"><div class="boxhd"><h2>Dữ liệu lô</h2><span class="muted">${t.lines} dòng · ${fmt(t.pieces, 0)} kiện</span><span class="spacer"></span>${legend}</div>
      ${lotTable(body)}<div class="tblfoot"><button class="sm" data-act="add-line">${ic('plus')}Thêm dòng</button>
      <p class="help">Bấm một ô để xem nguồn. Đơn vị đã đổi về m và kg; giá trị gốc nằm ở nguồn.</p></div></section>`;
  }
  const errs = body.documents.filter((d) => d.status === 'failed');
  const alert = errs.length ? `<div class="alert bad" role="alert">${errs.map((d) => `<div>${ic('circle-alert')}<b>${esc(d.name)}</b>: ${esc(d.error)}. Bấm "Đọc lại" ở tài liệu đó.</div>`).join('')}</div>` : '';
  paint(workspace(tool, `${alert}${docsStrip(body)}${top}${table}${excludedBox(body.lot)}${runsBox(body)}`));
  schedulePoll(body.id);
  if (S.openAdd) { S.openAdd = false; app.querySelector('[data-act="add-line"]')?.click(); }
}

// The lot's runs (and its what-if copies'), newest first, under the data: the last three, the rest on request; a
// row opens the run's result.
const RUNS_SHOWN = 3;
function runsBox(body) {
  if (!body.runs.length) return '';
  const names = Object.fromEntries(body.family.map((f) => [f.id, f.name]));
  const nums = runNumbers(body.runs);
  const shown = S.allRuns ? body.runs : body.runs.slice(0, RUNS_SHOWN);
  const rows = shown.map((r) => {
    const lotId = r.lot_id ?? body.id;
    const outcome = r.status === 'done' ? esc(runOutcome(r)) : `<span class="muted">${esc(runOutcome(r))}</span>`;
    const copy = lotId !== body.id ? ` <span class="muted">(${esc(names[lotId] || r.lot_name)})</span>` : '';
    const href = `#/lo/${lotId}/ket-qua/${esc(r.job_id)}`;
    return `<tr data-href="${href}"><td><a class="rowlink" href="${href}">Lần ${nums[r.job_id]}</a>${copy}</td>
      <td>${r.mode === 'b' ? 'Xếp vào container có sẵn' : 'Chọn container rẻ nhất'}</td><td>${outcome}</td><td class="muted">${when(r.created_at)}</td>${ROW_GO}</tr>`;
  }).join('');
  const more = body.runs.length > RUNS_SHOWN
    ? `<span class="spacer"></span><button class="sm ghost" data-act="all-runs" aria-expanded="${S.allRuns}">${S.allRuns ? 'Thu gọn' : `Xem tất cả ${body.runs.length} lần`}</button>` : '';
  return `<section class="box flush"><div class="boxhd"><h2>Các lần xếp</h2><span class="muted">${body.runs.length}</span>${more}</div>
    <table class="cmp"><thead><tr><th>Lần</th><th>Cách xếp</th><th>Kết quả</th><th>Lúc</th><th></th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

async function answerPoint(button) {
  const root = button.closest('.rvbody');
  const picked = root.querySelector('input[name="opt"]:checked')?.value;
  const req = { rev: S.lot.rev };
  const chosen = root.querySelector('input[name="opt"]:checked')?.closest('.opt');
  if (picked === 'custom') req.values = readCustom(chosen);
  else {
    req.choice = Number(picked);
    const more = Object.entries(readCustom(chosen)).filter(([, v]) => v !== null && !Number.isNaN(v));  // blank: the server names it
    if (more.length) req.values = Object.fromEntries(more);
  }
  try {
    button.disabled = true;
    S.lot = await api(`/api/lots/${S.lot.id}/points/${button.dataset.id}`, { method: 'POST', body: req });
    S.point = null;
    drawLot();
  } catch (e) {
    button.disabled = false;
    if (e.status === 409) { await loadLot(S.lot.id); drawLot(); toast('Lô vừa được sửa ở chỗ khác; đã tải lại.'); return; }
    $('rverr').textContent = e.message;
  }
}

async function confirmLot(lotId = S.lot.id) {
  try {
    const cur = lotId === S.lot?.id ? S.lot : await api(`/api/lots/${lotId}`);
    const body = await api(`/api/lots/${lotId}/confirm`, { method: 'POST', body: { rev: cur.rev } });
    if (lotId === S.lot?.id) { S.lot = body; drawLot(); }
    toast('Đã xác nhận dữ liệu lô.');
  } catch (e) {
    if ($('rverr')) $('rverr').textContent = e.message; else toast(e.message);
  }
}

// ---- chat ---------------------------------------------------------------------------------------------------------
const para = (text) => esc(text).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
// A question's code: H + its number; in the assistant's text a chip that opens it.
const qid = (n) => `H${n}`;
const qchip = (n) => `<button class="pt qchip" data-act="goto-point" data-id="${n}" title="Mở câu hỏi H${n}">H${n}</button>`;
const withChips = (html) => html.replace(/\bH(\d{1,3})\b/g, (_, n) => qchip(n));
const agentMsg = (html, extra = '', q = false) => `<div class="msg agent${q ? ' q' : ''}"><div class="who">${ic('bot')}Trợ lý</div>${html}${extra}</div>`;

// A value of the lot equals a proposed one: every key the proposal gives (a size, a stacking) is the same.
const sameValue = (has, want) => (want && typeof want === 'object'
  ? !!has && Object.keys(want).every((k) => sameValue(has[k], want[k])) : has === want);

// The lot already holds what a proposal asks: the user clicked it, or did the same on the page. Its button is
// then shown done, so a row is not added twice. A proposal for another lot (a what-if made in the turn) is not judged.
function proposalDone(p) {
  const body = S.lot;
  if (!body || body.id !== p.lot_id) return false;
  const lot = body.lot;
  if (p.kind === 'confirm') return statusOf(body) === 'confirmed';
  if (p.kind === 'add_line') return lot.lines.some((x) => x.sku === p.body.sku);
  if (p.kind === 'edit_line') {
    const line = lot.lines.find((x) => x.id === p.line_id);
    return !!line && Object.entries(p.body.values).every(([k, v]) => line[k]?.status === 'confirmed' && sameValue(line[k].value, v));
  }
  return !!lot.points.find((x) => x.id === p.point_id)?.resolved_at;
}

function proposalButtons(props) {
  if (!props?.length) return '';
  return `<div class="prop">${props.map((p) => {
    const text = p.kind === 'confirm' ? 'dữ liệu lô' : p.kind === 'answer' ? `${qid(p.point_id)}: ${esc(p.label)}` : esc(p.label);
    if (proposalDone(p)) return `<button class="sm" disabled>${ic('check')}Đã xác nhận ${text}</button>`;
    if (p.kind === 'confirm') return `<button class="sm primary" data-act="prop-confirm" data-lot="${p.lot_id}">${ic('check')}Xác nhận ${text}</button>`;
    if (p.kind === 'add_line' || p.kind === 'edit_line') return `<button class="sm" data-act="prop-line" data-lot="${p.lot_id}" data-line="${esc(p.line_id || '')}" data-body="${esc(JSON.stringify(p.body))}">${ic('check')}Xác nhận ${text}</button>`;
    return `<button class="sm" data-act="prop-answer" data-lot="${p.lot_id}" data-point="${p.point_id}" data-choice="${p.choice ?? ''}" data-values="${esc(JSON.stringify(p.values || null))}">${ic('check')}Xác nhận ${text}</button>`;
  }).join('')}</div>`;
}

function messageHtml(m) {
  if (m.role === 'user') return `<div class="msg user">${para(m.content.text)}</div>`;
  const c = m.content;
  const actions = (c.actions || []).map((a) => `<div class="tool">${ic('refresh-cw')}${esc(a)}</div>`).join('');
  const warn = c.unverified?.length ? `<div class="warnnum">${ic('triangle-alert')}Số chưa kiểm được từ dữ liệu: ${c.unverified.map(esc).join(', ')}</div>` : '';
  const links = (c.links || []).join('');
  return agentMsg(withChips(para(c.text || '')), `${actions}${proposalButtons(c.proposals)}${links}${warn}`);
}

function questionCard() {
  const body = S.lot;
  if (!body) return '';
  const p = currentPoint(body.lot);
  if (!p || p.resolved_at) return '';
  const buttons = p.options.map((o, i) => `<button class="sm" data-act="chat-opt" data-point="${p.id}" data-choice="${i}">${esc(o.label)}</button>`).join('');
  const open = body.lot.points.filter((x) => !x.resolved_at).length;
  return agentMsg(`<p><b>${qchip(p.id)} ${esc(p.title)}</b></p><p>${esc(p.question)}</p>`,
    `<div class="qr">${buttons}</div><div class="tool">${ic('info')}Còn ${open} câu hỏi; chọn ở đây, ở bảng bên trái, hoặc trả lời bằng lời.</div>`, true);
}

function chatColumn() {
  const lotId = S.lot?.id;
  const greeting = agentMsg(!lotId ? '<p>Chào bạn. Thả bảng kê hàng, thông số kỹ thuật và ảnh nhãn của lô vào bên trái, mình đọc rồi hỏi lại chỗ nào chưa rõ. Không có tài liệu thì nhập tay từng mã hàng.</p>'
    : S.lot.parent_id ? '<p>Đây là bản thử: đổi số lượng, bỏ hay thêm mã hàng ở đây rồi xếp lại để so với lô gốc; lô gốc giữ nguyên. Hỏi mình bất cứ lúc nào.</p>'
    : S.lot.documents.length ? '<p>Mình đọc tài liệu của lô, đặt câu hỏi ở chỗ thiếu hoặc mâu thuẫn, rồi xếp lô hàng khi bạn trả lời đủ. Hỏi mình bất cứ lúc nào.</p>'
    : S.lot.lot.lines.length ? '<p>Lô này nhập tay. Nhờ mình thêm hay sửa mã hàng, xếp lô hàng, hoặc thả tài liệu vào để mình đọc. Hỏi mình bất cứ lúc nào.</p>'
      : '<p>Lô này chưa có tài liệu. Nhập từng mã hàng ở bảng bên trái, hoặc thả bảng kê hàng, thông số kỹ thuật, ảnh nhãn vào để mình đọc. Hỏi mình bất cứ lúc nào.</p>');
  const log = S.chat.map(messageHtml).join('');
  const live = S.live ? agentMsg(S.live.actions.map((a) => `<div class="tool">${ic('refresh-cw')}${esc(a)}</div>`).join('') || '', '<div class="typing" aria-label="Trợ lý đang trả lời"><span></span><span></span><span></span></div>') : '';
  const open = S.lot ? S.lot.lot.points.filter((x) => !x.resolved_at).length : 0;
  return `<aside class="chat" aria-label="Trợ lý">
    <div class="rail"><button class="ghost railbtn" data-chat="open" aria-label="Mở trợ lý${open ? `, ${open} câu hỏi đang chờ` : ''}">${ic('bot')}${open ? `<span class="pt">${open}</span>` : ''}</button><span class="railtxt">Trợ lý</span></div>
    <div class="chathd">${ic('bot')}<h2>Trợ lý</h2><span class="spacer"></span>
      <button class="ghost icon" data-chat="close" aria-label="Thu gọn trợ lý">${ic('panel-right')}</button></div>
    <div class="chatlog" id="chatlog" aria-live="polite">${greeting}${log}${live}${S.live ? '' : questionCard()}</div>
    <form class="chatin" id="chatin">
      <textarea id="chattext" aria-label="Tin nhắn cho trợ lý" ${lotId ? 'aria-describedby="chathint"' : 'disabled'} placeholder="${lotId ? 'Trả lời hoặc hỏi trợ lý, ví dụ: nếu bỏ SKU-B thì sao?' : 'Tạo lô trước: thả tài liệu hoặc nhập tay'}">${esc(S.draft[lotId] || '')}</textarea>
      <button class="primary icon" aria-label="Gửi" ${lotId && !S.sending ? '' : 'disabled'}>${ic('send')}</button>
      ${lotId ? '<p class="chathint" id="chathint">Enter gửi · Shift+Enter xuống dòng</p>' : ''}
    </form></aside>`;
}

function redrawChat() {
  const aside = app.querySelector('aside.chat');
  if (!aside) return;
  keepChatInput(() => { aside.outerHTML = chatColumn(); });
  scrollChat();
}
function scrollChat() { const log = $('chatlog'); if (log) log.scrollTop = log.scrollHeight; }

async function sendChat(text) {
  const lotId = S.lot.id;
  S.sending = true;
  S.chat.push({ role: 'user', content: { text } });
  S.live = { actions: [] };
  redrawChat();
  let final = null;
  const links = [];
  try {
    const r = await fetch(`/api/lots/${lotId}/chat`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    if (r.status === 401) { location.assign('/login'); return; }
    if (!r.ok) throw new Error((await r.json())?.message || `Lỗi ${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, cut).trim();
        buf = buf.slice(cut + 2);
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === 'action') { S.live.actions.push(ev.text); redrawChat(); }
        else if (ev.type === 'lot') links.push(`<div class="tool">${ic('link')}<a class="lotlink" href="#/lo/${ev.lot_id}">Mở bản lô mới</a></div>`);
        else if (ev.type === 'run') links.push(`<div class="tool">${ic('play')}<a class="lotlink" href="#/lo/${ev.lot_id}/ket-qua/${ev.job_id}">Xem lần chạy</a></div>`);
        else if (ev.type === 'message' || ev.type === 'error') final = ev;
      }
    }
  } catch (e) {
    final = { type: 'error', message: e.message };
  }
  S.sending = false;
  S.live = null;
  if (final?.type === 'message') S.chat.push({ role: 'assistant', content: { ...final, links } });
  else S.chat.push({ role: 'assistant', content: { text: final?.message || 'Trợ lý không trả lời.', actions: [] } });
  if (S.lot?.id === lotId) {
    const body = await api(`/api/lots/${lotId}`);
    if (body.rev !== S.lot.rev) { S.lot = body; if (routeOf().name === 'lot') { drawLot(); return; } }
  }
  redrawChat();
  const run = links.find((l) => l.includes('ket-qua'));
  if (run) location.hash = run.match(/href="([^"]+)"/)[1];
}

async function proposalAnswer(btn) {
  const lotId = Number(btn.dataset.lot);
  try {
    const cur = await api(`/api/lots/${lotId}`);
    const req = { rev: cur.rev };
    if (btn.dataset.choice !== '') req.choice = Number(btn.dataset.choice);
    const values = JSON.parse(btn.dataset.values || 'null');
    if (values) req.values = values;
    const body = await api(`/api/lots/${lotId}/points/${btn.dataset.point}`, { method: 'POST', body: req });
    btn.disabled = true;
    toast(`Đã xác nhận ${qid(btn.dataset.point)}.`);
    if (S.lot?.id === lotId) { S.lot = body; if (routeOf().name === 'lot') drawLot(); else redrawChat(); }
  } catch (e) {
    toast(e.message);
  }
}

// A row added or changed in the chat: posted to the same routes as the table's form.
async function proposalLine(btn) {
  const lotId = Number(btn.dataset.lot);
  const line = btn.dataset.line;
  try {
    const cur = await api(`/api/lots/${lotId}`);
    const req = { ...JSON.parse(btn.dataset.body), rev: cur.rev };
    const body = await api(line ? `/api/lots/${lotId}/lines/${encodeURIComponent(line)}` : `/api/lots/${lotId}/lines`, { method: 'POST', body: req });
    btn.disabled = true;
    toast(line ? `Đã sửa dòng ${line}.` : `Đã thêm dòng ${req.sku}.`);
    if (S.lot?.id === lotId) { S.lot = body; if (routeOf().name === 'lot') drawLot(); else redrawChat(); }
  } catch (e) {
    toast(e.message);
  }
}

// ---- 4. run setup -------------------------------------------------------------------------------------------
async function screenRun(id) {
  const body = await loadLot(id);
  const t = totals(body.lot);
  const ready = statusOf(body) === 'confirmed';
  const tool = toolbar(lotCrumbs(body), 'Xếp lô hàng', `${statusFlag(body)}`);
  fillFor(body);
  const mode = (value, title, text) => `<label class="mode"><input class="sr-only" type="radio" name="mode" value="${value}" ${(S.mode === 'b') === (value === 'b') ? 'checked' : ''}>
      <span class="mk" aria-hidden="true">${ic('circle-check')}</span><div><b>${title}</b><span>${text}</span></div></label>`;
  const modes = `<fieldset class="modes"><legend class="sr-only">Cách xếp</legend>
      ${mode('a', 'Chọn container rẻ nhất', 'Lô cố định. Bộ giải chọn loại và số container, xếp hết hàng, tổng cước nhỏ nhất.')}
      ${mode('b', 'Xếp vào container có sẵn', 'Container có sẵn cố định, xếp nhiều hàng nhất theo thứ tự ưu tiên; báo hàng còn lại.')}</fieldset>`;
  const side = `<div class="col sticky"><section class="box"><h2>Lô</h2><dl class="sumrows">
        <dt>Dòng</dt><dd>${t.lines}</dd><dt>Kiện</dt><dd>${fmt(t.pieces, 0)}</dd><dt>Khối lượng</dt><dd>${fmt(t.kg, 0)} kg</dd><dt>Thể tích</dt><dd>${fmt(t.m3, 1)} m³</dd>
        <dt>Dữ liệu</dt><dd class="${ready ? 'ok' : ''}">${ready ? 'Đã xác nhận' : 'Chưa xác nhận đủ'}</dd></dl></section>
      <section class="box"><h2>Thời gian chạy</h2>
        <div class="timeopts" id="timeopts" role="group" aria-label="Thời gian chạy tối đa">${TIME_LEVELS.map((l) => `<button class="${l.seconds === RUN_S ? 'on' : ''}" aria-pressed="${l.seconds === RUN_S}" data-t="${l.seconds}"><b>${l.label}</b><span>${levelHint(l, RUN_S)}</span></button>`).join('')}<button aria-pressed="false" data-t="custom"><b>Khác…</b><span>${RUN_RANGE.join('–')} giây</span></button></div>
        <label class="tlcustom" id="tlcustom" hidden>Số giây<input id="tl" type="text" inputmode="numeric" autocomplete="off" value="90"></label>
        <div class="promise">${ic('clock')}<span id="promisetext">${promiseLine(RUN_S)}</span></div>
        <p class="help" style="margin:6px 0 12px">Phương án nào cũng qua kiểm tra ràng buộc trước khi hiện.</p>
        <button class="primary block" data-act="start-run" id="runbtn" ${ready ? '' : 'disabled'}>${ic('play')}Xếp lô hàng</button>
        ${ready ? '' : '<p class="runreason">Xác nhận đủ dữ liệu lô thì mới chạy được</p>'}<div id="runerr" class="err" role="alert"></div></section>
      ${advancedBox(body)}</div>`;
  paint(workspace(tool, `${modes}<div class="setup"><div class="col" id="setupmid">${setupMid(body)}</div>${side}</div>`));
  advSummary();
}

// The time levels: a label and a hint each, the promise under them.
const RUN_S = 60;  // the level picked first (the server's DEFAULT_RUN_S)
const RUN_RANGE = [10, 600];  // seconds the service takes (src/web/mode.py SERVICE.time_range)
const promiseLine = (s) => `Thường xong trong khoảng <b>${Number.isFinite(s) && s > 0 ? promiseText(s) : '—'}</b>. Thời gian dài hơn có thể cho phương án tốt hơn.`;
// The time limit picked: a level, or "Khác…" with the seconds typed; null after marking a number out of range.
function runTime() {
  const on = app.querySelector('#timeopts [aria-pressed="true"]');
  if (on.dataset.t !== 'custom') return Number(on.dataset.t);
  const s = parseDecimal($('tl').value);
  if (s !== null && s >= RUN_RANGE[0] && s <= RUN_RANGE[1]) return s;
  $('tl').classList.add('lferr');
  $('runerr').textContent = `Thời gian phải từ ${RUN_RANGE[0]} đến ${RUN_RANGE[1]} giây.`;
  return null;
}

// "Thiết lập nâng cao": folded, one line while folded; the tipping flag (on when a
// line may tip, locked when none may), the gap δ and the support ratio α. Kept per lot while the page is open.
const DELTA_TIP = 'Khe hở tối thiểu giữa hai kiện đứng cạnh nhau, để xe nâng và tay người luồn vào khi xếp, dỡ. Không áp với vách container, không áp theo phương đứng (kiện chồng thì chạm mặt).';
const ALPHA_TIP = 'Tỉ lệ đỡ tối thiểu (0–1): phần diện tích đáy kiện phải tựa lên sàn hoặc mặt trên kiện bên dưới. 1 = đỡ trọn; 0,8 = được nhô ra 20%.';
function advFor(body) {
  const canTip = body.lot.lines.some((l) => l.posture.value === 'tippable');
  if (S.adv?.lotId !== body.id) S.adv = { lotId: body.id, delta: '0,05', alpha: '0,8', orient: true, open: false };
  return { ...S.adv, canTip };
}
function advancedBox(body) {
  const a = advFor(body);
  return `<section class="box"><details class="adv" id="adv" ${a.open ? 'open' : ''}>
      <summary><span><h2>Thiết lập nâng cao</h2><span class="muted advsum" id="advsum"></span></span></summary>
      <label class="chk" style="margin-top:8px"><input id="orient" type="checkbox" autocomplete="off" ${a.canTip && a.orient ? 'checked' : ''} ${a.canTip ? '' : 'disabled'}> Cho bộ giải chủ động lật kiện</label>
      <div class="muted">${a.canTip ? 'Chỉ lật các mã "Được lật"; tắt nếu hàng thật không đặt nằm hay dựng cao được.' : 'Không mã nào "Được lật": bộ giải chỉ xoay quanh trục đứng.'}</div>
      <div class="row" style="margin-top:8px">
        <div class="tipwrap"><label for="delta" style="margin-top:0">δ (m)${infoTip(DELTA_TIP)}</label><input id="delta" type="text" inputmode="decimal" autocomplete="off" value="${esc(a.delta)}">
          <div class="help">Khe hở giữa hai kiện cạnh nhau; không áp với vách, không áp theo phương đứng.</div></div>
        <div class="tipwrap end"><label for="alpha" style="margin-top:0">α${infoTip(ALPHA_TIP)}</label><input id="alpha" type="text" inputmode="decimal" autocomplete="off" value="${esc(a.alpha)}">
          <div class="help">Phần đáy kiện phải được đỡ: 1 = đỡ trọn, 0,8 = nhô ra 20%.</div></div>
      </div></details></section>`;
}
function advSummary() {
  const d = parseDecimal($('delta')?.value), a = parseDecimal($('alpha')?.value);
  const orient = $('orient');
  if (!orient) return;
  $('advsum').textContent = [`khe hở ${d === null ? '?' : `${num(d)} m`}`, `đỡ ${a === null ? '?' : `${fmt(a * 100, 0)}%`}`,
    orient.checked && !orient.disabled ? 'chủ động lật' : 'không chủ động lật'].join(' · ');
}
// δ, α and the flag of the form, checked; null after marking the box that is wrong.
function advValues() {
  const d = parseDecimal($('delta').value), a = parseDecimal($('alpha').value);
  for (const [id, v, ok, msg] of [['delta', d, d !== null && d >= 0, 'δ phải là một số từ 0 (ví dụ 0,05).'],
    ['alpha', a, a !== null && a >= 0 && a <= 1, 'α phải là một số từ 0 đến 1 (ví dụ 0,8).']]) {
    if (!ok) { $(id).classList.add('lferr'); $('adv').open = true; $('runerr').textContent = msg; return null; }
  }
  return { delta: d, alpha: a, orient: $('orient').disabled ? null : $('orient').checked };
}

// Mode B's settings of the open lot (docs/product/ux.md §4): containers at hand per type, line ids by priority, partial.
function fillFor(body) {
  if (S.fill?.lotId === body.id) return S.fill;
  const types = body.containers.map((c) => c.id);
  const first = types.includes('40HC') ? '40HC' : types[0];
  S.fill = { lotId: body.id, fleet: Object.fromEntries(types.map((t) => [t, t === first ? 1 : 0])),
    priority: body.lot.lines.map((l) => l.id), partial: true };
  return S.fill;
}

function setupMid(body) {
  if (S.mode !== 'b') return ratesBox(body);
  const f = fillFor(body);
  const line = (id) => body.lot.lines.find((l) => l.id === id) || { sku: id, description: '' };
  const fleet = body.containers.map((c) => `<tr><td><b>${esc(c.id)}</b></td><td>${fmtDim(c.L)} × ${fmtDim(c.W)} × ${fmtDim(c.H)}</td><td class="num">${fmt(c.max_mass, 0)}</td>
      <td class="num"><button data-act="fleet-dec" data-t="${esc(c.id)}" aria-label="Bớt ${esc(c.id)}" ${f.fleet[c.id] ? '' : 'disabled'}>−</button>
      <b aria-live="polite" style="display:inline-block;min-width:2em;text-align:center">${f.fleet[c.id] || 0}</b><button data-act="fleet-inc" data-t="${esc(c.id)}" aria-label="Thêm ${esc(c.id)}">+</button></td></tr>`).join('');
  const prio = f.priority.map((id, i) => {
    const l = line(id);
    return `<tr><td class="num">${i + 1}</td><td style="border-left:4px solid ${lineCss(l.sku)}"><b>${esc(l.sku)}</b> <span class="muted">${esc(l.description)}</span></td>
      <td class="num">${fmt(l.qty?.value ?? 0, 0)}</td><td class="num"><button data-act="prio-up" data-i="${i}" aria-label="Đưa ${esc(l.sku)} lên" ${i ? '' : 'disabled'}>${ic('chevron-up')}</button>
      <button data-act="prio-down" data-i="${i}" aria-label="Đưa ${esc(l.sku)} xuống" ${i < f.priority.length - 1 ? '' : 'disabled'}>${ic('chevron-down')}</button></td></tr>`;
  }).join('');
  return `<section class="box"><div class="boxhd"><h2>Container có sẵn</h2></div>
      <table class="ftab cmp"><thead><tr><th>Loại</th><th>Kích thước trong (m)</th><th class="num">Tải tối đa (kg)</th><th class="num">Số lượng</th></tr></thead><tbody>${fleet}</tbody></table>
      <p class="help">Bộ giải dùng tối đa số container này; khi xếp vào container có sẵn, cước không dùng.</p></section>
    <section class="box"><div class="boxhd"><h2>Thứ tự ưu tiên</h2></div>
      <table class="ftab cmp"><thead><tr><th class="num">#</th><th>Mã hàng</th><th class="num">Số kiện</th><th class="num">Đổi chỗ</th></tr></thead><tbody>${prio}</tbody></table>
      <p><label><input type="checkbox" data-act="partial" ${f.partial ? 'checked' : ''}> Cho xếp một phần mã hàng</label></p>
      <p class="help">Bộ giải xếp nhiều kiện nhất của dòng số 1, rồi giữ số đó mà xếp nhiều nhất dòng số 2, và tiếp tục. Tắt ô trên thì mỗi dòng lên đủ hoặc không lên kiện nào.</p></section>`;
}

// Redraws the middle column, focus on the same button (or its enabled neighbour when it just became disabled).
function redrawSetup() {
  const [key] = focusKeys(document.activeElement);
  $('setupmid').innerHTML = setupMid(S.lot);
  const node = key && app.querySelector(key);
  (node?.disabled ? node.parentElement.querySelector('button:not(:disabled)') : node)?.focus({ preventScroll: true });
}

function ratesBox(body) {
  return `<section class="box"><div class="boxhd"><h2>Bảng cước</h2></div>
      <table class="ftab cmp"><thead><tr><th>Dùng</th><th>Loại</th><th>Kích thước trong (m)</th><th class="num">Tải tối đa (kg)</th><th class="num">Cước (USD)</th></tr></thead><tbody>
      ${body.containers.map((c, i) => `<tr><td><input type="checkbox" data-ct="${i}" checked aria-label="Dùng ${esc(c.id)}"></td><td><b>${esc(c.id)}</b></td><td>${fmtDim(c.L)} × ${fmtDim(c.W)} × ${fmtDim(c.H)}</td><td class="num">${fmt(c.max_mass, 0)}</td>
        <td class="num"><input class="money" type="text" inputmode="decimal" data-cost="${i}" value="${fmt(c.cost, 2)}" aria-label="Cước ${esc(c.id)}"></td></tr>`).join('')}
      </tbody></table><p class="help">Cước là số bạn nhập; bộ giải không tự đặt giá. Bảng mặc định là số giả lập.</p></section>`;
}

async function startRun(btn) {
  const body = S.lot;
  if (S.mode === 'b') {
    const f = fillFor(body);
    if (!Object.values(f.fleet).some((n) => n > 0)) { $('runerr').textContent = 'Đặt ít nhất một container có sẵn.'; return; }
    const knobs = advValues();
    const t = runTime();
    if (!knobs || t === null) return;
    try {
      btn.disabled = true;
      const fill = { fleet: f.fleet, priority: f.priority, partial: f.partial };
      const job = await api(`/api/lots/${body.id}/runs`, { method: 'POST', body: { mode: 'b', fill, time_limit: t, ...knobs } });
      location.hash = `#/lo/${body.id}/ket-qua/${job.id}`;
    } catch (e) {
      btn.disabled = false;
      $('runerr').textContent = e.message;
    }
    return;
  }
  const containers = [];
  body.containers.forEach((c, i) => {
    if (!app.querySelector(`[data-ct="${i}"]`).checked) return;
    const cost = parseDecimal(app.querySelector(`[data-cost="${i}"]`).value);
    containers.push({ ...c, cost: cost === null ? c.cost : cost });
  });
  if (!containers.length) { $('runerr').textContent = 'Chọn ít nhất một loại container.'; return; }
  const t = runTime();
  const knobs = advValues();
  if (!knobs || t === null) return;
  try {
    btn.disabled = true;
    const job = await api(`/api/lots/${body.id}/runs`, { method: 'POST', body: { mode: 'a', containers, time_limit: t, ...knobs } });
    location.hash = `#/lo/${body.id}/ket-qua/${job.id}`;
  } catch (e) {
    btn.disabled = false;
    $('runerr').textContent = e.message;
  }
}

// ---- 5. result ----------------------------------------------------------------------------------------------
// A run's lot changed since: the plan is of the data it was packed with, not of the lot as it is now.
const changedNote = (cmp, id) => (cmp?.lot_changed ? `<div class="alert caution" role="status">${ic('triangle-alert')}<span>Dữ liệu lô đã đổi sau lần chạy này; xếp lại để có phương án theo dữ liệu mới.</span><span class="spacer"></span><button class="sm" data-go="#/lo/${id}/chay">${ic('play')}Xếp lại</button></div>` : '');
async function runView(job) {
  if (S.runs[job]) return S.runs[job];
  let view;
  try { view = await api(`/api/jobs/${job}/result`); } catch (e) { if (e.status !== 404) throw e; view = await api(`/api/runs/${job}`); }
  S.runs[job] = view;
  return view;
}

async function jobState(job) {
  try { return await api(`/api/jobs/${job}`); } catch (e) { if (e.status === 404) return { id: job, status: 'done', saved: true }; throw e; }
}

// The solving screen, a card: a big clock, a container filling (decoration, not progress),
// the bar and Dừng. Drawn once; each second only the clock, the bar and the note change, so the picture keeps playing.
function solvingCard(job) {
  return `<div class="solve"><section class="box solvecard" data-job="${esc(job)}"><div class="solvehead">
      <div><div class="solvelabel">Thời gian chạy</div><div id="clock"></div></div>
      <div id="solveart">${fillArtSvg()}</div>
      <button class="danger-line" data-act="stop-run" data-job="${esc(job)}">${ic('square')}Dừng</button></div>
    <div class="bar" id="bar" role="progressbar" aria-label="Thời gian đã chạy" aria-valuemin="0" aria-valuemax="100"><div></div></div>
    <div class="promise">${ic('clock')}<span id="solvenote"></span></div>
    <p class="muted keep">Có thể rời màn này: lần chạy vẫn tiếp tục, xong thì có ở "Các lần xếp" của lô.</p></section></div>`;
}
function tickSolving(m) {
  app.querySelector('.wstool h1').textContent = m.label;
  $('clock').innerHTML = `${esc(m.clock)}${m.small ? ` <small>${esc(m.small)}</small>` : ''}`;
  $('bar').dataset.kind = m.kind;
  $('bar').firstElementChild.style.width = `${m.pct}%`;
  $('bar').setAttribute('aria-valuenow', String(Math.round(m.pct)));
  $('solvenote').textContent = m.note;
}

// The toolbar of a result: the run (a picker of the runs packed the same way when there are more), "So sánh" with
// another of them, and "Xuất".
function resultTool(body, job, title) {
  const nums = runNumbers(body.runs);
  const peers = comparable(body.runs, job);
  const run = body.runs.find((r) => r.job_id === job);
  const which = peers.length > 1
    ? `<select class="runsel" data-act="pick-run" aria-label="Lần chạy">${peers.map((r) => `<option value="${esc(r.job_id)}" ${r.job_id === job ? 'selected' : ''}>Lần ${nums[r.job_id]} · ${when(r.created_at)} · ${esc(runOutcome(r, false))}</option>`).join('')}</select>`
    : run ? `<span class="src">Lần ${nums[job]} · ${when(run.created_at)}</span>` : '';
  const other = peers.find((r) => r.job_id !== job);
  return toolbar(lotCrumbs(body), title, `${which}<span class="spacer"></span>
    ${other ? `<button data-go="#/lo/${body.id}/so-sanh/${esc(other.job_id)}/${esc(job)}">${ic('git-compare')}So sánh</button>` : ''}
    <div class="popwrap"><button class="primary" id="exportbtn" data-act="export-menu" aria-haspopup="true" aria-expanded="false" aria-controls="exportmenu">${ic('download')}Xuất${ic('chevron-down')}</button>
      <div class="menu" id="exportmenu" hidden><button data-act="dl-plan" data-job="${esc(job)}">${ic('download')}Kế hoạch xếp (CSV)</button>
      <button data-act="dl-json" data-job="${esc(job)}">${ic('download')}Phương án (JSON)</button></div></div>`);
}
// ⓘ beside a label: its text on hover or focus (`.tipwrap` around the label places it).
const infoTip = (text) => `<span class="info" tabindex="0" role="note" aria-label="${text}" data-tip="${text}">${ic('info')}</span>`;
// The simple packing a result is set against: what it is, in the ⓘ of the tile; the tile keeps the numbers.
const SIMPLE_A = 'Cách xếp đơn giản: lấp đầy lần lượt từng container cùng một loại, chọn loại cho tổng cước rẻ nhất. Mức thấp nhất có thể: không phương án nào rẻ hơn, tính theo thể tích và khối lượng của lô.';
const SIMPLE_B = 'Cách xếp đơn giản: đưa từng kiện vào theo thứ tự ưu tiên, đầy container này mới sang container sau.';
const simpleLab = (tipText) => `<div class="lab"><span class="tipwrap">So với cách xếp đơn giản${infoTip(tipText)}</span></div>`;
const checkKpi = (view) => `<section class="box kpi"><div class="lab">Kiểm tra ràng buộc</div><div class="val ${view.check.ok ? 'ok' : ''}">${ic(view.check.ok ? 'circle-check' : 'circle-alert')}${view.check.ok ? 'Đạt' : 'Không đạt'}</div><div class="sub">Bộ kiểm tra độc lập, ${view.check.n_violations} vi phạm</div></section>`;
// A difference against the simple packing: `better` says which sign is good; zero is neither.
const deltaSpan = (d, better, text) => `<span class="delta ${d === 0 ? '' : (d < 0) === (better < 0) ? 'good' : 'bad'}">${d < 0 ? '−' : d > 0 ? '+' : ''}${text}</span>`;

let clockTimer = null;
async function screenResult(id, job) {
  clearTimeout(clockTimer);
  const state = await jobState(job);
  if (state.status === 'queued' || state.status === 'running') {
    const m = solveClock(state);
    if (!app.querySelector(`.solvecard[data-job="${CSS.escape(job)}"]`)) {
      const body = await loadLot(id);
      paint(workspace(toolbar(lotCrumbs(body), m.label, ''), solvingCard(job)));
    }
    tickSolving(m);   // the clock only: the chat keeps what is being typed
    clockTimer = setTimeout(() => { if (location.hash.endsWith(`/ket-qua/${job}`)) screenResult(id, job); }, 1000);
    return;
  }
  const body = await loadLot(id);
  if (state.status !== 'done' || (!state.saved && !state.has_result)) {
    const why = { stopped: 'Lần chạy đã dừng.', failed: `Lần chạy lỗi: ${state.error || state.code}.` }[state.status] || 'Không có lời giải.';
    paint(workspace(toolbar(lotCrumbs(body), 'Không có lời giải', ''), `<div class="alert bad" role="alert">${esc(why)} <a href="#/lo/${id}/chay">Sửa thiết lập rồi chạy lại</a></div>`));
    return;
  }
  const view = await runView(job);
  if (view.fill) { await resultB(body, view, job); return; }
  let cmp = null;
  try { cmp = await api(`/api/runs/${job}/compare`, { method: 'POST', body: {} }); } catch { cmp = null; }
  const pieces = view.placements.length;
  const total = view.lines.reduce((a, l) => a + l.qty, 0);
  const mix = fleetText(view.containers.map((c) => c.type));
  const base = cmp?.cheapest_single;
  const delta = base ? view.check.cost - base.cost : null;
  const tool = resultTool(body, job, 'Kết quả · chọn container rẻ nhất');
  const kpis = `<div class="kpis four">
      <section class="box kpi hero"><div class="lab">Tổng cước</div><div class="val">${usd(view.check.cost)}</div><div class="sub">${view.containers.length} container · ${fmt(pieces, 0)} / ${fmt(total, 0)} kiện</div></section>
      <section class="box kpi"><div class="lab">Container</div><div class="val">${view.containers.length}</div><div class="sub">${esc(mix)}</div></section>
      <section class="box kpi">${simpleLab(SIMPLE_A)}<div class="val">${delta === null ? '—' : deltaSpan(delta, -1, usd(Math.abs(delta)))}</div>
        <div class="sub">${base ? `${base.containers} × ${esc(base.type)} = ${usd(base.cost)}` : 'Chưa tính được'}${cmp ? `<br>Thấp nhất có thể: ${usd(cmp.bound.cost)}` : ''}</div></section>
      ${checkKpi(view)}</div>`;
  const lines = body.lot.lines;
  const sku = (lid) => lines.find((l) => l.id === lid) || { sku: lid, description: '' };
  const head = view.containers.map((c, i) => `<th class="num">#${i + 1} ${esc(c.type)}</th>`).join('');
  const rows = view.lines.map((l) => {
    const s = sku(l.id);
    const per = view.containers.map((c) => `<td class="num">${c.lines.find((x) => x.id === l.id)?.qty || '—'}</td>`).join('');
    const rule = [s.posture ? valueText('posture', s.posture.value) : '', s.stacking ? valueText('stacking', s.stacking.value) : '', s.fragile?.value ? 'Dễ vỡ' : ''].filter(Boolean).join(' · ');
    return `<tr><td style="border-left:4px solid ${lineCss(s.sku)}"><b>${esc(s.sku)}</b> <span class="muted">${esc(s.description)}</span></td><td class="num">${l.qty}</td>${per}<td>${esc(rule)}</td></tr>`;
  }).join('');
  const table = `<section class="box flush"><div class="boxhd"><h2>Theo mã hàng</h2></div><table class="cmp"><thead><tr><th>Mã hàng</th><th class="num">Số kiện</th>${head}<th>Ràng buộc</th></tr></thead><tbody>${rows}</tbody></table></section>`;
  const viewer = `<section class="box"><div class="boxhd"><h2>Container</h2><span class="muted">bấm một thẻ để xem 3D và tua từng kiện</span></div>
    <div class="cgrid">${containerCards(view, job, lines)}</div></section>`;
  paint(workspace(tool, `${changedNote(cmp, id)}${kpis}${viewer}${table}`));
  drawThumbs(view, job);
}

// Mode B's result (docs/product/ux.md §4): pieces placed of the lot against the priority-order baseline, and per line
// by priority what went in and what is left.
async function resultB(body, view, job) {
  const id = body.id;
  const f = view.fill;
  let base = null;
  try {
    base = await api(`/api/runs/${job}/compare`, { method: 'POST', body: {} });
  } catch { base = null; }
  const mix = fleetText(view.containers.map((c) => c.type));
  const have = Object.entries(f.fleet).filter(([, n]) => n).map(([t, n]) => `${n} × ${t}`).join(', ');
  const delta = base?.ok ? f.placed - base.placed : null;
  const left = f.total - f.placed;
  const tool = resultTool(body, job, 'Kết quả · xếp vào container có sẵn');
  const kpis = `<div class="kpis four">
      <section class="box kpi hero"><div class="lab">Hàng đã xếp</div><div class="val">${fmt(f.placed, 0)} / ${fmt(f.total, 0)} kiện</div><div class="sub">${left ? `còn lại ${fmt(left, 0)} kiện` : 'xếp hết'}</div></section>
      <section class="box kpi"><div class="lab">Container</div><div class="val">${view.containers.length}</div><div class="sub">dùng ${esc(mix || '—')} · có sẵn ${esc(have)}</div></section>
      <section class="box kpi">${simpleLab(SIMPLE_B)}<div class="val">${delta === null ? '—' : deltaSpan(delta, 1, `${fmt(Math.abs(delta), 0)} kiện`)}</div>
        <div class="sub">${base?.ok ? `${fmt(base.placed, 0)} kiện theo thứ tự ưu tiên` : 'Chưa tính được'}</div></section>
      ${checkKpi(view)}</div>`;
  const lines = body.lot.lines;
  const sku = (lid) => lines.find((l) => l.id === lid) || { sku: lid, description: '' };
  const rows = f.lines.map((l, i) => {
    const s = sku(l.id);
    const rest = l.qty - l.placed;
    const why = !rest ? '' : !f.partial && !l.placed ? 'Không vừa cả dòng (không cho xếp một phần)' : 'Hết chỗ trong container có sẵn';
    return `<tr${rest ? ' style="background:var(--warn-soft)"' : ''}><td class="num">${i + 1}</td><td style="border-left:4px solid ${lineCss(s.sku)}"><b>${esc(s.sku)}</b> <span class="muted">${esc(s.description)}</span></td>
      <td class="num">${fmt(l.placed, 0)} / ${fmt(l.qty, 0)}</td><td class="num">${rest ? fmt(rest, 0) : '—'}</td><td>${esc(why)}</td></tr>`;
  }).join('');
  const table = `<section class="box flush"><div class="boxhd"><h2>Theo thứ tự ưu tiên</h2>${left ? `<span class="muted">Còn lại ${fmt(left, 0)} kiện</span>` : ''}</div>
    <table class="cmp"><thead><tr><th class="num">Ưu tiên</th><th>Mã hàng</th><th class="num">Đã xếp / tổng</th><th class="num">Còn lại</th><th>Lý do</th></tr></thead><tbody>${rows}</tbody></table></section>`;
  const viewer = `<section class="box"><div class="boxhd"><h2>Container</h2><span class="muted">bấm một thẻ để xem 3D và tua từng kiện</span></div>
    <div class="cgrid">${containerCards(view, job, lines)}</div></section>`;
  paint(workspace(tool, `${changedNote(base, id)}${kpis}${viewer}${table}`));
  drawThumbs(view, job);
}

// One card per container: type, cost, pieces, volume and mass used, the codes it carries; it opens the container
// screen (3D) on that container.
function containerCards(view, job, lines) {
  const sku = (id) => lines.find((l) => l.id === id)?.sku || id;
  return view.containers.map((c, i) => {
    const pieces = c.lines.reduce((a, x) => a + x.qty, 0);
    const chips = c.lines.map((x) => `<span class="chip"><span class="sw" style="background:${lineCss(sku(x.id))}"></span>${esc(sku(x.id))} × ${x.qty}</span>`).join('');
    const meter = (label, r) => `<div class="meter"><span>${label}</span><div class="bar"><div style="width:${Math.min(100, (r || 0) * 100)}%"></div></div><span class="num">${fmt((r || 0) * 100, 1)}%</span></div>`;
    return `<a class="ccard" style="text-decoration:none;color:inherit" href="#/lo/${S.lot.id}/ket-qua/${encodeURIComponent(job)}/c/${i + 1}" aria-label="Mở 3D container #${i + 1}">
      <div class="stage"><canvas data-thumb="${esc(job)}" data-i="${i}" width="${THUMB_PX[0]}" height="${THUMB_PX[1]}" aria-hidden="true"></canvas></div><div class="cb">
      <div class="ch"><b>#${i + 1}</b><span class="cp-type">${esc(c.type)}</span><span class="spacer"></span><span class="cellcost">${view.fill ? 'có sẵn' : usd(c.cost)}</span></div>
      <div>${pieces} kiện · ${fmt(c.mass, 0)} kg</div>${meter('Thể tích', c.volume_ratio)}${meter('Khối lượng', c.mass_ratio)}
      <div class="chips">${chips}</div></div></a>`;
  }).join('');
}

async function exportRun(job, kind) {
  const view = await runView(job);
  const name = (S.lot?.name || 'lo').replace(/[^\p{L}\p{N}_-]+/gu, '-');
  if (kind === 'json') {
    const solution = await api(`/api/runs/${job}/solution.json`).catch(() => api(`/api/jobs/${job}/solution.json`));
    download(`${name}-${job}.json`, JSON.stringify(solution, null, 2));
  } else {
    const skus = Object.fromEntries((S.lot?.lot.lines || []).map((l) => [l.id, l.sku]));
    download(`${name}-${job}.csv`, csvPlan(view, skus), 'text/csv');
  }
}

// ---- 6. compare ---------------------------------------------------------------------------------------------
// Two runs packed the same way: a picker for each side lists the lot's other runs of that way; two runs packed
// differently are not compared (mode A weighs freight, mode B pieces placed).
async function screenCompare(id, a, b) {
  const body = await loadLot(id);
  const nums = runNumbers(body.runs);
  const name = (job) => `Lần ${nums[job] ?? '—'}`;
  const peers = comparable(body.runs, a);
  const picker = (side, job, other) => {
    const list = peers.filter((r) => r.job_id !== other);
    const none = list.some((r) => r.job_id === job) ? '' : '<option value="" selected disabled>Chọn lần chạy</option>';  // `job` packed the other way
    return `<select class="runsel" data-act="cmp-run" data-side="${side}" aria-label="${side === 'a' ? 'Lần thứ nhất' : 'Lần thứ hai'}">${none}${list
      .map((r) => `<option value="${esc(r.job_id)}" ${r.job_id === job ? 'selected' : ''}>${name(r.job_id)} · ${when(r.created_at)} · ${esc(runOutcome(r, false))}</option>`).join('')}</select>`;
  };
  const tool = toolbar(lotCrumbs(body), 'So sánh lần chạy', `<span class="spacer"></span>${picker('a', a, b)}<span class="muted">với</span>${picker('b', b, a)}`);
  const mode = (job) => body.runs.find((r) => r.job_id === job)?.mode || 'a';
  if (mode(a) !== mode(b)) {
    paint(workspace(tool, `<div class="alert note" role="alert">${ic('info')}<div>${name(a)} và ${name(b).toLowerCase()} xếp theo hai cách khác nhau (chọn container rẻ nhất, xếp vào container có sẵn), nên không so được. Chọn hai lần cùng cách xếp ở trên.</div></div>`));
    return;
  }
  const [va, vb] = await Promise.all([runView(a), runView(b)]);
  const [la, lb] = await Promise.all([api(`/api/runs/${a}/lot.json`).catch(() => api(`/api/jobs/${a}/lot.json`)),
    api(`/api/runs/${b}/lot.json`).catch(() => api(`/api/jobs/${b}/lot.json`))]);
  const note = (job) => body.family.find((f) => f.id === body.runs.find((r) => r.job_id === job)?.lot_id)?.note;
  const c = runCompare(va, vb, la, lb, [nums[a] ?? '—', nums[b] ?? '—']);
  const rows = c.rows.map((r) => `<tr class="${r.key ? 'key' : ''}"><th scope="row">${r.label}</th><td class="num">${r.a}</td><td class="num">${r.b}</td><td class="num">${r.delta}</td></tr>`).join('');
  const changes = c.changes.length ? c.changes.map((x) => `<li>${esc(x)}</li>`).join('') : '<li>Không khác</li>';
  const outcome = (v) => (v.fill ? `${fmt(v.fill.placed, 0)} / ${fmt(v.fill.total, 0)} kiện` : usd(v.check.cost));
  const col = (v, job) => `<section class="box runcol"><div class="boxhd"><h2>${name(job)}</h2><span class="muted">${outcome(v)} · ${v.containers.length} container</span></div>
    <div class="cgrid one">${containerCards(v, job, body.lot.lines)}</div></section>`;
  const runsNote = [a, b].map((job) => (note(job) ? `<li>${name(job)} chạy trên bản thử: ${esc(note(job))}</li>` : '')).join('');
  paint(workspace(tool, `<section class="box"><h2>Đầu vào khác nhau</h2><ul class="chg">${changes}${runsNote}</ul></section>
    <section class="box flush"><table class="cmp"><thead><tr><th></th><th class="num">${name(a)}</th><th class="num">${name(b)}</th><th class="num">Chênh lệch (${name(b).toLowerCase()} − ${name(a).toLowerCase()})</th></tr></thead><tbody>${rows}</tbody></table></section>
    <div class="runcols">${col(va, a)}${col(vb, b)}</div>`));
  drawThumbs(va, a);
  drawThumbs(vb, b);
}

// ---- 7. one container in 3D ------------------------------------------------------------------------------------
// The container screen (scene, replay bar, container panel, list of pieces), built once in #scr-view: its modules
// look up their elements when they load, so they are imported after mountViewer. The result screens draw their own
// cards and take only the thumbnails from it (grid.js `drawThumbInto`).
const THUMB_PX = [520 * (window.devicePixelRatio || 1), 200 * (window.devicePixelRatio || 1)].map(Math.round);
let viewerReady = null;
let shown = null;  // {id, job} while the container screen is on

function viewer() {
  viewerReady ??= (async () => {
    mountViewer({ actions: [] });
    $('vback').classList.add('backbtn');
    const { S: VS } = await import('./state.js');
    await import('./layout.js');
    const player = await import('./player.js');
    const { drawThumbInto } = await import('./grid.js');
    document.addEventListener('viewer:select', () => {
      if (!shown) return;
      if (VS.selected === null) { location.hash = `#/lo/${shown.id}/ket-qua/${shown.job}`; return; }  // Esc
      history.replaceState(null, '', `#/lo/${shown.id}/ket-qua/${shown.job}/c/${VS.selected + 1}`);  // ←/→, Trước/Sau
      containerChrome();
    });
    return { VS, ...player, drawThumbInto };
  })();
  return viewerReady;
}

// The cards' thumbnails, one per animation frame (a big fleet does not stall the page).
async function drawThumbs(view, job) {
  let v;
  try { v = await viewer(); } catch { return; }  // no WebGL or three.js: the cards keep their numbers
  const canvases = [...app.querySelectorAll(`canvas[data-thumb="${CSS.escape(job)}"]`)];
  const next = () => {
    const cv = canvases.shift();
    if (!cv) return;
    if (cv.isConnected) v.drawThumbInto(cv, view, Number(cv.dataset.i));
    requestAnimationFrame(next);
  };
  requestAnimationFrame(next);
}

function containerChrome() {
  viewerReady.then(({ VS }) => setChrome({
    title: containerTitle(VS.cur), source: S.lot ? `${S.lot.name}` : '',
    back: { label: 'Quay lại', onclick: () => { location.hash = `#/lo/${shown.id}/ket-qua/${shown.job}`; } },
  }));
}

function showContainerScreen(on) {
  $('scr-view').hidden = !on;
  app.hidden = on;
  document.body.dataset.screen = on ? 'container' : '';
}

async function screenContainer(id, job, n) {
  await loadLot(id);
  const view = await runView(job);
  const v = await viewer();
  if (v.VS.view !== view) v.buildScene(view);
  shown = { id, job };
  showContainerScreen(true);
  v.select(Math.min(Math.max(n, 1), view.containers.length) - 1);
  containerChrome();
}

async function leaveContainerScreen() {
  if (!shown) return;
  shown = null;
  showContainerScreen(false);
  (await viewerReady).showGrid();  // drops the 3D container; the render loop idles on the grid
}

// ---- router -------------------------------------------------------------------------------------------------------
function routeOf() {
  const h = location.hash || '#/lo-hang';
  let m;
  if (h === '#/lo/moi') return { name: 'new' };
  if ((m = h.match(/^#\/lo\/(\d+)$/))) return { name: 'lot', id: Number(m[1]) };
  if ((m = h.match(/^#\/lo\/(\d+)\/chay$/))) return { name: 'run', id: Number(m[1]) };
  if ((m = h.match(/^#\/lo\/(\d+)\/ket-qua\/([\w-]+)$/))) return { name: 'result', id: Number(m[1]), job: m[2] };
  if ((m = h.match(/^#\/lo\/(\d+)\/ket-qua\/([\w-]+)\/c\/(\d+)$/))) return { name: 'container', id: Number(m[1]), job: m[2], n: Number(m[3]) };
  if ((m = h.match(/^#\/lo\/(\d+)\/so-sanh\/([\w-]+)\/([\w-]+)$/))) return { name: 'compare', id: Number(m[1]), a: m[2], b: m[3] };
  return { name: 'lots' };
}

const TITLES = { lots: 'Lô hàng', new: 'Lô mới', lot: '', run: 'Xếp lô hàng', result: 'Kết quả', container: 'Container', compare: 'So sánh' };
async function route() {
  clearTimeout(S.pollTimer);
  const r = routeOf();
  newScreen = true;  // the next paint puts focus on the screen's title
  try {
    if (r.name !== 'container') await leaveContainerScreen();
    if (r.name === 'container') await screenContainer(r.id, r.job, r.n);
    else if (r.name === 'lots') await screenLots();
    else if (r.name === 'new') screenNew();
    else if (r.name === 'lot') await screenLot(r.id);
    else if (r.name === 'run') await screenRun(r.id);
    else if (r.name === 'result') await screenResult(r.id, r.job);
    else if (r.name === 'compare') await screenCompare(r.id, r.a, r.b);
  } catch (e) {
    if (r.name === 'container') { shown = null; showContainerScreen(false); }
    paint(`<div class="page"><div class="alert bad" role="alert">${esc(e.message)} <a href="#/lo-hang">Về danh sách lô</a></div></div>`);
  }
  newScreen = false;
  document.title = `${[TITLES[r.name], S.lot && r.name !== 'lots' && r.name !== 'new' ? S.lot.name : ''].filter(Boolean).join(' · ') || 'Lô hàng'} — Loading AI Planner`;
  $('nav-lots')?.setAttribute('aria-current', 'page');
}

// ---- events -------------------------------------------------------------------------------------------------------
const picker = el('input', { type: 'file', multiple: true, hidden: true, accept: '.xlsx,.csv,.pdf,.png,.jpg,.jpeg,.webp' });
document.body.append(picker);
picker.addEventListener('change', async () => {
  const files = [...picker.files];
  picker.value = '';
  await addFiles(files);
});

async function addFiles(files) {
  const r = routeOf();
  if (!files.length || uploading || !['new', 'lot'].includes(r.name)) return;
  uploadBusy(true, files.length);
  try {
    if (r.name === 'new') { await createWithFiles(files); return; }
    const body = await upload(r.id, files);
    uploading = false;
    if (location.hash === `#/lo/${r.id}`) { S.lot = body; drawLot(); }
  } catch (e) {
    uploadBusy(false);
    toast(e.message);
  } finally {
    uploading = false;
  }
}

app.addEventListener('click', async (e) => {
  const go = e.target.closest('[data-go]');
  if (go && !go.disabled) { location.hash = go.dataset.go; return; }
  const row = e.target.closest('tr[data-href]');
  if (row && !e.target.closest('a, button, input, select, label, details')) { location.hash = row.dataset.href; return; }
  const ch = e.target.closest('[data-chat]');
  if (ch) { setChatMin(ch.dataset.chat === 'close'); return; }
  const act = e.target.closest('[data-act]');
  if (act) {
    const a = act.dataset.act;
    if (a === 'pick') picker.click();
    else if (a === 'manual-new') await createManual();
    else if (a === 'answer') await answerPoint(act);
    else if (a === 'later' || a === 'goto-point') {
      S.point = Number(act.dataset.id);
      if (S.lot?.lot.points.find((x) => x.id === S.point)?.resolved_at) S.editPoints = true;  // an answered one: open the list
      if (routeOf().name === 'lot') drawLot(); else location.hash = `#/lo/${S.lot.id}`;
    }
    else if (a === 'edit-points') { S.editPoints = !S.editPoints; S.point = null; drawLot(); }
    else if (a === 'prev-point' || a === 'next-point') {
      const open = S.lot.lot.points.filter((x) => !x.resolved_at);
      const i = open.indexOf(currentPoint(S.lot.lot)) + (a === 'next-point' ? 1 : -1);
      if (open[i]) { S.point = open[i].id; drawLot(); }
    } else if (a === 'confirm-lot') await confirmLot();
    else if (a === 'chat-opt') {
      try {
        S.lot = await api(`/api/lots/${S.lot.id}/points/${act.dataset.point}`, { method: 'POST', body: { rev: S.lot.rev, choice: Number(act.dataset.choice) } });
        S.point = null;
        if (routeOf().name === 'lot') drawLot(); else redrawChat();
      } catch (err) { toast(err.message); }
    } else if (a === 'prop-answer') await proposalAnswer(act);
    else if (a === 'prop-line') await proposalLine(act);
    else if (a === 'prop-confirm') { await confirmLot(Number(act.dataset.lot)); act.disabled = true; }
    else if (a === 'del-lot') {
      const ok = await confirmDelete({ title: 'Xóa lô?', message: `Lô "${act.dataset.name}" cùng tài liệu, hội thoại và các bản thử sẽ bị xóa.`, okLabel: 'Xóa lô' });
      if (!ok) return;
      const lotId = act.dataset.id;
      try { await api(`/api/lots/${lotId}`, { method: 'DELETE' }); } catch (err) { toast(err.message); return; }
      if (routeOf().name === 'lots') await screenLots(); else location.hash = '#/lo-hang';
      toast(`Đã xóa lô "${act.dataset.name}"`, { undo: async () => { await api(`/api/lots/${lotId}/restore`, { method: 'POST', body: {} }); if (routeOf().name === 'lots') screenLots(); } });
    } else if (a === 'del-doc') {
      const ok = await confirmDelete({ title: 'Xóa tài liệu?', message: `"${act.dataset.name}" bị xóa hẳn. Dữ liệu lấy từ tài liệu này bị bỏ; câu trả lời nào dựa trên nó sẽ được hỏi lại.`, okLabel: 'Xóa tài liệu' });
      if (!ok) return;
      try {
        S.lot = await api(`/api/lots/${S.lot.id}/documents/${act.dataset.id}`, { method: 'DELETE' });
        S.point = null;
        drawLot();
        toast(`Đã xóa "${act.dataset.name}"`);
      } catch (err) { toast(err.message); }
    } else if (a === 'reread-doc') {
      act.disabled = true;
      try {
        S.lot = await api(`/api/lots/${S.lot.id}/documents/${act.dataset.id}/read`, { method: 'POST', body: {} });
        drawLot();
      } catch (err) { act.disabled = false; toast(err.message); }
    } else if (a === 'edit-line' || a === 'add-line') {
      const line = a === 'edit-line' ? S.lot.lot.lines.find((x) => x.id === act.dataset.id) : null;
      const got = await lineDialog(line, openPointOf(S.lot.lot));
      if (got?.then === 'drop') { app.querySelector(`[data-act="drop-line"][data-id="${CSS.escape(line.id)}"]`)?.click(); return; }
      if (!got || (line && !Object.keys(got.values).length && got.sku === undefined && got.description === undefined)) return;
      const { then, ...body } = got;
      if (await lineChange(line ? `lines/${encodeURIComponent(line.id)}` : 'lines', body)) {
        toast(line ? `Đã lưu dòng ${line.sku}` : `Đã thêm dòng ${got.sku}`);
        if (then === 'again') app.querySelector('[data-act="add-line"]')?.click();
      }
    } else if (a === 'drop-line') {
      const line = S.lot.lot.lines.find((x) => x.id === act.dataset.id);
      const ok = await confirmDelete({ title: 'Bỏ dòng?', okLabel: 'Bỏ dòng',
        message: isManual(line) ? `Dòng ${line.sku} bạn tự thêm sẽ bị xóa hẳn.`
          : `Dòng ${line.sku} chuyển sang "Không đưa vào lô"; đọc lại tài liệu sau này vẫn bỏ. Đưa lại được từ mục đó.` });
      if (ok && await lineChange(`lines/${encodeURIComponent(line.id)}/drop`, {})) toast(`Đã bỏ dòng ${line.sku}`);
    } else if (a === 'restore-line') {
      if (await lineChange(`lines/${encodeURIComponent(act.dataset.id)}/restore`, {})) toast(`Đã đưa dòng ${act.dataset.id} lại vào lô`);
    } else if (a === 'rename-lot') {
      const name = await askText({ title: 'Đổi tên lô', label: 'Tên lô', value: act.dataset.name });
      if (!name || name === act.dataset.name) return;
      try {
        const rev = S.lot?.id === Number(act.dataset.id) ? S.lot.rev : (await api(`/api/lots/${act.dataset.id}`)).rev;
        const body = await api(`/api/lots/${act.dataset.id}`, { method: 'PATCH', body: { rev, name } });
        if (routeOf().name === 'lots') await screenLots(); else { S.lot = body; route(); }
        toast(`Đã đổi tên thành "${name}"`);
      } catch (err) { toast(err.message); }
    } else if (a === 'start-run') await startRun(act);
    else if (a === 'all-runs') { S.allRuns = !S.allRuns; drawLot(); }
    else if (a === 'fleet-inc' || a === 'fleet-dec') {
      const f = fillFor(S.lot);
      f.fleet[act.dataset.t] = Math.max(0, (f.fleet[act.dataset.t] || 0) + (a === 'fleet-inc' ? 1 : -1));
      redrawSetup();
    } else if (a === 'prio-up' || a === 'prio-down') {
      const f = fillFor(S.lot);
      const i = Number(act.dataset.i);
      const j = i + (a === 'prio-up' ? -1 : 1);
      [f.priority[i], f.priority[j]] = [f.priority[j], f.priority[i]];
      redrawSetup();
      app.querySelector(`[data-act="${a}"][data-i="${j}"]`)?.focus();
    }
    else if (a === 'stop-run') { await api(`/api/jobs/${act.dataset.job}/stop`, { method: 'POST', body: {} }); route(); }
    else if (a === 'export-menu') exportMenu($('exportmenu').hidden);
    else if (a === 'dl-plan' || a === 'dl-json') { exportMenu(false); await exportRun(act.dataset.job, a === 'dl-json' ? 'json' : 'csv'); }
    return;
  }
  const tb = e.target.closest('#timeopts button');
  if (tb) {
    for (const b of tb.parentElement.children) { b.setAttribute('aria-pressed', String(b === tb)); b.classList.toggle('on', b === tb); }
    const custom = tb.dataset.t === 'custom';
    $('tlcustom').hidden = !custom;
    $('promisetext').innerHTML = promiseLine(custom ? parseDecimal($('tl').value) : Number(tb.dataset.t));
    if (custom) $('tl').focus();
    return;
  }
  // a field's source opens on click or Enter/Space (a button), closes on Esc or a click elsewhere
  const btn = e.target.closest('button.cv');
  if (e.target.closest('.srcpop')) return;
  const was = btn?.getAttribute('aria-expanded') === 'true';
  closeSources();
  if (btn && !was) { btn.setAttribute('aria-expanded', 'true'); $(btn.getAttribute('aria-controls')).hidden = false; }
});

// The sources of a field (`cell`): every open box closed; the button that had one open, or null.
function closeSources() {
  const open = app.querySelector('button.cv[aria-expanded="true"]');
  for (const b of app.querySelectorAll('button.cv[aria-expanded="true"]')) b.setAttribute('aria-expanded', 'false');
  for (const p of app.querySelectorAll('.srcpop')) p.hidden = true;
  return open;
}

// The "Xuất" menu of a result: opens and closes with its button; a click elsewhere or Esc closes it.
function exportMenu(open) {
  const menu = $('exportmenu');
  if (!menu) return;
  menu.hidden = !open;
  $('exportbtn')?.setAttribute('aria-expanded', String(open));
}
document.addEventListener('click', (e) => { if ($('exportmenu') && !$('exportmenu').hidden && !e.target.closest('.popwrap')) exportMenu(false); });

app.addEventListener('input', (e) => {
  if (e.target.id === 'chattext' && S.lot) { S.draft[S.lot.id] = e.target.value; return; }
  if (e.target.id === 'tl') { e.target.classList.remove('lferr'); $('promisetext').innerHTML = promiseLine(parseDecimal(e.target.value)); return; }
  if (!['delta', 'alpha'].includes(e.target.id) || !S.adv) return;
  e.target.classList.remove('lferr');
  S.adv[e.target.id] = e.target.value;
  advSummary();
});
app.addEventListener('toggle', (e) => { if (e.target.id === 'adv' && S.adv) S.adv.open = e.target.open; }, true);

app.addEventListener('change', (e) => {
  if (e.target.id === 'orient' && S.adv) { S.adv.orient = e.target.checked; advSummary(); }
  if (e.target.name === 'mode') { S.mode = e.target.value; redrawSetup(); }
  if (e.target.matches('[data-act="pick-run"]')) location.hash = `#/lo/${S.lot.id}/ket-qua/${e.target.value}`;
  if (e.target.matches('[data-act="cmp-run"]')) {
    const [a, b] = ['a', 'b'].map((side) => app.querySelector(`[data-act="cmp-run"][data-side="${side}"]`).value);
    if (a && b) location.hash = `#/lo/${S.lot.id}/so-sanh/${a}/${b}`;
  }
  if (e.target.matches('[data-act="partial"]')) fillFor(S.lot).partial = e.target.checked;
  if (e.target.closest('.custom')) { const radio = e.target.closest('.opt')?.querySelector('input[type=radio]'); if (radio) radio.checked = true; }
  if (e.target.matches('[data-act="cv-stack"]')) e.target.parentElement.querySelector('.cvtiers').hidden = e.target.value !== 'limited';
});
app.addEventListener('focusin', (e) => {
  if (e.target.closest('.custom')) { const radio = e.target.closest('.opt')?.querySelector('input[type=radio]'); if (radio) radio.checked = true; }
});

app.addEventListener('submit', (e) => {
  if (e.target.id !== 'chatin') return;
  e.preventDefault();
  const text = $('chattext').value.trim();
  if (!text || S.sending || !S.lot) return;
  $('chattext').value = '';
  delete S.draft[S.lot.id];
  sendChat(text);
});
app.addEventListener('keydown', (e) => {
  if (e.target.id === 'chattext' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('chatin').requestSubmit(); }
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || document.querySelector('dialog[open]')) return;
  if ($('exportmenu') && !$('exportmenu').hidden) { exportMenu(false); $('exportbtn')?.focus(); return; }
  closeSources()?.focus();
});

// files dropped anywhere on a lot screen or the new-lot screen are added to the lot
window.addEventListener('dragover', (e) => { if (['lot', 'new'].includes(routeOf().name)) { e.preventDefault(); document.body.classList.add('dragging'); } });
window.addEventListener('dragleave', (e) => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
window.addEventListener('drop', async (e) => {
  document.body.classList.remove('dragging');
  if (!['lot', 'new'].includes(routeOf().name)) return;
  e.preventDefault();
  await addFiles([...e.dataTransfer.files]);
});

// ---- account ------------------------------------------------------------------------------------------------------
async function account() {
  try { me = (await api('/api/me')).name; } catch { return; }
  const btn = $('acctbtn');
  btn.innerHTML = `<span class="avatar">${esc(me.slice(0, 1).toUpperCase())}</span><span>${esc(me)}</span>`;
  btn.setAttribute('aria-label', `Tài khoản ${me}`);
  $('acctname').textContent = me;
  popover(btn, $('acctmenu'));  // closes on a click elsewhere or Esc
  $('logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST', body: {} }); location.assign('/login'); });
}

window.addEventListener('hashchange', route);
account();
route();
