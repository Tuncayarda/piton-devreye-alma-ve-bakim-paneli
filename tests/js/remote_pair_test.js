// The two ways into a remote admin session, and the dialog that offers both.
//
// There used to be a third — eight characters read down a telephone into two
// boxes of four, with a button swapping them for the square — and most of
// this file was about pasting a code into whichever box happened to have the
// cursor. That way in is gone (see components/remote_session.js). What is
// asserted now is what replaced it: two columns, each named by a heading
// that follows the face inside it, the square's own arithmetic, and — new
// with the real import — the polling beat and the password hygiene that the
// old text-slicing test could only stub out.
//
// A REAL IMPORT AT LAST. This file used to read app.js as TEXT and rebuild
// a module from a slice of it, because importing app.js starts the whole
// application. The dialog now lives in components/remote_session.js as a
// factory, so these tests hand it stand-in `el`/`fill`/`dialog`/`api`
// helpers and drive the exported behaviour directly.
import assert from "node:assert/strict";

import {
  createRemoteSession,
  PAIR_QUIET,
  PAIR_SIDE,
  squareBox,
} from "../../static/js/components/remote_session.js";

// ── the stand-in DOM ────────────────────────────────────────────────────
// Plain objects shaped like the two things the dialog does with a node:
// read/write its props and swap its children. `focus()` records itself so
// the caret assertions can ask where the cursor went.
let FOCUSED = null;

const field = (props) => {
  const self = {
    tagName: "INPUT", props, children: [], value: props.value || "",
    focus() { FOCUSED = self; },
  };
  return self;
};

const el = (tag, props = {}, children = []) => (
  tag === "input" ? field(props) : {
    tagName: String(tag).toUpperCase(), props, children,
    textContent: props.text,
    get disabled() { return !!props.disabled; },
    set disabled(v) { props.disabled = v; },
    focus() { FOCUSED = this; },
    click() { props.onclick && props.onclick(); },
  }
);

const fill = (node, children) => {
  node.children = children.filter(Boolean);
  return node;
};

// The dialog is two columns — an account on one side, the square on the
// other — so nothing here counts to a node. Everything is looked up by the
// class it is drawn with, which is the name the stylesheet uses too: a line
// added above a column, or another way in beside it, must not silently point
// these tests at the wrong box.
//
// BY TOKEN, not by the whole attribute: a node drawn with
// "remote-way remote-pair" carries the name being asked for, and an exact
// match would quietly answer null for every element with several classes.
const findBy = (node, want) => {
  if (!node || typeof node !== "object") return null;
  if (node.props
      && String(node.props.class || "").split(/\s+/).includes(want)) {
    return node;
  }
  for (const child of node.children || []) {
    const found = findBy(child, want);
    if (found) return found;
  }
  return null;
};

const all = (node, want, into = []) => {
  if (!node || typeof node !== "object") return into;
  if (node.props
      && String(node.props.class || "").split(/\s+/).includes(want)) {
    into.push(node);
  }
  for (const child of node.children || []) all(child, want, into);
  return into;
};

const head = (side) => {
  const found = findBy(side, "remote-way-head");
  return found && found.props.text;
};

// Let queued microtasks (the awaits inside the pairing flow) run out.
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// What the service answers a pairing request with, unless a test says
// otherwise. The image is a data: URI on purpose — see the img test below.
const PAIR = {
  modules: 41, quiet: 4, pollAfter: 3, pairId: "AB12",
  image: "data:image/svg+xml;base64,PHN2Zy8+",
};

// ── the harness ─────────────────────────────────────────────────────────
// One factory instance per test, with the beat held in `waits` instead of
// real timers: a queued poll is a {fn, ms} entry the test fires by hand.
function harness(apiOverrides = {}, stateOverrides = {}) {
  FOCUSED = null;
  let SHOWN = null;
  const log = {
    paired: 0, polled: 0, cancelled: 0,
    patches: [], editions: [], toasts: 0, waits: [],
  };
  const dialog = {
    show(options) { SHOWN = options; },
    // The real dialog calls onClose however it was closed — Escape, the
    // backdrop, the Cancel button, or the flow itself (components/dialog.js).
    close() {
      const open = SHOWN;
      SHOWN = null;
      if (open && open.onClose) open.onClose();
    },
  };
  const api = {
    remotePair: () => { log.paired += 1; return Promise.resolve({ pair: PAIR }); },
    remotePairPoll: () => {
      log.polled += 1;
      return Promise.resolve({ pair: { state: "pending" } });
    },
    remotePairCancel: () => { log.cancelled += 1; return Promise.resolve({}); },
    remoteSignin: () => Promise.resolve({ remote: { generation: 1 } }),
    remoteSignup: () => Promise.resolve({}),
    remote: () => Promise.resolve({}),
    edition: () => Promise.resolve({ mode: "field" }),
    ...apiOverrides,
  };
  const session = createRemoteSession({
    el, fill, dialog, api,
    t: (key) => key,
    state: { edition: null, remote: null, ...stateOverrides },
    patch: (change) => log.patches.push(change),
    applyEdition: (body) => { log.editions.push(body); return body; },
    showSuccess: () => { log.toasts += 1; },
    notify: () => { log.toasts += 1; },
    loading: (text) => el("div", { class: "loading", text }),
    loadFailed: (text) => el("div", { class: "load-failed", text }),
    wait: (fn, ms) => { log.waits.push({ fn, ms }); return log.waits.length; },
    clearWait: () => {},
  });

  const account = () => findBy(SHOWN.content, "remote-account");
  return {
    session, log, dialog,
    open: async () => { session.askForRemoteSession(); await settle(); },
    shown: () => SHOWN,
    account,
    pair: () => findBy(SHOWN.content, "remote-pair"),
    heads: () => [head(account()), head(findBy(SHOWN.content, "remote-pair"))],
    fields: () => all(account(), "field"),
    labels: () => all(account(), "label").map((node) => node.props.text),
    submit: () => findBy(account(), "remote-submit"),
    link: () => findBy(account(), "btn-link"),
    form: () => findBy(account(), "remote-account-pane"),
    square: () => findBy(SHOWN.content, "remote-square"),
    focused: () => FOCUSED,
    close: () => dialog.close(),
    gone: (name) => findBy(SHOWN.content, name),
    // The next queued poll round, fired by hand.
    beat: () => log.waits[log.waits.length - 1],
  };
}

const submitForm = async (ui) => {
  await ui.form().props.onsubmit({ preventDefault() {} });
};

// ── two ways in, side by side ───────────────────────────────────────────
Deno.test("both ways in open together, and both are named", async () => {
  // The columns are drawn alike on purpose, so the heading is the only thing
  // telling them apart: a column that lost its heading would look exactly
  // like the other one and say nothing about what it wants.
  const ui = harness();
  await ui.open();
  assert.ok(ui.account(), "the account column is drawn");
  assert.ok(ui.pair(), "the square's column is drawn");
  assert.deepEqual(ui.heads(), ["remote.wayAccount", "remote.wayQr"]);
});

Deno.test("signing in asks for two things and offers one button", async () => {
  const ui = harness();
  await ui.open();
  assert.deepEqual(ui.labels(), ["remote.email", "remote.password"]);
  assert.equal(ui.submit().props.text, "remote.signIn");
  assert.equal(ui.link().props.text, "remote.signUp");
  assert.equal(ui.focused(), ui.fields()[0], "the caret starts in the first");
});

Deno.test("the heading follows the face inside the column", async () => {
  // The whole column is refilled on a swap, heading and all. A column headed
  // "sign in with an account" over a four-field "create an account" form is
  // a heading that has stopped describing what is under it.
  const ui = harness();
  await ui.open();
  ui.link().click();
  assert.deepEqual(ui.heads(), ["remote.signUp", "remote.wayQr"]);
  assert.deepEqual(ui.labels(), [
    "remote.name", "remote.email", "remote.password", "remote.passwordAgain",
  ]);
  assert.equal(ui.submit().props.text, "remote.signUp");

  ui.link().click();                                  // and back again
  assert.deepEqual(ui.heads(), ["remote.wayAccount", "remote.wayQr"]);
  assert.deepEqual(ui.labels(), ["remote.email", "remote.password"]);
});

Deno.test("the address typed in comes along to the other face", async () => {
  // Somebody who filled the address in, was told there is no such account
  // and pressed "create one" must not be asked for it a second time.
  const ui = harness();
  await ui.open();
  ui.fields()[0].value = "engineer@example.test";
  ui.link().click();
  assert.equal(ui.fields()[1].props.value, "engineer@example.test");
});

Deno.test("no code box was left behind", async () => {
  // The way in that asked the operator to transcribe eight characters is
  // gone, and so is the button that swapped it for the square. If either
  // comes back it comes back on purpose, with its own tests.
  const ui = harness();
  await ui.open();
  for (const name of ["remote-code-row", "remote-code-pane", "remote-swap"]) {
    assert.equal(ui.gone(name), null, name);
  }
});

// ── the password never waits around ─────────────────────────────────────
Deno.test("the password box is emptied when the sign-in succeeds", async () => {
  const ui = harness();
  await ui.open();
  const [email, password] = ui.fields();
  email.value = "engineer@example.test";
  password.value = "hunter2";
  await submitForm(ui);
  assert.equal(password.value, "", "the box is emptied on success");
  assert.equal(ui.shown(), null, "the dialog closes");
  assert.equal(ui.log.editions.length, 1, "the edition body is applied");
  assert.deepEqual(ui.log.patches.at(-1), { remote: { generation: 1 } });
});

Deno.test("the password box is emptied when the sign-in is refused", async () => {
  // WHICHEVER WAY THE REPLY LANDED: a wrong password left on screen is a
  // wrong password somebody tries to correct rather than retype.
  const ui = harness({
    remoteSignin: () => Promise.reject(new Error("remote.noPermission")),
  });
  await ui.open();
  const [, password] = ui.fields();
  password.value = "hunter2";
  await submitForm(ui);
  assert.equal(password.value, "", "the box is emptied on refusal too");
  const warning = findBy(ui.account(), "warning");
  assert.equal(warning.hidden, false, "the refusal is said");
  assert.equal(warning.textContent, "remote.noPermission");
  assert.equal(ui.focused(), password, "the caret returns to the password");
  assert.ok(ui.shown(), "a refusal keeps the dialog open — that is the point");
  assert.ok(ui.square(), "…with the square still live beside it");
});

Deno.test("a sign-up mismatch is refused locally, both boxes emptied", async () => {
  let asked = 0;
  const ui = harness({
    remoteSignup: () => { asked += 1; return Promise.resolve({}); },
  });
  await ui.open();
  ui.link().click();
  const [, , password, again] = ui.fields();
  password.value = "hunter2";
  again.value = "hunter3";
  await submitForm(ui);
  assert.equal(asked, 0, "a mismatch needs no round trip to notice");
  assert.equal(password.value, "");
  assert.equal(again.value, "");
  assert.equal(findBy(ui.account(), "warning").textContent,
    "remote.passwordMismatch");
});

// ── the square and its beat ─────────────────────────────────────────────
Deno.test("the square is an img with the service's data: URI", async () => {
  // Not decoration: SVG inside an <img> is static by specification — no
  // script runs, nothing is fetched. Putting the service's markup into the
  // page AS markup would hand a network-supplied drawing the run of the
  // panel's own DOM, the one thing el() exists to make impossible.
  const ui = harness();
  await ui.open();
  const img = findBy(ui.square(), "remote-qr").children[0];
  assert.equal(img.tagName, "IMG", "drawn as an image, never as markup");
  assert.equal(img.props.src, PAIR.image);
  assert.match(img.props.src, /^data:image\/svg\+xml/);
  const box = squareBox(PAIR.modules, PAIR.quiet);
  assert.equal(img.props.width, box.side);
  assert.equal(img.props.height, box.side);
  const badge = findBy(ui.pair(), "badge");
  assert.equal(badge.props.text, "AB12", "the request number is on the row");
});

Deno.test("the poll follows the service's own cadence", async () => {
  // `pollAfter` is the service saying how often it wants to be asked; the
  // panel obeys it round after round rather than picking a beat of its own.
  const ui = harness();
  await ui.open();
  assert.equal(ui.log.waits.length, 1, "one round is queued");
  assert.equal(ui.beat().ms, 3000, "…after the seconds the service named");

  await ui.beat().fn();                       // pending → ask again
  assert.equal(ui.log.polled, 1);
  assert.equal(ui.log.waits.length, 2);
  assert.equal(ui.beat().ms, 3000, "the cadence holds between rounds");
});

Deno.test("a service without a cadence is asked every two seconds", async () => {
  const ui = harness({
    remotePair: () =>
      Promise.resolve({ pair: { ...PAIR, pollAfter: undefined } }),
  });
  await ui.open();
  assert.equal(ui.beat().ms, 2000);
});

Deno.test("a 429 rides the beat out; a real refusal stops it", async () => {
  const throttle = Object.assign(new Error("slow down"), { status: 429 });
  const refusal = Object.assign(new Error("gone"), { status: 404 });
  let answer = throttle;
  const ui = harness({
    remotePairPoll: () => Promise.reject(answer),
  });
  await ui.open();

  await ui.beat().fn();                       // throttled: the square is
  assert.equal(ui.log.waits.length, 2);       // still good, ask again
  assert.equal(ui.gone("remote-pair-failed"), null);

  answer = refusal;
  await ui.beat().fn();                       // decided: say so and stop
  assert.equal(ui.log.waits.length, 2, "no further round is queued");
  assert.ok(findBy(ui.square(), "remote-pair-failed"));
  ui.close();
  assert.equal(ui.log.cancelled, 0,
    "a pairing the service already ended is not cancelled again");
});

Deno.test("an approved poll enters the mode and never cancels", async () => {
  const granted = {
    mode: "admin", remote: { active: true, generation: 4 }, views: ["admin"],
  };
  const ui = harness({
    remotePairPoll: () => Promise.resolve(granted),
  });
  await ui.open();
  await ui.beat().fn();
  assert.equal(ui.shown(), null, "the dialog closes itself");
  assert.deepEqual(ui.log.editions, [granted], "the whole edition lands");
  assert.deepEqual(ui.log.patches.at(-1), { remote: granted.remote });
  assert.equal(ui.log.cancelled, 0, "used, not abandoned — never cancelled");
});

Deno.test("a refusal is said; an expiry just offers the button", async () => {
  const ui = harness({
    remotePairPoll: () =>
      Promise.resolve({ pair: { state: "denied" }, stateText: "not you" }),
  });
  await ui.open();
  await ui.beat().fn();
  const failed = findBy(ui.square(), "remote-pair-failed");
  assert.equal(findBy(failed, "load-failed").props.text, "not you",
    "somebody decided that, and it must not be swallowed");

  const expired = harness({
    remotePairPoll: () => Promise.resolve({ pair: { state: "expired" } }),
  });
  await expired.open();
  await expired.beat().fn();
  const quiet = findBy(expired.square(), "remote-pair-failed");
  assert.equal(findBy(quiet, "load-failed"), null,
    "nothing to say that the retry button does not say better");
  quiet.children.at(-1).click();              // and the button asks again
  await settle();
  assert.equal(expired.log.paired, 2);
});

Deno.test("the square is asked for on opening and given up on closing", async () => {
  // Both halves of the dialog are live at once: the operator either points a
  // phone at the square or signs in as themselves, and whichever they do the
  // other must not be left running. Closing is the only place that knows the
  // square has stopped being looked at.
  const ui = harness();
  await ui.open();
  assert.equal(ui.log.paired, 1, "the pairing is asked for at once");
  assert.ok(findBy(ui.pair(), "remote-qr"), "and drawn in its own column");
  ui.close();
  assert.equal(ui.log.cancelled, 1, "closing gives the pairing back");
});

// ── the session poll that rides the key beat ────────────────────────────
Deno.test("pollRemote asks nothing where no grant could be checked", async () => {
  let asked = 0;
  const ui = harness(
    { remote: () => { asked += 1; return Promise.resolve({}); } },
    { edition: { remoteAvailable: false } },
  );
  await ui.session.pollRemote();
  assert.equal(asked, 0, "a build without the public key has no session");
});

Deno.test("a session that ended is re-read, not guessed at", async () => {
  const edition = { mode: "field", views: [] };
  const ui = harness(
    {
      remote: () =>
        Promise.resolve({ active: false, generation: 8, reasonText: "over" }),
      edition: () => Promise.resolve(edition),
    },
    {
      edition: { remoteAvailable: true },
      remote: { active: true, generation: 7 },
    },
  );
  await ui.session.pollRemote();
  assert.deepEqual(ui.log.editions, [edition],
    "what is on screen is read again from the server");
  assert.equal(ui.log.toasts, 1, "and the operator is told why");
});

// ── how big the square is drawn ─────────────────────────────────────────
Deno.test("the square is sized to whole pixels per module", () => {
  // A module that is 7.3 pixels wide comes out alternating seven and eight,
  // because the drawing asks for crisp edges rather than a blur. Every
  // square the same size is what a decoder starts from, so the scale is
  // rounded DOWN to a whole number and the picture gives up the remainder.
  //
  // WHAT MUST FIT THE PLATE IS WHAT IS SEEN, not the whole picture. The
  // scale used to be worked out from every module the service drew, margin
  // included, and then some of that margin was cropped away — so the code
  // was sized against white nobody ever looked at and came out a pixel a
  // module smaller than the plate could carry. The picture is now larger
  // than the plate on purpose: the part hanging outside it is the margin
  // being cropped.
  for (const modules of [21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 65, 177]) {
    const { side, shown } = squareBox(modules, 4);
    assert.equal(side % modules, 0, `${modules} modules -> ${side}px`);
    assert.ok(shown <= PAIR_SIDE, `${modules} modules must not grow`);
    assert.ok(side >= modules, `${modules} modules must stay visible`);
  }
});

Deno.test("the plate is filled by the code, not by its margin", () => {
  // The complaint this arithmetic answers: a small drawing floating in the
  // middle of a white card. The code used to be scaled against every module
  // the service drew, margin included, and then part of that margin was
  // cropped — so it was sized against white nobody ever saw.
  //
  // What is asserted is that the scale is the LARGEST whole number of pixels
  // per module that still leaves the quiet zone inside the plate: one pixel
  // more and the code plus its clear border would not fit. Everything else —
  // how little white is left, how big the code comes out — follows from it.
  for (const modules of [29, 37, 41, 49]) {
    for (const quiet of [0, 2, 4, 8]) {
      const { side, shown } = squareBox(modules, quiet);
      const scale = side / modules;
      const kept = Math.min(quiet, PAIR_QUIET);
      // The code, the margin the picture kept, and the margin the plate has
      // to supply because the picture did not carry it.
      const box = shown / scale + (PAIR_QUIET - kept) * 2;
      assert.ok(box * scale <= PAIR_SIDE,
        `${modules}/${quiet}: ${box * scale}px does not fit ${PAIR_SIDE}`);
      assert.ok(scale === 1 || box * (scale + 1) > PAIR_SIDE,
        `${modules}/${quiet}: ${scale + 1}px a module would still have fitted`);
    }
  }
});

Deno.test("the crop takes margin and never takes code", () => {
  // What is cropped is white the service measured and reported. Cropping
  // past it would eat the code, and no arithmetic here may arrive there.
  for (const modules of [29, 37, 41, 49]) {
    for (const quiet of [0, 1, 2, 3, 4, 8]) {
      const { side, shown, offset } = squareBox(modules, quiet);
      const scale = side / modules;
      const cropped = (side - shown) / 2;
      assert.equal(cropped, -offset, "the picture moves by what is hidden");
      assert.ok(cropped >= 0, "the window never grows past the picture");
      assert.ok(cropped <= quiet * scale,
        `${quiet} modules of margin, ${cropped / scale} cropped`);
      const left = quiet - cropped / scale;
      assert.ok(left >= Math.min(quiet, PAIR_QUIET),
        `${quiet} modules of margin left ${left}`);
    }
  }
});

Deno.test("a picture that arrived without its measurements still draws", () => {
  for (const nothing of [undefined, null, 0, -4, "wide", NaN]) {
    const { side, shown, offset } = squareBox(nothing, 4);
    assert.equal(side, PAIR_SIDE);
    assert.equal(shown, PAIR_SIDE);
    assert.equal(offset, 0);
  }
});
