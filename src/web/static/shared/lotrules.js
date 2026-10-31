// Pure rules of the lot editor (lotform.js), apart from it so they run without a DOM (tests/web/test_lotrules.py).
export const NUMBER = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$/;
export const STANDARD_TYPES = [   // the `standard` cost table
  ['20DC', 5.9, 2.35, 2.39, 2.34, 2.28, 28000, 0.6],
  ['40DC', 12.03, 2.35, 2.39, 2.34, 2.28, 26700, 1.0],
  ['40HC', 12.03, 2.35, 2.69, 2.34, 2.58, 26500, 1.05],
  ['45HC', 13.56, 2.35, 2.7, 2.34, 2.58, 27700, 1.2],
];

// The default types whose id is not among `ids` (the texts of the id cells, compared trimmed), in STANDARD_TYPES order.
export function missingStandardTypes(ids) {
  const have = new Set(ids.map((s) => String(s).trim()));
  return STANDARD_TYPES.filter((t) => !have.has(t[0]));
}

// The text a cell shows for a value of the file.
export const cellText = (v) => (v === undefined || v === null ? '' : typeof v === 'string' ? v : typeof v === 'number' ? String(v) : JSON.stringify(v));

// A non-blank cell as JSON: a number when it parses (comma = decimal point), else the raw string (the server reports the wrong type).
export function numberOrRaw(raw) {
  const s = raw.trim();
  if (!NUMBER.test(s)) return raw;
  const n = Number(s.replace(',', '.'));
  return Number.isFinite(n) ? n : raw;
}

// ---- stacking: two ticks, each with an optional number behind it ------------------------------------------

// `load` and `tiers` of a line from its cells. "Không được chồng" is `load` 0, "Chỉ nằm sàn" is `tiers` 1; a blank
// number is `null` = unlimited. The texts behind a ticked box are kept by the form but not sent.
export function stackingFields({ noStack, loadText, floorOnly, tiersText }) {
  const one = (text) => (String(text).trim() === '' ? null : numberOrRaw(String(text)));
  return { load: noStack ? 0 : one(loadText), tiers: floorOnly ? 1 : one(tiersText) };
}

// The ticks and texts a line read from a file shows as: `load` 0 ticks "Không được chồng", `tiers` 1 ticks "Chỉ nằm sàn".
export function stackingFromJson(item) {
  const noStack = item.load === 0, floorOnly = item.tiers === 1;
  return { noStack, loadText: noStack ? '' : cellText(item.load), floorOnly, tiersText: floorOnly ? '' : cellText(item.tiers) };
}

// ---- posture: one tick "Được lật", or the `orientations` a file brought --------------------------------------

// `tippable` / `orientations` of a line. `file` holds what the file said when it had an `orientations` key; it goes
// out as it came (an invalid set too, the server reports it on that row).
export function postureFields({ tippable, file }) {
  return file ? { ...file } : { tippable: Boolean(tippable) };
}

// The posture of a line read from a file: a tick, or `file` when the line carries an `orientations` list.
export function postureFromJson(item) {
  if (item.orientations === undefined || item.orientations === null) return { tippable: Boolean(item.tippable), file: null };
  const file = { orientations: item.orientations };
  if (item.tippable !== undefined) file.tippable = item.tippable;
  return { tippable: false, file };
}

// What "Tùy chỉnh (từ file)" lists in its title.
export const orientationsText = (orientations) => (Array.isArray(orientations) ? orientations.join(', ') : cellText(orientations));

// ---- mass entry (step 4): per item or for the whole type; the file always holds the mass of one item ----------

// A number for an input box: at most 10 significant digits, so 100 / 3 * 3 comes back as 100.
export const formatNumber = (x) => String(Number(Number(x).toPrecision(10)));

// Decimal comma in a number cell for display; text that is not a number is shown as typed.
export const showNumber = (text) => (NUMBER.test(String(text).trim()) ? String(text).trim().replace('.', ',') : String(text));

// The mass of ONE item as the cell holds it, from what the person typed. mode 'piece': the text as it is. mode 'total':
// the mass of the whole type, divided by `qtyText`. Blank stays blank, text that is not a number stays as typed (the server
// reports it). null: a total cannot be turned into a per-item mass because the quantity is not a positive number.
export function massPerItem(text, qtyText, mode) {
  if (mode !== 'total' || String(text).trim() === '') return text;
  const total = numberOrRaw(String(text));
  if (typeof total !== 'number') return text;
  const qty = numberOrRaw(String(qtyText));
  return typeof qty === 'number' && qty > 0 ? formatNumber(total / qty) : null;
}

// What the mass box shows for a cell holding the mass of one item, in the given mode.
export function massShown(perItemText, qtyText, mode) {
  if (mode !== 'total' || String(perItemText).trim() === '') return perItemText;
  const one = numberOrRaw(String(perItemText));
  if (typeof one !== 'number') return perItemText;
  const qty = numberOrRaw(String(qtyText));
  return typeof qty === 'number' && qty > 0 ? formatNumber(one * qty) : '';
}

// ---- problems of a lot ------------------------------------------------------------------------------------------

// An empty lot is not an error: the server's "no items" is left out while the lot has no item type.
export function visibleIssues(details, itemCount) {
  return details.filter((d) => !(d.code === 'items_none' && itemCount === 0));
}

// Text into HTML (ids and messages are the person's words).
export const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// ---- time limit by level (step 4) ----------------------------

// What the person is told to expect (the run overshoots its limit by about 1.2 x): "thường xong trong khoảng …".
export const PROMISE_FACTOR = 1.2;
export const TIME_LEVELS = [
  { seconds: 60, label: '1 phút', hint: 'nhanh' },
  { seconds: 120, label: '2 phút', hint: 'kỹ hơn' },
  { seconds: 300, label: '5 phút', hint: 'lô lớn' },
];
// The small print under a level: "mặc định" on the level the server defaults to.
export const levelHint = (level, defaultSeconds) => (level.seconds === defaultSeconds ? 'mặc định' : level.hint);
// Index of the level with exactly this many seconds, or -1 (the "Khác…" choice).
export const levelIndex = (seconds) => TIME_LEVELS.findIndex((l) => l.seconds === seconds);
// ---- default time limit by lot size: the thresholds come from /api/config (`size_time_limits`) ------

const SIZE_WORDS = { small: 'nhỏ', medium: 'trung bình', large: 'lớn' };
// Containers of the lower-bound fleet (`bound.fleet`: type id -> count).
export const fleetSize = (fleet) => Object.values(fleet || {}).reduce((a, n) => a + n, 0);
// The size class of a fleet: the first of `limits` ([{name, max_containers, seconds}], null max = no end) that holds it.
export function sizeClass(limits, fleet) {
  const n = fleetSize(fleet);
  const hit = (limits || []).find((l) => l.max_containers === null || n <= l.max_containers);
  return hit ? { name: hit.name, word: SIZE_WORDS[hit.name] || hit.name, seconds: hit.seconds, containers: n } : null;
}
// What the service page does with the time box once a lot is valid: `line` is the sentence under the levels (null:
// nothing to say yet), `fill` is the seconds to put in the box, or null when the person already chose by hand.
export function timeDefault({ limits, bound, touched }) {
  const c = bound ? sizeClass(limits, bound.fleet) : null;
  if (!c) return { line: null, seconds: null, fill: null };
  const line = `Lô cỡ ${c.word} (cận dưới ${c.containers} container): mặc định ${inputText(c.seconds)} s`;
  return { line, seconds: c.seconds, fill: touched ? null : c.seconds };
}
// 90 -> "1 phút 30 giây", 180 -> "3 phút", 45 -> "45 giây".
export function durationText(seconds) {
  const s = Math.round(seconds), m = Math.floor(s / 60), r = s % 60;
  return [m ? `${m} phút` : '', r || !m ? `${r} giây` : ''].filter(Boolean).join(' ');
}
// The promise for a limit in seconds, rounded up: 120 -> "2,5 phút", 300 -> "6 phút", 10 -> "12 giây".
export function promiseText(limit) {
  const s = limit * PROMISE_FACTOR;
  if (s < 60) return `${Math.ceil(s)} giây`;
  return `${String(Math.ceil(s / 30) / 2).replace('.', ',')} phút`;
}

// ---- decimal fields of the pages (δ, α, time limit, seed): text inputs that take a decimal comma --------------------

// A number as an input box shows it: 0.05 -> "0,05" (no thousands space, so it parses back).
export const inputText = (x) => String(x).replace('.', ',');
// The value of a text box: `fallback` when blank, the number when it parses (comma or dot), NaN when it is not a number.
export function readDecimal(text, fallback) {
  const s = String(text).trim();
  if (s === '') return fallback;
  const n = numberOrRaw(s);
  return typeof n === 'number' ? n : NaN;
}

// ---- totals of the rows that are in order (the summary card while the lot still has errors) -------------------------

// Mass in kg and volume in m3 of the rows that have a whole positive qty and positive mass and sizes. `rows`: [{qty, L, W, H, mass}]
// as numbers or text; a row that does not qualify is left out, `pieces` counts the pieces of the rows that did.
export function localTotals(rows) {
  let mass = 0, volume = 0, pieces = 0;
  const pos = (v) => (typeof v === 'number' ? v : typeof v === 'string' ? readDecimal(v, NaN) : NaN);
  for (const r of rows) {
    const q = pos(r.qty), L = pos(r.L), W = pos(r.W), H = pos(r.H), m = pos(r.mass);
    if (![q, L, W, H, m].every((x) => Number.isFinite(x) && x > 0) || !Number.isInteger(q)) continue;
    mass += q * m;
    volume += q * L * W * H;
    pieces += q;
  }
  return { mass, volume, pieces };
}
