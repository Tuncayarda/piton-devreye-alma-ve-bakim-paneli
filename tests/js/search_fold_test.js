// The device search has to match what the screen shows. The top bar shows a
// project name that carries Turkish letters, and the operator searching for
// it is typing on whatever keyboard is in the cabinet — so the two spellings
// have to meet in the middle. Both of the obvious ways of doing that are
// wrong, in opposite directions, and this is what holds the fold to the one
// that works.

import assert from "node:assert/strict";

import { fold } from "../../static/js/core/store.js";

const matches = (typed, shown) => fold(shown).includes(fold(typed));

Deno.test("every spelling of the name finds the device", () => {
  // What the DeviceMap calls it, and the four ways it gets typed.
  for (const typed of ["Yataklı", "yataklı", "Yatakli", "yatakli", "YATAKLI"]) {
    assert.ok(matches(typed, "Yataklı_1"), typed);
  }
});

// THE TRAP IN `toLocaleLowerCase('tr')`: it lowercases an ASCII I to a
// dotless one, so the project spelled in ASCII stops matching itself.
Deno.test("an ASCII name is not broken by the folding", () => {
  for (const typed of ["VIP", "vip", "Vip"]) {
    assert.ok(matches(typed, "VIP"), typed);
  }
  assert.ok(matches("gdm", "GDM"));
});

// THE TRAP IN PLAIN `toLowerCase`: it leaves the dotted capital I as an i
// with a combining dot, which no keyboard produces.
Deno.test("the dotted capital I folds to a plain i", () => {
  assert.equal(fold("İSTASYON"), "istasyon");
  assert.ok(matches("istasyon", "İSTASYON"));
});

Deno.test("the rest of the alphabet folds to its ASCII base", () => {
  assert.equal(fold("Güneş"), "gunes");
  assert.equal(fold("ÇÖPLÜK"), "copluk");
  assert.ok(matches("kapi", "Kapı_3"));
});

// Folding is not a licence to match anything: a search that found every row
// would be as useless as one that found none.
Deno.test("folding does not make unrelated names match", () => {
  assert.ok(!matches("vip", "Yataklı_1"));
  assert.ok(!matches("yatakli", "VIP"));
});

Deno.test("nothing typed is nothing to fold", () => {
  for (const empty of ["", null, undefined]) {
    assert.equal(fold(empty), "");
  }
});
