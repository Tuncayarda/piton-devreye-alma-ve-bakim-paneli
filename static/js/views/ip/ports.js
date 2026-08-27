// Port text and addressing — pure functions, no DOM.
//
// "11-14, 18-19, 21" is the same format as the server's
// ip_assign.format_ports / parse_ports. The text is produced here and parsed
// here too, because going to the server on every keystroke (and blanking the
// screen on invalid text) is not the right behaviour while the user types.
//
// No DOM, but not free of the catalogue either: the messages these return
// are read by the user, so they come from the same place as every other
// sentence on screen.

import { protectedPortsFor } from './state.js';
import { t } from '../../core/i18n.js';

// The reading of a `tried[].state` code from the server. The codes are the
// contract (panel/ip_assign/ports.py SWITCH_STATE_LABEL); the words are
// chosen here.
const SWITCH_STATE = {
  auth: 'ip.switchStateAuth',
  unreachable: 'ip.switchStateUnreachable',
  unreadable: 'ip.switchStateUnreadable',
  empty: 'ip.switchStateEmpty',
  read: 'ip.switchStateRead',
};

export function switchStateLabel(state) {
  const key = SWITCH_STATE[state];
  return key ? t(key) : String(state || '');
}

// A panel DTO may exist even when the switch did not answer: the server then
// draws the physical layout from DeviceMap and marks its source accordingly.
// That fallback is useful for orientation, but it is not proof that an IP run
// can reach the switch. Keep this check pure so readiness cannot accidentally
// treat a DeviceMap panel as live switch data.
export function activePanelError(panel, plannedSwitch, loading = false) {
  if (!panel) {
    return !loading && plannedSwitch ? t('ip.switchUnreachable') : '';
  }
  if (panel.hasCredentials === false) {
    return t('ip.noSwitchCredentials', { switch: panel.switchName });
  }
  if (panel.source !== 'switch') {
    return panel.note || t('ip.switchUnreachable');
  }
  return '';
}

export function formatPorts(ports) {
  const sorted = [...new Set(ports.map(Number))]
    .filter(Number.isInteger).sort((a, b) => a - b);
  if (!sorted.length) return '';
  const parts = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (let i = 1; i <= sorted.length; i += 1) {
    const current = i < sorted.length ? sorted[i] : null;
    if (current === previous + 1) { previous = current; continue; }
    parts.push(start === previous ? String(start) : `${start}-${previous}`);
    start = current; previous = current;
  }
  return parts.join(', ');
}

export function parsePorts(text, allowed) {
  const found = [];
  for (const raw of String(text || '').replace(/[;\s]+/g, ',').split(',')) {
    const part = raw.trim();
    if (!part) continue;
    if (part.includes('-')) {
      const [a, b] = part.split('-');
      const start = Number(a);
      const end = Number(b);
      if (!Number.isInteger(start) || !Number.isInteger(end) || end < start
          || start < 1 || a === '' || b === '') {
        return {
          ports: [], error: t('ip.invalidPortRange', { part }),
        };
      }
      for (let n = start; n <= end; n += 1) found.push(n);
    } else {
      const n = Number(part);
      if (!Number.isInteger(n) || n < 1) {
        return { ports: [], error: t('ip.invalidPort', { part }) };
      }
      found.push(n);
    }
  }
  if (allowed && allowed.length) {
    const set = new Set(allowed);
    const outside = [...new Set(found)].filter(n => !set.has(n))
      .sort((a, b) => a - b);
    if (outside.length) {
      return {
        ports: [],
        error: t('ip.portsWithoutDevice', { ports: outside.join(', ') }),
      };
    }
  }
  return { ports: [...new Set(found)].sort((a, b) => a - b), error: '' };
}

// ── addressing ──────────────────────────────────────────────────────────
// Devices leave the factory on the same address (10.1.1.12); the run opens a
// port and writes the DeviceMap IP to whatever device comes up there. A device
// configured earlier is not on the factory address — then the given network is
// scanned.
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

export function isIpv4(text) {
  const match = IPV4.exec(String(text || '').trim());
  return !!match && match.slice(1).every(part => Number(part) <= 255);
}

// A mask can be written as 255.255.255.0 or as "24".
export function maskPrefix(text) {
  const raw = String(text || '').trim();
  if (/^\d{1,2}$/.test(raw)) {
    const n = Number(raw);
    return n >= 0 && n <= 32 ? n : null;
  }
  if (!isIpv4(raw)) return null;
  const bits = raw.split('.').map(Number)
    .map(part => part.toString(2).padStart(8, '0')).join('');
  return /^1*0*$/.test(bits) ? bits.replace(/0/g, '').length : null;
}

export const SEARCH_LIMIT = 512;   // same as ip_assign.SEARCH_LIMIT

// The mask written together with the newly assigned address. It is normally
// the project's /24, but a display commissioned on a bench is sometimes given
// a /8 so it stays reachable from the whole 10.0.0.0 range. Empty means "use
// the plan's default" and is not an error.
//
// The bounds mirror panel/ip_assign/addressing.py; the server checks them
// again, this only saves the round trip.
export function validateTargetMask(text, low = 8, high = 30) {
  const raw = String(text || '').trim().replace(/^\//, '');
  if (!raw) return '';
  const prefix = maskPrefix(raw);
  if (prefix === null) return t('ip.maskInvalid');
  if (prefix < low || prefix > high) {
    return t('error.targetMaskOutOfRange', { low, high });
  }
  return '';
}

function ipNumber(text) {
  return String(text).trim().split('.')
    .reduce((total, part) => (total * 256) + Number(part), 0);
}

// The area to search can be given two ways: network + mask, or an explicit
// address range. If the project mask is wide (/8 in the top bar) opening the
// network means millions of addresses; in that setup a range is the only way
// to narrow it. With a range given the network/mask is never used (nor on the
// server).
export function validateSearch(networkText, maskText, firstText, lastText) {
  const first = String(firstText || '').trim();
  const last = String(lastText || '').trim();
  if (first || last) {
    if (!first || !last) {
      return t('ip.rangeNeedsBoth');
    }
    if (!isIpv4(first) || !isIpv4(last)) {
      return t('ip.rangeNeedsIpv4');
    }
    const count = ipNumber(last) - ipNumber(first) + 1;
    if (count <= 0) return t('ip.rangeReversed');
    if (count > SEARCH_LIMIT) {
      return t('ip.rangeTooWide', { count, limit: SEARCH_LIMIT });
    }
    return '';
  }
  const network = String(networkText || '').trim();
  const mask = String(maskText || '').trim();
  if (!network && !mask) return t('ip.searchNeedsNetwork');
  if (!isIpv4(network)) return t('ip.searchNetworkInvalid');
  const prefix = maskPrefix(mask);
  if (prefix === null) return t('ip.maskInvalid');
  const count = prefix >= 31 ? 1 : (2 ** (32 - prefix)) - 2;
  if (count > SEARCH_LIMIT) {
    return t('ip.maskTooWide', { count, limit: SEARCH_LIMIT });
  }
  return '';
}


// Port text the user typed, judged against the plan: parseable, and not
// touching a port the run must leave alone. Still no DOM — the caller
// decides where the returned sentence is shown.
// The single validation point for the text in the field: format + defined on
// this switch + the ports the run must not touch. Returns the error text, or
// '' when there is none.
export function validatePorts(text, allowed, plan) {
  const { ports, error } = parsePorts(text, allowed);
  if (error) return error;
  const protectedPorts = new Map(protectedPortsFor(plan));
  const clashing = ports.filter(port => protectedPorts.has(port));
  if (clashing.length) {
    const port = clashing[0];
    return t('ip.portProtected', {
      port, reason: protectedPorts.get(port),
    });
  }
  return '';
}
