// Allowed postures of an item line, in words and in codes.
// The one home of the rule that turns what a person picks ("Chỉ đứng", "Được nằm", ...) into `tippable` and
// `orientations`, and back; the viewer's posture words (panels.js) use `kindOf` too. Pure functions, no DOM.
//
// An orientation code names the item dimension along x, y, z; its last letter is the dimension pointing up. The two
// codes with the same up-dimension differ by a 90° turn about the vertical, so a posture is chosen as a *pair*,
// keyed by that dimension: 'H' (upright), 'W', 'L'.
export const PAIRS = { H: ['LWH', 'WLH'], W: ['LHW', 'HLW'], L: ['WHL', 'HWL'] };
export const ALL_CODES = ['LWH', 'WLH', 'LHW', 'HLW', 'WHL', 'HWL'];   // canonical order of the server
export const UPS = ['H', 'W', 'L'];
export const EPS = 1e-9;   // "equal to H" tolerance, same as the viewer

const validDims = (d) => d && ['L', 'W', 'H'].every((k) => typeof d[k] === 'number' && Number.isFinite(d[k]));

// Kind of the pair whose `up` dimension points up: 'đứng' (H), 'nằm' (shorter than H), 'dựng cao' (longer than H),
// 'lật' (equal to H in size: lying and edge-standing look the same). Without usable dims every non-H pair is 'lật'.
export function kindOf(up, dims) {
  if (up === 'H') return 'đứng';
  if (!validDims(dims)) return 'lật';
  const d = dims[up] - dims.H;
  return Math.abs(d) <= EPS ? 'lật' : d < 0 ? 'nằm' : 'dựng cao';
}

// The pair keys a level allows ('custom' takes its own `pairs`), in H, W, L order.
export function pairsFor(level, pairs, dims) {
  let ups;
  if (level === 'upright') ups = ['H'];
  else if (level === 'lying') ups = UPS.filter((u) => u === 'H' || kindOf(u, dims) === 'nằm');
  else if (level === 'all') ups = UPS;
  else ups = UPS.filter((u) => (pairs || []).includes(u));
  return ups;
}

const codesOfPairs = (ups) => ALL_CODES.filter((c) => ups.some((u) => PAIRS[u].includes(c)));
export const codesFor = (level, pairs, dims) => codesOfPairs(pairsFor(level, pairs, dims));

// Fields of the item line in the file: upright is the default (`tippable` false); "all" is the default of `tippable`
// true; anything else is `tippable` true plus the explicit codes, written only when they differ from that default.
export function fileFields(level, pairs, dims) {
  if (level === 'upright') return { tippable: false };
  const codes = codesFor(level, pairs, dims);
  return codes.length === ALL_CODES.length ? { tippable: true } : { tippable: true, orientations: codes };
}

const sameSet = (a, b) => a.length === b.length && a.every((c) => b.includes(c));

// The level and pairs a line read from a file shows as. A set of codes (`orientations`, else all six if `tippable`,
// else the upright two) equal to a level's shows as that level, the smallest first, so a level the form disables for
// these dimensions is not picked; any other set shows as 'custom' with the pairs that are fully there.
// Never throws: bad input (junk, codes outside the pairs, half a pair) falls to 'custom'; the server reports it.
export function levelFromFile(tippable, orientations, dims) {
  const given = orientations === undefined || orientations === null ? (tippable ? ALL_CODES : PAIRS.H) : orientations;
  const codes = Array.isArray(given) ? given.filter((c) => typeof c === 'string') : [];
  if (Array.isArray(given) && codes.length === given.length) {
    for (const level of ['upright', 'lying', 'all']) {
      const ups = pairsFor(level, null, dims);
      if (sameSet(codesOfPairs(ups), codes)) return { level, pairs: ups };
    }
  }
  return { level: 'custom', pairs: UPS.filter((u) => PAIRS[u].every((c) => codes.includes(c))) };
}

// Whether a line's `tippable` / `orientations` as read from a file are a set the server accepts (model.py): no key,
// or a non-empty list of distinct known codes holding both codes of every pair it uses, and only upright codes when
// `tippable` is false. The form never "repairs" an invalid one: it keeps the raw values until the person re-picks.
export function orientationsValid(tippable, orientations) {
  if (orientations === undefined || orientations === null) return true;
  if (!Array.isArray(orientations) || orientations.length === 0) return false;
  if (!orientations.every((c) => ALL_CODES.includes(c)) || new Set(orientations).size !== orientations.length) return false;
  if (!UPS.every((u) => PAIRS[u].every((c) => orientations.includes(c)) || PAIRS[u].every((c) => !orientations.includes(c)))) return false;
  return tippable === true || orientations.every((c) => PAIRS.H.includes(c));
}

// A level whose code set equals the next smaller level's one is disabled ("Được nằm" when no pair is 'nằm').
export function levelEnabled(level, dims) {
  if (level === 'lying') return !sameSet(codesFor('lying', null, dims), codesFor('upright', null, dims));
  if (level === 'all') return !sameSet(codesFor('all', null, dims), codesFor('lying', null, dims));
  return true;
}

