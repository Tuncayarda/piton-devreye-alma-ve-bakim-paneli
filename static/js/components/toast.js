// The toast strip at the bottom. It is aria-live, so a screen reader hears it.
import { $ } from '../core/dom.js';

let timer = null;

export function notify(text, kind = 'info', duration = 4200) {
  const box = $('#toast');
  if (!box) return;
  box.textContent = String(text);
  box.dataset.kind = kind;
  box.hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => { box.hidden = true; }, duration);
}

export const showError = (m) => notify(m, 'error', 6000);
export const showSuccess = (m) => notify(m, 'success');
