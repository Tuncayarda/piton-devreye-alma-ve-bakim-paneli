// The remote service session — the other way into admin mode, on a machine
// with no service key in it: the panel opens a session on the grant service
// and then keeps asking that service to sign for it, and the mode lasts as
// long as the answers do (see panel/remotekey/watcher.py).
//
// TWO DOORS, ONE ROOM, AND SO ONE DIALOG. A square somebody approves on a
// telephone, and an engineer standing at the panel signing in as themselves.
// They end in the same place by the same evidence — a grant the SERVER
// checked a signature on — so they are laid out side by side rather than
// hidden behind a choice nobody can make before they know which one they
// have. The account is on the left because it needs nobody else awake; the
// square is on the right because it is what to reach for when the person who
// can say yes is somewhere else.
//
// EACH COLUMN IS NAMED, and that heading is the only thing telling the two
// apart: same ground, same rhythm, one line of accent caps over each. Two
// ways in that look alike and are labelled are read as alternatives; two
// that are drawn differently are read as a main way and a fallback, which is
// not true of either of these.
//
// THERE WAS A THIRD: eight characters read down a telephone into two boxes
// of four, with a button swapping them for the square. It is gone. It needed
// the same person awake at the other end that the square needs, so it bought
// nothing the square does not give, and it asked the operator to transcribe
// eight characters while standing next to a train. The service still mints
// those codes and `/api/admin/remote/connect` still takes one; nothing in
// this window asks for one any more.
//
// LIFTED OUT OF app.js AS A FACTORY, and the factory is the point: app.js
// starts the whole application the moment it is imported, so the only test
// this dialog had was one that read app.js as TEXT and rebuilt a module from
// a slice of it. `createRemoteSession()` takes its dependencies — the DOM
// helpers, the dialog, the API client, the store, and app.js's own
// `applyEdition` — with the real ones as defaults, so app.js passes only
// what it alone owns and the tests pass stand-ins and drive the dialog by
// ordinary import (tests/js/remote_pair_test.js).

import { el as domEl, fill as domFill } from '../core/dom.js';
import { api as liveApi } from '../core/api.js';
import { state as liveState, patch as livePatch } from '../core/store.js';
import * as liveDialog from './dialog.js';
import { notify as liveNotify, showSuccess as liveShowSuccess } from './toast.js';
import { loadFailed as liveLoadFailed, loading as liveLoading }
  from './placeholder.js';
import { t as liveT } from '../core/i18n.js';

// How big the square wants to be, before it is rounded to whole modules.
//
// MEASURED IN MODULES, NOT IN PIXELS. A pairing address is 54 characters,
// which is a version 4 code: 33 modules of code, 41 across with its margin.
// At 176px — where this started — each module was four pixels, which is
// below what a phone can resolve at the distance it will also focus at.
// Eight is comfortable and does not take over the dialog.
//
// It is not a workaround for anything. The square was unreadable at every
// size for a fortnight because the service was drawing the format
// information backwards, and enlarging it did nothing at all; the fix was
// in the service (dabp-remote-key/src/qr.js). This is just a legible size.
export const PAIR_SIDE = 224;

// HOW MUCH WHITE IS LEFT AROUND IT, IN MODULES.
//
// The service draws the four the standard asks for, which is the right thing
// for a code that might be printed and photographed off a wall. On a panel
// it is a fifth of the picture: with the margin also counted into the scale,
// the code came out at seven pixels a module inside a plate that was a third
// white — a small drawing floating on a card, which is what made the square
// look pasted on rather than presented.
//
// Two, and they are the ONLY white: the scale is worked out from the code
// plus these two and nothing else, so the plate is filled by what somebody
// is meant to point a telephone at. Not zero, and this is the one place the
// number cannot be chosen by eye — a code with nothing clear around it is
// read against whatever is behind it, and behind this one is a dark panel.
// Two modules is what a screen decoder wants at arm's length.
export const PAIR_QUIET = 2;

// Everything the window needs to draw one: the picture's real size, the
// size of the hole it is seen through, and how far to pull it up and left
// behind that hole.
//
// A WHOLE NUMBER OF PIXELS PER MODULE. The drawing asks for crisp edges, so
// a fractional scale — 300 across 41 modules is 7.3 — is not blurred; it is
// SNAPPED, and the modules come out alternating seven and eight pixels wide.
// Rounding down to seven costs thirteen pixels of size and makes every
// square the same size as every other, which is the assumption a decoder
// starts from.
export function squareBox(modules, quiet) {
  const across = Number(modules);
  const margin = Number(quiet);
  if (!(across > 0)) return { side: PAIR_SIDE, shown: PAIR_SIDE, offset: 0 };
  // The margin the picture keeps, and the margin the plate has to supply
  // because the picture did not carry it. Between them the code always sits
  // inside `PAIR_QUIET` clear modules, however the service drew it.
  const kept = Math.min(margin, PAIR_QUIET);
  const crop = margin - kept;
  const shownModules = across - crop * 2;
  // THE SCALE IS WORKED OUT FROM WHAT IS SEEN, not from the whole picture.
  // Dividing by `across` sized the code against margin that was then cropped
  // away, so it lost a pixel a module to white nobody ever saw.
  const boxModules = shownModules + (PAIR_QUIET - kept) * 2;
  const scale = Math.max(1, Math.floor(PAIR_SIDE / boxModules));
  return {
    side: across * scale,
    shown: shownModules * scale,
    offset: -crop * scale,
  };
}

// Statuses worth asking again after. Everything else is a decision — the
// pairing was refused, expired or swept — and the square says so and stops
// rather than beating against it.
const PAIR_RETRY = new Set([0, 429, 503]);

export function createRemoteSession(overrides = {}) {
  const {
    el, fill, t, api, state, patch, dialog,
    notify, showSuccess, loadFailed, loading,
    // What app.js alone owns: applying a whole edition body to the store
    // and redrawing on a mode change. Passed in rather than imported so
    // this module never has to know how the shell redraws itself.
    applyEdition,
    // The timers, injectable so the tests can hold the beat in their hand
    // instead of sleeping through it.
    wait = (fn, ms) => setTimeout(fn, ms),
    clearWait = (id) => clearTimeout(id),
  } = {
    el: domEl, fill: domFill, t: liveT, api: liveApi, state: liveState,
    patch: livePatch, dialog: liveDialog, notify: liveNotify,
    showSuccess: liveShowSuccess, loadFailed: liveLoadFailed,
    loading: liveLoading,
    ...overrides,
  };

  function askForRemoteSession() {
    // Filled in by `startPairing` below, and refilled every time the square
    // moves on: asked for, waiting, refused, gone.
    const square = el('div', { class: 'remote-square' });

    dialog.show({
      title: t('remote.title'),
      // The account column, a rule, and the square's column. The square is
      // what fixes the right-hand number; the left takes what is left, which
      // is comfortably more than two fields and a button need.
      width: '720px',
      // The width the RIGHT-HAND column is drawn to, declared before the
      // service is even asked. It is here rather than in the stylesheet
      // because the window is what needs the number: the square's scale is
      // worked out from it, in whole modules (see squareBox).
      content: el('div', {
        class: 'remote-ways', style: `--remote-width:${PAIR_SIDE}px`,
      }, [
        accountSide(),
        el('div', { class: 'remote-way remote-pair' }, [
          wayHead(t('remote.wayQr')),
          square,
        ]),
      ]),
      actions: [
        el('button', {
          type: 'button', class: 'btn', text: t('locked.cancel'),
          onclick: () => dialog.close(),
        }),
      ],
      // Escape, the backdrop and the Cancel button all arrive here, which is
      // the only place that knows the square is no longer being looked at.
      onClose: stopPairing,
    });
    startPairing(square);
  }

  // ───────────────────────────────── signing in as yourself ─────────────
  // The left-hand column, and the only way in that needs nobody else awake:
  // the engineer standing at the machine gives their own e-mail and password,
  // and the service mints a session bound to this installation. The SERVER
  // enters admin mode on the round that succeeds, on a signature it checked —
  // exactly as it does for an approved square
  // (panel/api/routes/remote_routes.py).
  //
  // THREE FACES, ONE COLUMN, ONE AT A TIME: signing in, asking for an
  // account, and the sentence that follows a new one. They replace each
  // other in place rather than opening dialogs of their own — the square on
  // the right is live throughout, and a second window on top of it would
  // cover the very thing the operator may be about to point a phone at.
  //
  // THE HEADING BELONGS TO THE FACE, not to the column, which is why the
  // whole column is what gets refilled. A column headed "Sign in with an
  // account" with a four-field "create an account" form under it is a
  // heading that has stopped describing what is beneath it.
  //
  // THE PASSWORD LIVES IN ONE FIELD AND ONE REQUEST BODY. It is not put in
  // `state`, not remembered for a retry, and the field is emptied the moment
  // the reply lands — whichever way it landed, because a wrong password left
  // on screen is a wrong password somebody tries to correct rather than
  // retype.
  //
  // A REFUSAL KEEPS THE DIALOG OPEN, and that is the point of the layout: an
  // account without permission to sign in from the panel is told so beside a
  // square that is already drawn and already waiting. The fallback is not a
  // second dialog; it is the other half of this one.
  function accountSide() {
    const pane = el('div', { class: 'remote-way remote-account' });
    showSignIn(pane, '');
    return pane;
  }

  const wayHead = (caption) => el('h4', {
    class: 'remote-way-head', text: caption,
  });

  const fieldLabel = (caption, field) => el('label', { class: 'field-label' }, [
    el('span', { class: 'label', text: caption }),
    field,
  ]);

  // The quiet line under the button: a sentence nobody has to read, and the
  // way to the column's other face. It is a link rather than a second button
  // because the column already has the one thing to press, and two buttons of
  // equal weight under two fields is a question where there was an answer.
  const aside = (sentence, link) => el('p', { class: 'remote-aside' }, [
    el('span', { text: sentence }),
    link,
  ]);

  function showSignIn(pane, address) {
    const email = el('input', {
      class: 'field', type: 'email', autocomplete: 'off', value: address,
      autocapitalize: 'off', spellcheck: 'false', inputmode: 'email',
    });
    const password = el('input', {
      class: 'field', type: 'password', autocomplete: 'new-password',
    });
    const warning = el('p', { class: 'warning', role: 'alert', hidden: true });
    const submit = el('button', {
      type: 'submit', class: 'btn btn-primary remote-submit',
      text: t('remote.signIn'),
    });

    fill(pane, [wayHead(t('remote.wayAccount')), el('form', {
      class: 'remote-account-pane',
      onsubmit: async (event) => {
        event.preventDefault();
        warning.hidden = true;
        submit.disabled = true;
        submit.textContent = t('remote.signingIn');
        try {
          const answer = await api.remoteSignin(email.value.trim(),
                                                password.value);
          password.value = '';
          // Closing takes the square back at the same time: the dialog's
          // `onClose` is the only thing that knows a pairing was asked for.
          dialog.close();
          patch({ remote: answer.remote });
          applyEdition(answer);
          showSuccess(t('remote.connected'));
        } catch (e) {
          password.value = '';
          warning.textContent = e.message;
          warning.hidden = false;
          password.focus();
        } finally {
          submit.disabled = false;
          submit.textContent = t('remote.signIn');
        }
      },
    }, [
      fieldLabel(t('remote.email'), email),
      fieldLabel(t('remote.password'), password),
      warning,
      submit,
      aside(t('remote.noAccount'), el('button', {
        type: 'button', class: 'btn-link', text: t('remote.signUp'),
        // What is typed already comes along. Somebody who filled the address
        // in, was told there is no such account and pressed this should not
        // be asked for it a second time.
        onclick: () => showSignUp(pane, email.value.trim()),
      })),
    ])]);
    email.focus();
  }

  // Asking for an account, from the panel, by anybody holding it.
  //
  // WHAT THIS MAKES CANNOT DO ANYTHING. The service gives a new account
  // every permission at zero, so the very next sign-in with it is refused
  // until an administrator turns a switch on their own page — which is why
  // the door can be open at all. The screen says so before the account is
  // asked for and again after it exists, because somebody who was not told
  // would spend the afternoon retyping a password that is perfectly correct.
  function showSignUp(pane, address) {
    const name = el('input', {
      class: 'field', type: 'text', autocomplete: 'off', spellcheck: 'false',
    });
    const email = el('input', {
      class: 'field', type: 'email', autocomplete: 'off', value: address,
      autocapitalize: 'off', spellcheck: 'false', inputmode: 'email',
    });
    const password = el('input', {
      class: 'field', type: 'password', autocomplete: 'new-password',
    });
    const again = el('input', {
      class: 'field', type: 'password', autocomplete: 'new-password',
    });
    const warning = el('p', { class: 'warning', role: 'alert', hidden: true });
    const submit = el('button', {
      type: 'submit', class: 'btn btn-primary remote-submit',
      text: t('remote.signUp'),
    });

    const refuse = (message, field) => {
      password.value = '';
      again.value = '';
      warning.textContent = message;
      warning.hidden = false;
      field.focus();
    };

    fill(pane, [wayHead(t('remote.signUp')), el('form', {
      class: 'remote-account-pane',
      onsubmit: async (event) => {
        event.preventDefault();
        warning.hidden = true;
        // The two boxes are compared HERE and nowhere else. There is no
        // recovering a password nobody knows on an account nobody has
        // approved yet, and a mismatch needs no round trip to notice.
        if (password.value !== again.value) {
          refuse(t('remote.passwordMismatch'), password);
          return;
        }
        submit.disabled = true;
        submit.textContent = t('remote.signingUp');
        const wanted = email.value.trim();
        try {
          await api.remoteSignup(wanted, password.value, name.value.trim());
          password.value = '';
          again.value = '';
          showSignedUp(pane, wanted);
        } catch (e) {
          refuse(e.message, password);
        } finally {
          submit.disabled = false;
          submit.textContent = t('remote.signUp');
        }
      },
    }, [
      fieldLabel(t('remote.name'), name),
      fieldLabel(t('remote.email'), email),
      fieldLabel(t('remote.password'), password),
      fieldLabel(t('remote.passwordAgain'), again),
      warning,
      submit,
      aside(t('remote.haveAccount'), el('button', {
        type: 'button', class: 'btn-link', text: t('remote.backToSignIn'),
        onclick: () => showSignIn(pane, email.value.trim()),
      })),
    ])]);
    name.focus();
  }

  // The account exists and is waiting on somebody. Said as an `.info` rather
  // than a `.warning`: nothing went wrong, and the one thing left to do
  // about it is not on this machine.
  function showSignedUp(pane, address) {
    const back = el('button', {
      type: 'button', class: 'btn btn-primary remote-submit',
      text: t('remote.backToSignIn'),
      // The address goes back with it, so the person who has just chosen a
      // password can try it the moment somebody says yes.
      onclick: () => showSignIn(pane, address),
    });
    fill(pane, [wayHead(t('remote.signUp')),
      el('div', { class: 'remote-account-pane' }, [
        el('p', {
          class: 'info', role: 'status', text: t('remote.signUpWaiting'),
        }),
        back,
      ])]);
    back.focus();
  }

  // ───────────────────────────────────────────── the square ─────────────
  // The other half of the same dialog, for the far more common case: nobody
  // has to read anything out. The panel asks the service for a pairing,
  // draws the square that comes back, and asks every couple of seconds
  // whether anybody has approved it. The round that finds an approval is the
  // round that enters admin mode — and the SERVER does that, on a signature
  // it checked (panel/api/routes/remote_routes.py).
  //
  // THE SQUARE IS AN `<img>` WITH AN INLINE-ENCODED SOURCE, and that is not
  // decoration. What the service draws is SVG; SVG inside an `<img>` is
  // static by specification — no script runs, nothing is fetched. Putting
  // the same markup into the page AS markup would hand a drawing that came
  // off the network the run of the panel's own DOM, which is the one thing
  // `el()` exists to make impossible (see core/dom.js).

  // A late answer never touches a screen that has moved on. Every round
  // takes a number, closing the dialog burns it, and an answer that comes
  // back with an old one is dropped — the same rule the refresh loops
  // follow (core/latest.js is that rule for the screens; the round number
  // here also has to retire the chained TIMER, which is why it is not the
  // same helper).
  let pairRound = 0;
  let pairTimer = null;
  // Whether the service is holding a pairing this window asked for. Only
  // this says whether closing the dialog has anything to take back.
  let pairingOpen = false;

  function stopPairing() {
    pairRound += 1;
    if (pairTimer !== null) { clearWait(pairTimer); pairTimer = null; }
    if (!pairingOpen) return;
    pairingOpen = false;
    // Nothing waits for this and nothing is shown if it fails: the dialog
    // has already gone, and a pairing nobody takes back expires on its own.
    api.remotePairCancel().catch(() => {});
  }

  async function startPairing(square) {
    const mine = (pairRound += 1);
    // Nothing arms a timer and then offers "another square", so this should
    // already be clear — but a round left beating against a square that has
    // been replaced is the one failure here nobody would ever see.
    if (pairTimer !== null) { clearWait(pairTimer); pairTimer = null; }
    // The spinner and nothing else. "Preparing the square" is a sentence
    // whose whole content is already on screen as a spinner, in a dialog the
    // operator opened one second ago.
    fill(square, [loading('')]);
    let answer;
    try {
      answer = await api.remotePair();
    } catch (e) {
      if (mine === pairRound) fill(square, [pairFailed(square, e.message)]);
      return;
    }
    // The dialog closed while the service was answering, so there is a
    // pairing out there that nothing will use. It is left to expire rather
    // than cancelled: another square may have been asked for since, and the
    // service keeps one at a time — cancelling now would take back the
    // wrong one.
    if (mine !== pairRound) return;

    pairingOpen = true;
    const pair = answer.pair || {};
    const box = squareBox(pair.modules, pair.quiet);
    // The plate is a fixed square (see components.css .remote-qr) and the
    // code is centred in it: a code is drawn in whole modules, so its own
    // side is whatever the module count makes it, and a plate that took that
    // number would be a different size for a different code. What is left
    // over is white, which is quiet zone, which is the one thing a decoder
    // wants more of. This is the only number that comes from the answer.
    const inset = Math.round((PAIR_SIDE - box.shown) / 2);
    fill(square, [
      el('div', { class: 'remote-qr' }, [
        el('img', {
          src: pair.image, alt: t('remote.pairAlt'),
          width: box.side, height: box.side,
          style: `left:${box.offset + inset}px;top:${box.offset + inset}px`,
        }),
      ]),
      // ONE ROW, NOT TWO SENTENCES. What it is doing on the left, which
      // request it is on the right, both ending where the square ends. The
      // number is there because a square that will not scan is not the end
      // of the road — the same request is waiting on the operator's own
      // page under it — and it is a badge rather than a sentence because
      // nobody reads it until they need it.
      el('div', {
        class: 'remote-status', role: 'status', 'aria-live': 'polite',
      }, [
        el('span', { class: 'remote-status-live' }, [
          el('span', {
            class: 'dot', 'data-state': 'busy', 'aria-hidden': 'true',
          }),
          el('span', { text: t('remote.pairWaiting') }),
        ]),
        el('span', {
          class: 'badge', title: t('remote.pairNumber'),
          text: pair.pairId || '',
        }),
      ]),
    ]);
    waitForPairing(square, pair.pollAfter, mine);
  }

  function waitForPairing(square, after, mine) {
    const seconds = Number(after) > 0 ? Number(after) : 2;
    pairTimer = wait(() => pollPairing(square, seconds, mine),
                     seconds * 1000);
  }

  async function pollPairing(square, seconds, mine) {
    pairTimer = null;
    let answer;
    try {
      answer = await api.remotePairPoll();
    } catch (e) {
      if (mine !== pairRound) return;
      if (!PAIR_RETRY.has(e.status)) {
        pairingOpen = false;
        fill(square, [pairFailed(square, e.message)]);
        return;
      }
      // The network, or a service asking to be left alone for a moment. The
      // square is still good and the deadline is the service's, so this is
      // ridden out exactly as the grant beat rides out silence.
      waitForPairing(square, seconds, mine);
      return;
    }
    if (mine !== pairRound) return;

    // Approved, and the server has already been in and out of the service
    // with it: what came back is the whole edition, the way a sign-in gets
    // it.
    if (answer.mode !== undefined) {
      pairingOpen = false;                // used, not abandoned — never cancel
      dialog.close();
      patch({ remote: answer.remote });
      applyEdition(answer);
      showSuccess(t('remote.connected'));
      return;
    }
    const settled = (answer.pair || {}).state;
    if (settled !== 'pending') {
      pairingOpen = false;
      // Expired, or given up on: there is nothing to say about it that the
      // button underneath does not say better. A REFUSAL IS DIFFERENT —
      // somebody decided that, and swallowing it would leave the operator
      // pressing "new square" until they wore out.
      fill(square, [pairFailed(square,
        settled === 'denied' ? (answer.stateText || '') : '')]);
      return;
    }
    waitForPairing(square, seconds, mine);
  }

  // The square is gone, and here is the one thing to do about it. The
  // sentence above the button is for the cases where it would not otherwise
  // be obvious — a refusal, or a service that could not be reached — and is
  // left out where it would only be reading the button back.
  function pairFailed(square, message) {
    return el('div', { class: 'remote-pair-failed' }, [
      message ? loadFailed(message) : null,
      el('button', {
        type: 'button', class: 'btn', text: t('remote.pairRetry'),
        onclick: () => startPairing(square),
      }),
    ]);
  }

  // Polled on the same beat as the service key (components/admin_key.js),
  // and only where it could do anything: a package built without a public
  // key for the service has no session to ask about.
  async function pollRemote() {
    if (!(state.edition && state.edition.remoteAvailable)) return;
    let seen;
    try { seen = await api.remote(); } catch { return; }
    const previous = state.remote;
    patch({ remote: seen });
    if (!previous || previous.generation === seen.generation) return;
    // The session was holding the door and is not any more — the link was
    // closed, the network went, or the grant simply ran out. The server has
    // already dropped the mode (or is holding it until a write finishes),
    // so what is on screen has to be read again rather than guessed at.
    if (previous.active && !seen.active) {
      try { applyEdition(await api.edition()); } catch { /* next round */ }
      notify(seen.reasonText || t('remote.ended'));
    }
  }

  return { askForRemoteSession, pollRemote };
}
