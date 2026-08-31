// The service-key watcher's frontend half: the once-a-second look at the
// slot, the question a recognised key raises, and the sentences said when
// admin mode ends on its own.
//
// A real import, like remote_pair_test.js: this used to live inside app.js,
// which starts the whole application on import, so none of it was testable
// except by reading the file as text. components/admin_key.js is a factory,
// and these tests hand it a stand-in api/dialog and hold the beat in their
// own hands.
import assert from "node:assert/strict";

import {
  ADMIN_KEY_INTERVAL,
  createAdminKey,
} from "../../static/js/components/admin_key.js";

function harness({ key, ask = () => Promise.resolve(false) } = {}) {
  const log = {
    looked: 0, asked: [], toasts: [], modes: [], editions: 0,
    remotePolls: 0, waits: [],
  };
  // The store's two facts this component reads. `patch` and `applyEdition`
  // write them back the way app.js would, so the next round sees what the
  // previous one did.
  const state = { adminKey: null, mode: "field" };
  const component = createAdminKey({
    api: {
      adminKey: () => {
        log.looked += 1;
        return Promise.resolve(typeof key === "function" ? key() : key);
      },
      adminMode: (enter) => {
        log.modes.push(enter);
        return Promise.resolve({ mode: enter ? "admin" : "field" });
      },
      edition: () => {
        log.editions += 1;
        return Promise.resolve({ mode: "field" });
      },
    },
    state,
    patch: (change) => Object.assign(state, change),
    dialog: {
      ask: (question) => { log.asked.push(question); return ask(question); },
    },
    t: (k) => k,
    notify: (text) => log.toasts.push(text),
    showSuccess: (text) => log.toasts.push(text),
    showError: (text) => log.toasts.push(text),
    applyEdition: (body) => { state.mode = body.mode; return body; },
    pollRemote: () => { log.remotePolls += 1; return Promise.resolve(); },
    wait: (fn, ms) => { log.waits.push({ fn, ms }); return log.waits.length; },
    clearWait: () => {},
  });
  return {
    component, log, state,
    // Run the round the loop has queued, to its end.
    round: async () => { await log.waits[log.waits.length - 1].fn(); },
  };
}

Deno.test("the slot is asked about once a second, remote riding the beat", async () => {
  // One beat, two questions: both are "has the way in gone away", and two
  // timers would mean two answers arriving out of step about one mode.
  const ui = harness({ key: { generation: 0, recognised: false } });
  ui.component.start();
  assert.equal(ui.log.waits[0].ms, ADMIN_KEY_INTERVAL);
  assert.equal(ADMIN_KEY_INTERVAL, 1000,
    "a USB stick appearing is a physical act; a second is what 'noticed' means");
  await ui.round();
  assert.equal(ui.log.looked, 1);
  assert.equal(ui.log.remotePolls, 1, "the remote poll rides the same round");
  assert.equal(ui.log.waits.length, 2, "the loop re-arms itself");
  assert.equal(ui.log.waits[1].ms, ADMIN_KEY_INTERVAL);
});

Deno.test("a declined key is not asked about again until it moves", async () => {
  // The observation counter is the memory: saying "not now" holds until the
  // key is taken out and put in again (a new generation), not for two
  // seconds.
  let generation = 1;
  const ui = harness({
    key: () => ({ generation, recognised: true, present: true, label: "K" }),
  });
  ui.component.start();
  await ui.round();
  assert.equal(ui.log.asked.length, 1, "the first sighting asks");
  await ui.round();
  assert.equal(ui.log.asked.length, 1, "the same generation never re-asks");
  generation = 2;
  await ui.round();
  assert.equal(ui.log.asked.length, 2, "reinserting the key asks afresh");
});

Deno.test("saying yes enters admin mode through the server", async () => {
  const ui = harness({
    key: { generation: 5, recognised: true, present: true },
    ask: () => Promise.resolve(true),
  });
  ui.component.start();
  await ui.round();
  assert.deepEqual(ui.log.modes, [true], "the server is asked to open it");
  assert.equal(ui.state.mode, "admin", "and the edition body is applied");
  assert.ok(ui.log.toasts.includes("adminkey.entered"));
});

Deno.test("the question names the moment: launch or mid-session", async () => {
  // `previous === null` is launch. The two dialogs carry different sentences
  // because "start in admin mode?" and "switch now?" are different offers.
  const ui = harness({
    key: { generation: 3, recognised: true, present: true },
  });
  await ui.component.checkAtLaunch();
  assert.equal(ui.log.asked[0].title, "adminkey.launchTitle");
  ui.component.start();
  ui.state.adminKey = { generation: 3, recognised: true };
  const later = harness({
    key: { generation: 4, recognised: true, present: true },
  });
  later.state.adminKey = { generation: 3, recognised: false };
  later.component.start();
  await later.round();
  assert.equal(later.log.asked[0].title, "adminkey.switchTitle");
});

Deno.test("which way in went away decides which sentence is said", async () => {
  // "The key was removed" to somebody who deleted the secret file sends
  // them looking at a USB port for no reason.
  const pulled = harness({ key: { generation: 9, recognised: false } });
  pulled.state.mode = "admin";
  pulled.state.adminKey = { generation: 8, recognised: true };
  pulled.component.start();
  await pulled.round();
  assert.equal(pulled.log.editions, 1, "the edition is re-read, not guessed");
  assert.ok(pulled.log.toasts.includes("adminkey.removed"));

  const closed = harness({ key: { generation: 9, recognised: false } });
  closed.state.mode = "admin";
  closed.state.adminKey = {
    generation: 8, recognised: false, withoutKey: true,
  };
  closed.component.start();
  await closed.round();
  assert.ok(closed.log.toasts.includes("adminkey.closed"));
});

Deno.test("a key nobody may read is said even at launch", async () => {
  // "denied" is not a bad key: the OS gates removable volumes. It looks
  // exactly like an empty slot, there is something to go and do about it,
  // and it will not fix itself on the next poll.
  const ui = harness({
    key: { generation: 2, present: true, recognised: false, reason: "denied" },
  });
  await ui.component.checkAtLaunch();
  assert.ok(ui.log.toasts.includes("adminkey.denied"));
  assert.equal(ui.log.asked.length, 0, "nothing is offered — only said");
});
