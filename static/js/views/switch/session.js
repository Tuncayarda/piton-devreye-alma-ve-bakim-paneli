// Signing in to a switch.
//
// THE PASSWORD IS NEVER STORED ON THIS SIDE. It is read out of the row's box,
// put straight into `api.switchLogin`, and dropped the moment the switch
// accepts it. It does not touch `core/store.js` — which would refuse the key
// anyway — and nothing here is written to disk. The server keeps it in memory
// only (panel/credentials.py) and never sends it back.
//
// THERE IS NO DIALOG. There used to be one, opening over the screen for each
// switch in turn; the boxes are on the row now (see discovery.js), so signing
// into a bench of six is six pairs of fields on one list rather than six
// modals over it.

import { api } from '../../core/api.js';
import { showSuccess } from '../../components/toast.js';
import { t } from '../../core/i18n.js';
import { forgetTyped } from './state.js';

// Does this failure mean "sign in", rather than "it is not there"?
export function needsCredentials(error) {
  return !!(error && (error.status === 401 || (error.body && error.body.auth)));
}

/**
 * Try the account typed on the row. Resolves true when the switch took it.
 *
 * `applyToGroup` is always on: a train set's switches are opened by one
 * account, and the group is the same one the IP assignment screen reads
 * (`panel.switch.device.GROUP`) — so signing in here spares that screen from
 * asking. Making it a checkbox per row would be a question asked six times
 * with the same answer.
 */
export async function signIn(ip, user, password) {
  await api.switchLogin(ip, user, password, true);
  // Typed, sent, accepted — and now gone from this side.
  forgetTyped(ip);
  showSuccess(t('switch.authSignedIn', { ip }));
  return true;
}
