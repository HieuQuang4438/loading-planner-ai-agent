// The page frame both modes share: screens switched by the URL hash, popovers and menus of the top
// bar and toolbar, the delete confirmation and the undo toast. A page declares its screens; this file knows no mode.
import { $, el } from './util.js';
import { icon } from './icons.js';

// ---- router --------------------------------------------------------------------------------------------------------

// createRouter({ routes, home })
//   routes  { name: { section, kind, allowed?(arg), enter?(arg) } } keyed by the first hash segment (`#/name/arg`).
//           `section` is the id of the <section class="screen"> to show, `kind` goes to <body data-screen>.
//   home    the route used for an empty hash and for a route whose `allowed` says no.
//   onShow  called with the current route after every screen change (the page sets its tab title there).
// `go(name, arg)` pushes a history entry and shows the screen at once; the back button comes through `hashchange`.
export function createRouter({ routes, home, onShow = () => {} }) {
  let current = null;
  const parse = () => {
    const [name, arg] = location.hash.replace(/^#\/?/, '').split('/');
    return { name: name || home, arg };
  };
  const hashOf = (name, arg) => `#/${name}${arg === undefined || arg === null ? '' : `/${arg}`}`;

  function apply() {
    let { name, arg } = parse();
    let route = routes[name];
    if (!route || (route.allowed && !route.allowed(arg))) {
      name = home; arg = undefined; route = routes[home];
      history.replaceState(null, '', hashOf(name));
    }
    for (const s of document.querySelectorAll('.screen')) s.hidden = s.id !== route.section;
    document.body.dataset.screen = route.kind;
    current = { name, arg, kind: route.kind };
    route.enter?.(arg);
    onShow(current);
  }
  function go(name, arg) {
    const hash = hashOf(name, arg);
    if (location.hash !== hash) history.pushState(null, '', hash);
    apply();
  }
  window.addEventListener('hashchange', apply);
  return { go, apply, current: () => current };
}

// Rows, cards and violation lines that open something also open on Enter or Space.
document.addEventListener('keydown', (e) => {
  const t = e.target;
  if ((e.key === 'Enter' || e.key === ' ') && t.matches?.('tr.click, li.click, .cell')) { e.preventDefault(); t.click(); }
});

// ---- popovers and menus ----------------------------------------------------------------------------------------------

// Opens `panel` under `button` on click; closes on a click outside, Esc, or `close()`. `onOpen` runs when it opens.
export function popover(button, panel, { onOpen = () => {} } = {}) {
  button.setAttribute('aria-haspopup', 'true');
  button.setAttribute('aria-expanded', 'false');
  const close = () => { panel.hidden = true; button.setAttribute('aria-expanded', 'false'); };
  const open = () => { panel.hidden = false; button.setAttribute('aria-expanded', 'true'); onOpen(); };
  button.addEventListener('click', () => (panel.hidden ? open() : close()));
  document.addEventListener('click', (e) => { if (!panel.hidden && !e.target.closest('dialog') && !panel.contains(e.target) && !button.contains(e.target)) close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !panel.hidden && !document.querySelector('dialog[open]')) { close(); button.focus(); e.stopPropagation(); }
  }, true);
  panel.hidden = true;
  return { open, close };
}

// ---- delete confirmation and undo toast ---------------------------------------------------------------------------------

// A modal alert dialog; resolves true on the red button, false on Cancel, Esc or a click outside. Cancel is focused first.
export function confirmDelete({ title, message, okLabel }) {
  const dialog = el('dialog', { class: 'confirm' });
  dialog.setAttribute('role', 'alertdialog');
  dialog.setAttribute('aria-labelledby', 'confirmttl');
  dialog.setAttribute('aria-describedby', 'confirmmsg');
  const cancel = el('button', { type: 'button' }, 'Hủy');
  const ok = el('button', { type: 'button', class: 'danger' }, icon('trash'), okLabel);
  dialog.append(el('div', { class: 'cbd' }, el('h2', { id: 'confirmttl' }, title), el('p', { id: 'confirmmsg' }, message)),
    el('div', { class: 'cft' }, cancel, ok));
  document.body.append(dialog);
  return new Promise((resolve) => {
    let answer = false;
    cancel.onclick = () => dialog.close();
    ok.onclick = () => { answer = true; dialog.close(); };
    dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
    dialog.showModal();
    cancel.focus();
  });
}

// A modal dialog with one text field; resolves the trimmed text on Save or Enter, null on Cancel, Esc or a click outside.
export function askText({ title, label, value = '', okLabel = 'Lưu', maxLength = 200 }) {
  const dialog = el('dialog', { class: 'confirm' });
  dialog.setAttribute('aria-labelledby', 'askttl');
  const input = el('input', { type: 'text', value, maxLength, required: true });
  const cancel = el('button', { type: 'button' }, 'Hủy');
  const ok = el('button', { type: 'submit', class: 'primary' }, okLabel);
  const form = el('form', {}, el('div', { class: 'cbd' }, el('h2', { id: 'askttl' }, title), el('label', { class: 'asklabel' }, label, input)),
    el('div', { class: 'cft' }, cancel, ok));
  dialog.append(form);
  document.body.append(dialog);
  return new Promise((resolve) => {
    let answer = null;
    cancel.onclick = () => dialog.close();
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      answer = text;
      dialog.close();
    });
    dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
    dialog.showModal();
    input.select();
  });
}

const TOAST_MS = 6000;
let toastTimer = null;
// A message at the bottom of the page for 6 s; with `undo` it carries a "Hoàn tác" button that runs it and closes the toast.
export function toast(message, { undo = null } = {}) {
  let box = $('toast');
  if (!box) {
    box = el('div', { id: 'toast', role: 'status' });
    document.body.append(box);
  }
  const close = () => { box.hidden = true; clearTimeout(toastTimer); };
  box.replaceChildren(el('span', {}, message), ...(undo ? [el('button', { type: 'button', onclick: () => { undo(); close(); } }, 'Hoàn tác')] : []));
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(close, TOAST_MS);
}

// ---- delete with confirmation and undo (lot lines, containers) ------------------------------------------------------------

// Asks first; on yes runs `remove()` and shows "Đã xóa …" with "Hoàn tác" (`undo`) for 6 s.
export async function deleteWithUndo({ title, message, okLabel, done, remove, undo }) {
  if (!(await confirmDelete({ title, message, okLabel }))) return false;
  remove();
  toast(done, { undo });
  return true;
}
