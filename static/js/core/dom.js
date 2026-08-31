// DOM helpers.
//
// No text coming from a device is ever written with innerHTML. Everything
// goes through textContent, and `el()` below offers no other route. A device
// named "<img onerror=...>" shows up on screen as exactly that text and does
// not run.

export function el(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') { node.textContent = String(value); continue; }
    if (key === 'class') { node.className = String(value); continue; }
    if (key === 'style') {
      node.setAttribute('style', String(value));
      continue;
    }
    if (key === 'dataset') {
      for (const [dataKey, dataValue] of Object.entries(value)) {
        if (dataValue !== null && dataValue !== undefined) {
          node.dataset[dataKey] = String(dataValue);
        }
      }
      continue;
    }
    if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2), value);
      continue;
    }
    if (value === true) { node.setAttribute(key, ''); continue; }
    node.setAttribute(key, String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(
      child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(root) {
  while (root.firstChild) root.removeChild(root.firstChild);
  return root;
}

export function fill(root, children) {
  clear(root);
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    root.append(
      child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return root;
}

export const $ = (selector, root = document) => root.querySelector(selector);

// Keeps the scroll position across a redraw.
//
// Screens are rebuilt on every state change. `fill()` empties the container,
// the browser resets scrollTop, and when the content comes back that zero
// stays: a light refresh every few seconds threw a long list back to the top
// each round. So the position is captured first and restored afterwards.
export function preserveScroll(outer, draw) {
  const outerTop = outer ? outer.scrollTop : 0;
  const innerPositions = outer
    ? [...outer.querySelectorAll('.table-wrap')].map(
      e => [e.scrollLeft, e.scrollTop])
    : [];

  draw();

  if (!outer) return;
  // Restore once the layout has settled with the new content.
  const apply = () => {
    if (outerTop && outer.scrollHeight > outer.clientHeight) {
      outer.scrollTop = outerTop;
    }
    const current = outer.querySelectorAll('.table-wrap');
    for (let i = 0; i < current.length && i < innerPositions.length; i += 1) {
      const [left, top] = innerPositions[i];
      if (left) current[i].scrollLeft = left;
      if (top) current[i].scrollTop = top;
    }
  };
  apply();
  requestAnimationFrame(apply);
}

// Is focus in a box the operator is working in? Redrawing would rebuild the
// box mid-word and throw away the caret and the half-typed value (fields
// save on change, i.e. when focus leaves). app.js asks this before it
// redraws the open view on a store publish; a view that repaints ITSELF
// (the adb and ip screens' own draw()) has to ask the same question, or the
// protection app.js gives its renders would quietly not apply to theirs.
export function focusHeld(root) {
  const active = document.activeElement;
  if (!active || !root || !root.contains(active)) return false;
  return active.matches(
    'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]),'
    + ' textarea, select, [contenteditable="true"]');
}

// SVG elements live in their own namespace: createElement('svg') does not
// produce valid SVG and shows nothing. Hence these two helpers rather than
// el().
const SVG_NS = 'http://www.w3.org/2000/svg';

export function svg(attributes = {}, children = []) {
  const node = document.createElementNS(SVG_NS, 'svg');
  const merged = {
    viewBox: '0 0 20 20', width: '15', height: '15',
    'aria-hidden': 'true', ...attributes,
  };
  for (const [key, value] of Object.entries(merged)) {
    if (value !== null && value !== undefined) {
      node.setAttribute(key, String(value));
    }
  }
  for (const [childTag, childAttributes] of children) {
    const child = document.createElementNS(SVG_NS, childTag);
    for (const [key, value] of Object.entries(childAttributes || {})) {
      if (value !== null && value !== undefined) {
        child.setAttribute(key, String(value));
      }
    }
    node.append(child);
  }
  return node;
}

// A line icon — the path data is fixed and never comes from outside.
export function icon(paths, size = 15) {
  return svg({
    width: size, height: size, fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.5', 'stroke-linecap': 'round',
  }, [].concat(paths).map(d => ['path', { d }]));
}

// Focus trap — Tab must not leave an open dialog.
export function focusTrap(container, close) {
  const selector =
    'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';
  function trap(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const focusable = [...container.querySelectorAll(selector)]
      .filter(node => !node.disabled && node.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  container.addEventListener('keydown', trap);
  return () => container.removeEventListener('keydown', trap);
}


// Mark a field as invalid and show (or clear) the message under it.
// Lives here rather than beside one form: every screen that validates as
// the user types needs exactly this, and it is nothing but DOM.
export function showFieldWarning(input, warning, message) {
  input.setAttribute('aria-invalid', String(!!message));
  warning.textContent = message;
  warning.hidden = !message;
}
