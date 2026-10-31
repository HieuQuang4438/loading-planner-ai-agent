// Colour of an item type (loại kiện) from its id alone, so deleting or adding another type never changes it (ui.md §3).
// Pure functions, no three.js: the scene, the tables and the lot form share them.

// FNV-1a 32-bit hash of the id.
function hash(id) {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

// Hue in [0, 1): the hash spread by the golden ratio so that ids that differ in one character land far apart.
export function lineHue(id) {
  return (hash(String(id)) * 0.6180339887498949) % 1;
}

// Lightness in {0.45, 0.57, 0.69} from other bits of the hash, to tell apart ids whose hues come out close.
export function lineLightness(id) {
  return 0.45 + 0.12 * ((hash(String(id)) >>> 13) % 3);
}

export const LINE_SATURATION = 0.7;
export const lineCss = (id) => `hsl(${Math.round(lineHue(id) * 360)} ${LINE_SATURATION * 100}% ${Math.round(lineLightness(id) * 100)}%)`;
