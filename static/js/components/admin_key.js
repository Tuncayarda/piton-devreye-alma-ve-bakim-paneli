// The service key — the only way into admin mode on a customer package —
// and the questions the panel asks about it: the once-a-second look at the
// USB slot, the dialog offered when a recognised key appears, and the two
// moves in and out of admin mode themselves.
//
// There is no socket, so the panel asks; `generation` counts OBSERVED
// CHANGES rather than polls, so asking twice a second still means "nothing
// has happened" almost every time (see panel/adminkey/watcher.py).
//
// LIFTED OUT OF app.js AS A FACTORY for the same reason as
// components/remote_session.js: app.js starts the application on import, so
// nothing in it could be tested without reading the file as text.
// `createAdminKey()` takes its dependencies with the real ones as defaults;
// app.js passes only `applyEdition` (its own) and `pollRemote` (the remote
// session's, ridden on this beat), and the tests pass stand-ins
// (tests/js/admin_key_test.js).

import { api as liveApi } from '../core/api.js';
import { state as liveState, patch as livePatch } from '../core/store.js';
import * as liveDialog from './dialog.js';
import {
  notify as liveNotify, showError as liveShowError,
  showSuccess as liveShowSuccess,
} from './toast.js';
import { t as liveT } from '../core/i18n.js';

// The service key: a USB stick appearing is a physical act, and a second is
// the difference between "the panel noticed" and "the panel is broken".
// The cost is nothing but reading back what the panel's own watcher already
// established (see panel/adminkey/watcher.py), not a device read, so this
// round is not held back by a running job the way the scan rounds are.
export const ADMIN_KEY_INTERVAL = 1000;

export function createAdminKey(overrides = {}) {
  const {
    api, state, patch, dialog, t, notify, showSuccess, showError,
    // app.js's own: applying a whole edition body and redrawing on a mode
    // change.
    applyEdition,
    // On the same beat rather than a timer of its own: both questions are
    // "has the way in gone away", both are cheap, and two timers would mean
    // two answers arriving out of step about one mode. The remote session
    // hands its poll in here so neither module has to import the other.
    pollRemote = async () => {},
    wait = (fn, ms) => setTimeout(fn, ms),
    clearWait = (id) => clearTimeout(id),
  } = {
    api: liveApi, state: liveState, patch: livePatch, dialog: liveDialog,
    t: liveT, notify: liveNotify, showSuccess: liveShowSuccess,
    showError: liveShowError,
    ...overrides,
  };

  let timer = null;
  // The observation the user has already said no to. Without this the
  // question would come back every two seconds; with it, it comes back only
  // after the key has been taken out and put in again.
  let declinedGeneration = -1;
  let askingAboutKey = false;

  async function enterAdmin() {
    try {
      applyEdition(await api.adminMode(true));
      showSuccess(t('adminkey.entered'));
    } catch (e) {
      showError(e.message);
    }
  }

  async function leaveAdmin() {
    try {
      applyEdition(await api.adminMode(false));
      notify(t('adminkey.left'));
    } catch (e) {
      showError(e.message);
    }
  }

  function loop() {
    clearWait(timer);
    timer = wait(async () => {
      try {
        const seen = await api.adminKey();
        const previous = state.adminKey;
        patch({ adminKey: seen });
        // `withoutKey` as well as the generation: the secret appearing or
        // going away changes what may be done without anything happening to
        // a volume, so the observation counter would not move.
        if (!previous || previous.generation !== seen.generation
            || previous.withoutKey !== seen.withoutKey) {
          await onKeyChanged(seen, previous);
        }
      } catch { /* the next round retries */ }
      await pollRemote();
      loop();
    }, ADMIN_KEY_INTERVAL);
  }

  function stop() {
    clearWait(timer);
    timer = null;
  }

  async function onKeyChanged(seen, previous) {
    // Admin mode may have just ended on its own: the key was pulled — or the
    // secret file taken away — and the server dropped it (or is holding it
    // until a write finishes).
    if (state.mode === 'admin' && !seen.recognised && !seen.withoutKey) {
      try { applyEdition(await api.edition()); } catch { /* next round */ }
      if (state.mode !== 'admin') {
        // Which of the two went away decides which sentence is true. Saying
        // "the key was removed" to somebody who deleted the secret file
        // would send them looking at a USB port for no reason.
        const pulled = !!(previous && previous.recognised);
        notify(t(pulled ? 'adminkey.removed' : 'adminkey.closed'));
      }
      return;
    }
    if (state.mode === 'admin' || !seen.recognised) {
      // A key was found and NOT recognised: worth saying, because a stick
      // that looks right and is not is otherwise indistinguishable from no
      // stick.
      if (seen.present && !seen.recognised) {
        // "denied" is not a bad key, it is a key nobody was allowed to read:
        // the operating system gates removable volumes and the panel runs
        // elevated (see panel/adminkey/keyfile.py). Said even at launch —
        // `previous` null — because there is something to go and do about
        // it, and it will not fix itself on the next poll.
        if (seen.reason === 'denied') notify(t('adminkey.denied'));
        else if (previous) notify(t('adminkey.notRecognised'));
      }
      return;
    }
    if (seen.generation === declinedGeneration) return;
    await askAboutKey(seen, !previous);
  }

  async function askAboutKey(seen, atLaunch) {
    if (askingAboutKey) return;
    askingAboutKey = true;
    try {
      const yes = await dialog.ask({
        title: t(atLaunch ? 'adminkey.launchTitle' : 'adminkey.switchTitle'),
        body: t(atLaunch ? 'adminkey.launchLead' : 'adminkey.switchLead',
                { label: seen.label || t('adminkey.unlabelled') }),
        confirm: t(atLaunch ? 'adminkey.startAdmin' : 'adminkey.switchNow'),
        cancel: t(atLaunch ? 'adminkey.continueNormal' : 'adminkey.notNow'),
      });
      if (yes) await enterAdmin();
      else declinedGeneration = seen.generation;
    } finally {
      askingAboutKey = false;
    }
  }

  // One look at the slot before the first paint: a key already in the
  // machine should be offered at launch, not two seconds later.
  async function checkAtLaunch() {
    try {
      const seen = await api.adminKey();
      patch({ adminKey: seen });
      // "denied" as well as recognised: a key the panel is not allowed to
      // read looks exactly like an empty slot, and this is the moment to
      // say so.
      if (seen.recognised || seen.reason === 'denied') {
        await onKeyChanged(seen, null);
      }
    } catch { /* the loop retries */ }
  }

  return { start: loop, stop, enterAdmin, leaveAdmin, checkAtLaunch };
}
