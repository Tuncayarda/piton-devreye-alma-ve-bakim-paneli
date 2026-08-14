// Port text and addressing — pure functions, no DOM.
//
// "11-14, 18-19, 21" is the same format as the server's
// ip_assign.format_ports / parse_ports. The text is produced here and parsed
// here too, because going to the server on every keystroke (and blanking the
// screen on invalid text) is not the right behaviour while the user types.

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
        return { ports: [], error: `Invalid port range: ${part}` };
      }
      for (let n = start; n <= end; n += 1) found.push(n);
    } else {
      const n = Number(part);
      if (!Number.isInteger(n) || n < 1) {
        return { ports: [], error: `Invalid port: ${part}` };
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
        error: 'Ports with no device defined on this switch: '
          + outside.join(', '),
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
function maskPrefix(text) {
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
      return 'Enter both the first and the last address of the range.';
    }
    if (!isIpv4(first) || !isIpv4(last)) {
      return 'Use valid IPv4 addresses in the range.';
    }
    const count = ipNumber(last) - ipNumber(first) + 1;
    if (count <= 0) return 'The last address cannot come before the first.';
    if (count > SEARCH_LIMIT) {
      return `That range covers ${count} addresses; at most ${SEARCH_LIMIT} `
        + 'can be scanned.';
    }
    return '';
  }
  const network = String(networkText || '').trim();
  const mask = String(maskText || '').trim();
  if (!network && !mask) return 'Enter the search network and the netmask.';
  if (!isIpv4(network)) return 'The search network must be a valid IPv4 address';
  const prefix = maskPrefix(mask);
  if (prefix === null) {
    return 'The mask must be written as 255.255.255.0 or 24';
  }
  const count = prefix >= 31 ? 1 : (2 ** (32 - prefix)) - 2;
  if (count > SEARCH_LIMIT) {
    return `That netmask covers ${count} addresses; at most ${SEARCH_LIMIT} `
      + 'can be scanned. Narrow the mask or give an address range.';
  }
  return '';
}
