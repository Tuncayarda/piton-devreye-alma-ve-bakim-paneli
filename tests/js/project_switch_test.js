// Where a project switch is offered, and — the bug this file exists for —
// whether it goes both ways.
//
// The two lists answer different questions and are deliberately not the same
// list. The top bar switches between the projects THIS PACKAGE was built for
// (VIP and Yatakli, one operator's two train types). The admin screen's
// project card is where another customer's train is opened, which only
// exists in admin mode.
//
// The card first listed only the projects admin mode had ADDED, and that was
// a one-way door: switching from Yatakli to the exhibition rack left a card
// offering GDM, Gaziray and the rack, with the package's own trains nowhere
// on the screen the switch had been made from.
import assert from "node:assert/strict";

// `ownProjects` is a real import now: it moved out of self-starting app.js
// into core/store.js as a selector precisely so this file could stop
// rebuilding it from source text with `new Function`. It takes the state to
// read as an argument, the way core/schedule.js's predicates do, so the
// fixtures below drive it directly.
import { ownProjects } from "../../static/js/core/store.js";

const ADMIN = new URL("../../static/js/views/admin.js", import.meta.url);

// `otherProjects`' filter is still read out of admin.js rather than
// restated here: a restatement keeps passing after the original changes,
// which is the one thing this must not do.
const adminText = await Deno.readTextFile(ADMIN);

// The card no longer filters at all — it lists everything and marks the
// open row — so what is checked here is the whole function's shape: the
// guard that keeps a list of one off the screen, and the marking.
const listsEverything = /const all = state\.projects \|\| \[\];/.test(
  adminText);
assert.ok(listsEverything, "the project list in admin.js has changed shape");
const guard = adminText.match(/if \(all\.length < (\d+)/);
assert.ok(guard, "the short-list guard was not found in admin.js");
const MINIMUM = Number(guard[1]);

const otherProjects = (state) => {
  const all = state.projects || [];
  return all.length < MINIMUM ? [] : all;
};

const catalogue = (currentKey) => ({
  projects: [
    { key: "yatakli", label: "Yatakli", origin: "edition", available: true },
    { key: "vip", label: "VIP", origin: "edition", available: true },
    { key: "gdm", label: "GDM", origin: "extra", available: true },
    { key: "gaziray", label: "Gaziray", origin: "extra", available: true },
    { key: "fuar", label: "Fuar", origin: "extra", available: true },
  ].map((p) => ({ ...p, current: p.key === currentKey })),
});

const labels = (rows) => rows.map((p) => p.label);

Deno.test("the top bar offers only this package's own projects", () => {
  // Another customer's train must not be one click from the project name.
  assert.deepEqual(labels(ownProjects(catalogue("yatakli"))),
    ["Yatakli", "VIP"]);
  // And it stays that way while a foreign project is open, which is what
  // makes it the way back.
  assert.deepEqual(labels(ownProjects(catalogue("fuar"))),
    ["Yatakli", "VIP"]);
});

Deno.test("the admin card lists every project, the open one included", () => {
  assert.deepEqual(labels(otherProjects(catalogue("yatakli"))),
    ["Yatakli", "VIP", "GDM", "Gaziray", "Fuar"]);
});

Deno.test("from a foreign project the package's own are still offered", () => {
  // THE BUG. On Fuar the card used to list GDM, Gaziray and Fuar — no way
  // back to the trains the package is for.
  const offered = labels(otherProjects(catalogue("fuar")));
  assert.ok(offered.includes("Yatakli"),
    `no way back to Yatakli: ${offered.join(", ")}`);
  assert.ok(offered.includes("VIP"));
});

Deno.test("exactly one row is the open one, whichever it is", () => {
  for (const key of ["yatakli", "vip", "gdm", "gaziray", "fuar"]) {
    const rows = otherProjects(catalogue(key));
    assert.equal(rows.length, 5, key);
    assert.deepEqual(rows.filter((p) => p.current).map((p) => p.key), [key]);
  }
});

Deno.test("the open row is marked, and never disabled", () => {
  // Greyed out it would read as "not available to you", which is the
  // opposite of what is true of the project you are looking at. The
  // undelivered ones are the ones that read that way.
  assert.match(adminText, /'aria-current': project\.current \? 'true' : null/);
  assert.match(adminText, /disabled: !project\.available/);
  assert.ok(!/disabled:[^\n]*project\.current/.test(adminText),
    "the open project must not be disabled");
});

Deno.test("a package with one project draws no list at all", () => {
  // A gdm package with no foreign maps opened: a list of one is a heading
  // over a statement of the obvious.
  const single = { projects: [
    { key: "gdm", label: "GDM", origin: "edition", available: true,
      current: true },
  ] };
  assert.deepEqual(otherProjects(single), []);
  assert.deepEqual(labels(ownProjects(single)), ["GDM"]);
});
