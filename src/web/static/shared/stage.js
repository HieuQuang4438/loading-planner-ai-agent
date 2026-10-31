// The viewer's DOM (toolbar, stage, replay bar, item drawer, side panel), built in one place so the demo and the service
// page cannot drift apart. The other shared modules look these ids up when they load, so a page must call
// mountViewer before it imports scene.js, player.js, panels.js or layout.js (dynamic `import()` after the call).
import { $, el } from './util.js';
import { icon } from './icons.js';

const SPEEDS = [['600', 'Chậm'], ['200', 'Vừa'], ['60', 'Nhanh'], ['15', 'Rất nhanh']];
const COLORS = [['line', 'Màu: loại kiện'], ['load', 'Màu: tải đè so với giới hạn'], ['tiers', 'Màu: tầng so với giới hạn'], ['support', 'Màu: phần đáy được đỡ']];

const hidden = (tag, id, props = {}, ...kids) => el(tag, { id, style: 'display:none', ...props }, ...kids);
const box = (title, id, text) => el('section', { class: 'box', id: `box-${id}` }, el('h2', {}, title), el('div', { id, class: 'muted' }, text));
const iconButton = (id, name, label, props = {}) => {
  const b = el('button', { id, class: 'icon', title: label, ...props }, icon(name));
  b.setAttribute('aria-label', label);
  return b;
};

// mountViewer({ actions, resultExtra })
//   The page provides <div id="vtool">, <div id="center"> and <aside id="right"> in its viewer screen.
//   actions      nodes placed at the right of the toolbar, before the "hide panel" button (e.g. "Chỉnh tay", "Xuất")
//   The toolbar also holds "Trước i/n Sau" (one container screen), the scene card holds the colour select and the label
//   switch (top right of the scene), the replay bar only replay controls and speed.
//   resultExtra  nodes placed under #result inside the "Kết quả" box
export function mountViewer({ actions = [], resultExtra = [] }) {
  const select = (id, opts, sel, title) => el('select', { id, ...(title ? { title } : {}) },
    opts.map(([v, t]) => el('option', { value: v, ...(v === sel ? { selected: true } : {}) }, t)));
  const hideBtn = el('button', { id: 'rcol', title: 'Ẩn hoặc hiện panel bên phải' }, icon('panel-right'), el('span', { id: 'rcoltext' }, 'Ẩn panel'));
  $('vtool').append(
    el('button', { id: 'vback' }, icon('arrow-left'), el('span', { id: 'vbacktext' })),
    el('h1', { id: 'viewtitle' }),
    el('span', { id: 'srclabel' }),
    el('span', { class: 'spacer' }),
    el('div', { class: 'vact' }, ...actions, hideBtn,
      hidden('span', 'nav', { class: 'navbox' },
        el('button', { id: 'prevc', title: 'Container trước (←)' }, icon('chevron-left'), 'Trước'),
        el('span', { id: 'navpos', class: 'navpos' }),
        el('button', { id: 'nextc', title: 'Container sau (→)' }, 'Sau', icon('chevron-right'))),
      // No visible "back to the grid" button: "← Kết quả" in the toolbar and Esc do it. The element stays because the
      // manual packing screen drives the same step through it (its own "Lưới" button clicks it).
      el('button', { id: 'back', hidden: true, title: 'Về lưới (Esc)' })));

  const stage = el('div', { id: 'stage' },
    // The 3D scene card: the scene with its options at the top right, then the replay bar under it (not over it), so the
    // container fills the frame. Manual packing puts one short caption at the top left.
    el('div', { id: 'viewport' },
      hidden('canvas', 'canvas', { style: 'visibility:hidden' }),
      el('div', { id: 'banner' }, el('span', { id: 'bannertext' })),
      el('div', { id: 'top' },
        el('div', { id: 'viewopts' },
          el('div', { class: 'optbar' },
            select('colorby', COLORS, 'line', 'Tô màu kiện theo'),
            el('label', { class: 'chk', title: 'Chữ mã loại kiện trên 5 mặt mỗi kiện (trừ đáy); mặt có cạnh nhỏ hơn 0,15 m không có chữ' },
              el('input', { type: 'checkbox', id: 'showlabels' }), 'Nhãn mã loại kiện')),
          hidden('div', 'colorkey', { class: 'muted' })))),
    hidden('div', 'hud', {},
      el('div', { class: 'row' },
        iconButton('first', 'skip-back', 'Về đầu'),
        iconButton('prev', 'chevron-left', 'Lùi một kiện'),
        el('button', { id: 'play' }, icon('play'), 'Phát'),
        iconButton('next', 'chevron-right', 'Tiến một kiện'),
        iconButton('last', 'skip-forward', 'Tới cuối'),
        el('input', { id: 'slider', type: 'range', min: '0', max: '0', value: '0', 'aria-label': 'Bước tua' }),
        select('speed', SPEEDS, '200', 'Tốc độ tua')),
      hidden('div', 'pickinfo'),
      el('div', { id: 'stepinfo', class: 'stepinfo' }),
      el('div', { id: 'ordernote', class: 'muted' })),
    // The result page (tiles, container cards, item types) and, in manual packing, the grid of containers.
    el('div', { id: 'resview' },
      el('div', { id: 'restop', class: 'muted' }),
      el('div', { id: 'restiles', class: 'kpis' }),
      el('div', { id: 'reshead', class: 'sechead' }, el('h2', {}, 'Container'),
        el('span', { class: 'muted hint-view' }, 'Bấm một container để xem 3D và tua lại'),
        el('span', { class: 'muted hint-edit' }, 'Bấm một container để mở 3D và chỉnh')),
      el('div', { id: 'grid' }),
      el('div', { id: 'reslines' }),
      el('div', { id: 'resextra' })));
  const drawer = el('div', { id: 'drawer', hidden: true },
    el('div', { id: 'dgrip', title: 'Kéo để đổi chiều cao' }),
    el('button', { id: 'dtoggle' }),
    el('div', { id: 'dbody' }));
  drawer.querySelector('#dtoggle').setAttribute('aria-expanded', 'false');
  $('center').append(stage, drawer);

  $('right').append(
    el('section', { class: 'box', id: 'box-result' }, el('h2', {}, 'Kết quả'), el('div', { id: 'result', class: 'muted' }, 'Chưa có.'), ...resultExtra),
    box('Container', 'cinfo', 'Bấm một ô trong lưới container.'),
    el('section', { class: 'box', id: 'box-clines', hidden: true }, el('div', { id: 'clines' })),
    box('Loại kiện', 'legend', 'Chưa có.'));
}

// The toolbar of the viewer screens: the screen's title and its contextual back button.
// back: { label, onclick } or null (no back button).
// "Container #<n> · <type>": the title of the one-container screen.
export const containerTitle = (cur) => (cur ? `Container #${cur.data.k} · ${cur.data.type}` : 'Container');

export function setChrome({ title, back = null, source }) {
  $('viewtitle').textContent = title;
  if (source !== undefined) $('srclabel').textContent = source;
  $('vback').hidden = !back;
  if (back) {
    $('vbacktext').textContent = back.label;
    $('vback').onclick = back.onclick;
  }
}
