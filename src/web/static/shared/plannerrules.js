// Pure helpers of the app's screens (planner.js), kept apart so node can test them: values as the screens write them
// (docs/product/ux.md §2), lot totals, the CSV packing plan of a run, how the lists name a run, the solving clock and
// the comparison of two runs.
import { fmt, fmtDim, fmtKg } from './util.js';

const UNIT = { carton: 'thùng', pallet: 'pallet', piece: 'kiện' };

// A field's value on screen; null is "Chưa có" (no document gives it).
export function valueText(name, v, unit = 'carton') {
  if (v === null || v === undefined) return 'Chưa có';
  switch (name) {
    case 'qty': return `${fmt(v, 0)} ${UNIT[unit] || 'kiện'}`;
    case 'dims': return `${fmtDim(v.L)} × ${fmtDim(v.W)} × ${fmtDim(v.H)}`;
    case 'mass': return fmtKg(v);
    case 'posture': return v === 'upright' ? 'Chỉ đứng' : 'Được lật';
    case 'stacking': return v.kind === 'free' ? 'Chồng tự do' : v.kind === 'none' ? 'Không chồng' : `Tối đa ${v.tiers} tầng`;
    case 'fragile': return v ? 'Dễ vỡ' : 'Không';
    default: return String(v);
  }
}

// "12,5" and "12.5" are 12.5; spaces between thousands are dropped; empty or not a number is null.
export function parseDecimal(text) {
  const t = String(text ?? '').replace(/[\s  ]/g, '');
  if (!t) return null;
  const n = Number(t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t);
  return Number.isFinite(n) ? n : null;
}

// Lines, pieces, kg and m³ of a lot, counting only the fields that have a value.
export function totals(lot) {
  let pieces = 0, kg = 0, m3 = 0;
  for (const l of lot.lines) {
    const q = l.qty.value || 0;
    pieces += q;
    if (l.mass.value) kg += q * l.mass.value;
    if (l.dims.value) m3 += q * l.dims.value.L * l.dims.value.W * l.dims.value.H;
  }
  return { lines: lot.lines.length, pieces, kg, m3 };
}

// [icon, kind] of an uploaded file by its extension.
export function fileKind(name) {
  const ext = String(name).split('.').pop().toLowerCase();
  if (ext === 'xlsx' || ext === 'csv') return ['file-spreadsheet', ext === 'csv' ? 'CSV' : 'Excel'];
  if (ext === 'pdf') return ['file-text', 'PDF'];
  return ['image', 'Ảnh'];
}

const csvCell = (v) => (/[",\n;]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

// The packing plan of a run as CSV, one row per piece: container (its number in the run, from 1), its type, the loading order within the
// container (the viewer's replay order when the run has one), the piece, its code, position and size in m.
export function csvPlan(view, skus = {}) {
  const head = ['container', 'loai', 'thu_tu_xep', 'kien', 'ma_hang', 'x', 'y', 'z', 'dai', 'rong', 'cao'];
  const rows = [];
  view.containers.forEach((c, n0) => {
    const own = view.placements.map((p, i) => [p, i]).filter(([p]) => p.k === c.k);
    const order = c.replay && c.replay.length ? c.replay : own.map(([, i]) => i);
    const rank = new Map(order.map((i, n) => [i, n + 1]));
    own.sort((a, b) => (rank.get(a[1]) ?? 1e9) - (rank.get(b[1]) ?? 1e9));
    own.forEach(([p, i], n) => {
      rows.push([n0 + 1, c.type, rank.get(i) ?? n + 1, p.item, skus[p.line] || p.line,
        p.x.toFixed(3), p.y.toFixed(3), p.z.toFixed(3), p.l.toFixed(3), p.w.toFixed(3), p.h.toFixed(3)]);
    });
  });
  return [head, ...rows].map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
}

const usd = (x) => (x === null || x === undefined ? '—' : `${fmt(x, 2)} USD`);
const signed = (x, f) => (x === 0 ? '0' : `${x > 0 ? '+' : '−'}${f(Math.abs(x))}`);

function count(types) {
  const n = {};
  for (const t of types) n[t] = (n[t] || 0) + 1;
  return n;
}
const mixText = (m) => Object.entries(m).filter(([, k]) => k).map(([t, k]) => `${k} × ${t}`).join(', ');

// "2 × 40GP, 1 × 20GP" of the container types of a plan, one entry per container.
export const fleetText = (types) => mixText(count(types));

// ---- runs ---------------------------------------------------------------------------------------------------------

const RUN_STATUS = { stopped: 'Đã dừng', failed: 'Lỗi' };

// What a run came to, as the lists write it: the cost (mode A), or the pieces placed (mode B pays no freight: its
// containers are at hand), then the containers unless `fleet` is false; or why it has no plan. `r` is a run summary of
// the API.
export function runOutcome(r, fleet = true) {
  if (r.status !== 'done') return RUN_STATUS[r.status] || 'Không có lời giải';
  const head = r.mode === 'b' ? `${fmt(r.placed ?? 0, 0)} / ${fmt(r.total ?? 0, 0)} kiện` : usd(r.cost);
  return [head, fleet ? fleetText(r.containers || []) : ''].filter(Boolean).join(' · ');
}

// Every run of a lot's family by its number, the oldest 1 ("Lần n" on every screen); `runs` newest first, as listed.
export const runNumbers = (runs) => Object.fromEntries(runs.map((r, i) => [r.job_id, runs.length - i]));

// The finished runs that can stand beside `job`: those that packed the same way (mode A weighs freight, mode B pieces).
export function comparable(runs, job) {
  const mode = runs.find((r) => r.job_id === job)?.mode || 'a';
  return runs.filter((r) => r.status === 'done' && (r.mode || 'a') === mode);
}

const pad = (n) => String(n).padStart(2, '0');
// 64.3 -> "1:04".
export function minSec(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

// The solving screen for a job state (`/api/jobs/{id}`): waiting its
// turn, inside the chosen time, or past it, the solver settling its best plan until the hard limit.
export function solveClock({ status, elapsed = 0, time_limit: limit, hard_limit: hard = null, position = null }) {
  if (status === 'queued') {
    return { kind: 'queued', label: 'Đang chờ đến lượt', clock: position ? `Thứ ${position}` : 'Đang chờ', small: position ? 'trong hàng đợi' : '',
      pct: 0, note: 'Bắt đầu khi lần chạy trước xong: các lần chạy được xếp lần lượt.' };
  }
  const clock = minSec(elapsed), small = `/ ${minSec(limit)}`;
  if (elapsed > limit) {
    const left = Math.max(0, (hard ?? limit) - elapsed);
    return { kind: 'over', label: 'Đang xếp lô hàng', clock, small, pct: 100,
      note: left > 0 ? `Hết thời gian đã chọn; bộ giải đang chốt phương án tốt nhất, muộn nhất ${minSec(left)} nữa.` : 'Hết thời gian đã chọn; đang nhận kết quả.' };
  }
  return { kind: 'running', label: 'Đang xếp lô hàng', clock, small, pct: Math.min(100, (100 * elapsed) / limit),
    note: 'Bộ giải dùng gần hết thời gian đã chọn để tìm phương án tốt hơn. Phương án nào cũng qua kiểm tra ràng buộc trước khi hiện.' };
}

// Two runs of the same way of packing side by side (`comparable`): the metric rows (first, second, second − first)
// and what differs in their inputs (engine lot JSON). `names` are the runs' numbers, as the screen calls them.
export function runCompare(va, vb, la, lb, names = ['A', 'B']) {
  const used = (v) => v.containers.reduce((a, c) => a + c.volume, 0);
  const cap = (v) => v.containers.reduce((a, c) => a + c.L * c.W * c.H, 0);
  const mass = (v) => v.containers.reduce((a, c) => a + c.mass, 0);
  const ma = count(va.containers.map((c) => c.type)), mb = count(vb.containers.map((c) => c.type));
  const types = [...new Set([...Object.keys(ma), ...Object.keys(mb)])];
  const mixDelta = types.map((t) => [t, (mb[t] || 0) - (ma[t] || 0)]).filter(([, d]) => d).map(([t, d]) => `${d > 0 ? '+' : '−'}${Math.abs(d)} × ${t}`).join(', ') || '0';
  const fill = (v) => (cap(v) ? used(v) / cap(v) : 0);
  const fa = va.fill, fb = vb.fill;  // mode B: pieces placed of the lot is the measure, freight is not paid
  const head = fa && fb
    ? [{ label: 'Hàng đã xếp', a: `${fmt(fa.placed, 0)} / ${fmt(fa.total, 0)} kiện`, b: `${fmt(fb.placed, 0)} / ${fmt(fb.total, 0)} kiện`, delta: signed(fb.placed - fa.placed, (x) => `${fmt(x, 0)} kiện`), key: true }]
    : [{ label: 'Tổng cước', a: usd(va.check.cost), b: usd(vb.check.cost), delta: signed(vb.check.cost - va.check.cost, usd), key: true }];
  const rows = [...head,
    { label: 'Container', a: mixText(ma), b: mixText(mb), delta: mixDelta },
    ...(fa && fb ? [] : [{ label: 'Số kiện', a: fmt(va.placements.length, 0), b: fmt(vb.placements.length, 0), delta: signed(vb.placements.length - va.placements.length, (x) => fmt(x, 0)) }]),
    { label: 'Thể tích dùng', a: `${fmt(fill(va) * 100, 1)}%`, b: `${fmt(fill(vb) * 100, 1)}%`, delta: `${signed((fill(vb) - fill(va)) * 100, (x) => fmt(x, 1))} điểm` },
    { label: 'Khối lượng', a: `${fmt(mass(va), 0)} kg`, b: `${fmt(mass(vb), 0)} kg`, delta: signed(mass(vb) - mass(va), (x) => `${fmt(x, 0)} kg`) },
    { label: 'Kiểm tra ràng buộc', a: va.check.ok ? 'Đạt' : 'Không đạt', b: vb.check.ok ? 'Đạt' : 'Không đạt', delta: '—' },
  ];
  const changes = [];
  const second = `lần ${names[1]}`;
  const lines = (lot) => Object.fromEntries((lot.items || []).map((l) => [l.id, l]));
  const xa = lines(la), xb = lines(lb);
  for (const id of new Set([...Object.keys(xa), ...Object.keys(xb)])) {
    if (!xb[id]) changes.push(`${id}: ${xa[id].qty} → 0, không có trong ${second}`);
    else if (!xa[id]) changes.push(`${id}: 0 → ${xb[id].qty}, chỉ có trong ${second}`);
    else if (xa[id].qty !== xb[id].qty) changes.push(`${id}: ${xa[id].qty} → ${xb[id].qty} kiện`);
  }
  if (fa && fb) {
    const atHand = (f) => mixText(f.fleet) || '—';
    const yes = (on) => (on ? 'có' : 'không');
    if (atHand(fa) !== atHand(fb)) changes.push(`Container có sẵn: ${atHand(fa)} → ${atHand(fb)}`);
    if (fa.priority.join('\n') !== fb.priority.join('\n')) changes.push(`Thứ tự ưu tiên: ${fa.priority.join(', ')} → ${fb.priority.join(', ')}`);
    if (fa.partial !== fb.partial) changes.push(`Cho xếp một phần mã hàng: ${yes(fa.partial)} → ${yes(fb.partial)}`);
  } else {
    const costs = (lot) => Object.fromEntries((lot.container_types || []).map((t) => [t.id, t.cost]));
    const ca = costs(la), cb = costs(lb);
    for (const t of new Set([...Object.keys(ca), ...Object.keys(cb)])) {
      if (!(t in cb)) changes.push(`${t}: không dùng ở ${second}`);
      else if (!(t in ca)) changes.push(`${t}: chỉ dùng ở ${second}`);
      else if (ca[t] !== cb[t]) changes.push(`Cước ${t}: ${usd(ca[t])} → ${usd(cb[t])}`);
    }
  }
  const pa = va.params || {}, pb = vb.params || {};  // "Thiết lập nâng cao"
  if (pa.delta !== pb.delta) changes.push(`Khe hở δ: ${fmt(pa.delta, 2)} → ${fmt(pb.delta, 2)} m`);
  if (pa.alpha !== pb.alpha) changes.push(`Đỡ α: ${fmt(pa.alpha * 100, 0)}% → ${fmt(pb.alpha * 100, 0)}%`);
  return { rows, changes };
}
