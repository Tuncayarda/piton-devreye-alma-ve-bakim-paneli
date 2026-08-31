// A password typed on a switch row must not outlive its moment.
//
// The store refuses credential keys outright (core/store.js), and
// `typed()` in views/switch/state.js is the module memory that exists to
// hold the pair for the seconds between typing and sending. These tests pin
// the erasers around it: a FAILED sign-in drops the password exactly as an
// accepted one does (session.js only erases on success), leaving the screen
// or changing the project/edition drops every half-typed pair, and the
// error path in index.js really calls the eraser.
//
// Pure-module tests, like project_switch_test.js: state.js has no DOM in
// it, and the index.js behaviour that needs one is checked by reading its
// source rather than restating it here.
import assert from "node:assert/strict";

import {
  forgetAllTyped,
  forgetTyped,
  forgetTypedPassword,
  local,
  typed,
} from "../../static/js/views/switch/state.js";
import { patch } from "../../static/js/core/store.js";

const INDEX = new URL(
  "../../static/js/views/switch/index.js",
  import.meta.url,
);
const indexText = await Deno.readTextFile(INDEX);

Deno.test("a failed connect leaves no password in typed(ip)", () => {
  forgetAllTyped();
  const box = typed("10.1.1.9");
  box.user = "admin";
  box.password = "secret";

  // What connectSwitch's error path calls (asserted below).
  forgetTypedPassword("10.1.1.9");

  assert.equal(typed("10.1.1.9").password, "");
  // The username is not a secret; the likeliest next act is correcting the
  // password beside it, not retyping both halves.
  assert.equal(typed("10.1.1.9").user, "admin");
});

Deno.test("connectSwitch erases the password on its error path", () => {
  // Read from the source rather than restated: a restatement would keep
  // passing after the original changed. The catch around signIn must call
  // the eraser before it returns.
  const failure = indexText.match(
    /await signIn\(ip[\s\S]*?catch \(error\) \{([\s\S]*?)\r?\n\s*\} finally/,
  );
  assert.ok(failure, "connectSwitch's sign-in catch block was not found");
  assert.match(failure[1], /forgetTypedPassword\(ip\)/);
});

Deno.test("an accepted sign-in erases the whole pair", () => {
  const box = typed("10.1.1.9");
  box.user = "admin";
  box.password = "secret";

  forgetTyped("10.1.1.9");   // what session.js calls when the switch says yes

  assert.equal(local.credentials["10.1.1.9"], undefined);
});

Deno.test("leaving the screen drops everything typed", () => {
  typed("10.1.1.9").password = "secret";
  typed("10.1.1.10").user = "admin";

  forgetAllTyped();

  assert.deepEqual(local.credentials, {});
  // And stop() — what app.js calls when the view changes — is where the
  // screen actually does it.
  assert.match(
    indexText,
    /export function stop\(\) \{[\s\S]*?forgetAllTyped\(\)/,
  );
});

Deno.test("an edition or project change drops every typed pair", () => {
  typed("10.1.1.9").password = "secret";
  typed("10.1.1.10").user = "admin";

  // Both roads republish `edition` (app.js applyEdition); the subscription
  // registered by state.js is what has to react.
  patch({ edition: { mode: "field", stamp: "test" } });

  assert.deepEqual(local.credentials, {});
});
