// The language control, and the one place that applies the catalogue.
//
// Two kinds of text have to be translated. Everything a view builds goes
// through `t()` at draw time, so a redraw is enough. The application shell in
// index.html is written once and never rebuilt, so its nodes carry
// `data-i18n` / `data-i18n-title` / `data-i18n-aria` and are refreshed here.
//
// Switching goes through the SERVER: it is the server that stores the choice
// (browser storage is closed to this application) and the server that
// translates its own errors and queue rows. The reply carries the whole new
// catalogue, so there is no moment where half the screen is in one language
// and half in the other.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { applyCatalogue, language, languages, t } from '../core/i18n.js';
import { showError } from './toast.js';

// What each language calls ITSELF. Never translated — a user looking for
// their own language should not have to know the current one.
const ENDONYM = { en: 'EN', tr: 'TR' };
const FULL_NAME = { en: 'English', tr: 'Türkçe' };

// Applies the catalogue to the shell nodes written in index.html.
export function applyStaticText(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of root.querySelectorAll('[data-i18n-title]')) {
    node.title = t(node.dataset.i18nTitle);
  }
  for (const node of root.querySelectorAll('[data-i18n-aria]')) {
    node.setAttribute('aria-label', t(node.dataset.i18nAria));
  }
  document.documentElement.lang = language();
}

// One button per language, the current one pressed. A dropdown was not worth
// it for two options and hid which language was active.
// Every picker on the page — the role screen has its own, because the
// language has to be changeable before a session is opened.
const HOSTS = ['#language-picker', '#role-language-picker'];

export function renderAll(onChange) {
  for (const selector of HOSTS) render(document.querySelector(selector),
                                       onChange);
}

export function render(host, onChange) {
  if (!host) return;
  const current = language();
  fill(host, languages().map(code => el('button', {
    type: 'button',
    class: 'btn btn-small language-btn',
    'aria-pressed': String(code === current),
    title: FULL_NAME[code] || code,
    text: ENDONYM[code] || code.toUpperCase(),
    onclick: () => select(code, onChange),
  })));
}

async function select(code, onChange) {
  if (code === language()) return;
  try {
    applyCatalogue(await api.setLanguage(code));
  } catch (e) {
    showError(e.message);
    return;
  }
  applyStaticText();
  renderAll(onChange);
  if (onChange) onChange();
}

// Read at start-up, before the first paint: no screen is ever drawn with
// message keys showing.
export async function load() {
  applyCatalogue(await api.language());
  applyStaticText();
}
