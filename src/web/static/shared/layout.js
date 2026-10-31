// The hideable side panel of the viewer screens and the resizable item drawer; state kept in localStorage.
import { $, el, store } from './util.js';
import { icon } from './icons.js';
import { S } from './state.js';

// Hides or shows the side panel (the toolbar button `#rcol` flips it); `id` and `key` name the panel and its stored state.
export function setCollapsed(id, key, on, persist = true) {
  $(id).classList.toggle('collapsed', on);
  $('vbody').classList.toggle('nopanel', on);
  $('rcoltext').textContent = on ? 'Hiện panel' : 'Ẩn panel';
  $('rcol').setAttribute('aria-expanded', String(!on));
  if (persist) store.set(key, on ? '1' : '0');
}
setCollapsed('right', 'web.rightCollapsed', store.get('web.rightCollapsed') === '1', false);
$('rcol').onclick = () => setCollapsed('right', 'web.rightCollapsed', !$('right').classList.contains('collapsed'));

let drawerH = Number(store.get('web.drawerHeight')) || 260;
const clampH = (h) => Math.max(80, Math.min(h, window.innerHeight * 0.5));
export function applyDrawer() {
  const d = $('drawer');
  d.classList.toggle('open', S.drawerOpen);
  d.style.height = S.drawerOpen ? `${clampH(drawerH)}px` : '';
  $('dtoggle').replaceChildren(icon(S.drawerOpen ? 'chevron-down' : 'chevron-right'),
    el('span', {}, `Danh sách kiện (${$('dtoggle').dataset.n ?? 0})` + (S.drawerOpen ? ' — bấm một dòng để tô kiện trong cảnh 3D' : ' — bấm để mở')));
  $('dtoggle').setAttribute('aria-expanded', String(S.drawerOpen));
}
$('dtoggle').onclick = () => { S.drawerOpen = !S.drawerOpen; applyDrawer(); };
$('dgrip').onpointerdown = (e) => {
  const y0 = e.clientY, h0 = $('drawer').getBoundingClientRect().height;
  $('dgrip').setPointerCapture(e.pointerId);
  $('dgrip').onpointermove = (m) => { drawerH = clampH(h0 + y0 - m.clientY); applyDrawer(); };
  $('dgrip').onpointerup = () => {
    $('dgrip').onpointermove = null; $('dgrip').onpointerup = null;
    store.set('web.drawerHeight', Math.round(drawerH));
  };
};
