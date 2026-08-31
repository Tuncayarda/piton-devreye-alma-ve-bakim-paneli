// core/latest.js — the shared race guard. Seven screens carried their own
// copy of this counter; what is asserted here is the contract they all
// relied on: a reply that was overtaken finds `fresh()` false at its next
// checkpoint, and the newest call never does.
import assert from "node:assert/strict";

import { latest } from "../../static/js/core/latest.js";

// A run whose awaits the test resolves by hand, so "the old reply lands
// after the new one started" is a statement, not a sleep.
function controlled() {
  const gates = [];
  const seen = [];
  const run = latest(async (fresh, name) => {
    await new Promise((resolve) => gates.push(resolve));
    if (!fresh()) return "stale";
    seen.push(name);
    return name;
  });
  return { run, gates, seen };
}

Deno.test("a call overtaken mid-flight is retired at its checkpoint", async () => {
  const { run, gates, seen } = controlled();
  const first = run("old");
  const second = run("new");
  // Both replies land, the OLD one last — the exact shape of the bug the
  // guard exists for (a slow device answering after the group changed).
  gates[1]();
  gates[0]();
  assert.deepEqual(await Promise.all([first, second]), ["stale", "new"]);
  assert.deepEqual(seen, ["new"], "only the newest call did its work");
});

Deno.test("the newest call stays fresh through every checkpoint", async () => {
  // A refresh with several requests in it (the IP screen: the plan, then
  // every switch's panel) checks fresh() after each — all must hold as long
  // as nothing overtook it.
  const marks = [];
  const run = latest(async (fresh) => {
    marks.push(fresh());
    await Promise.resolve();
    marks.push(fresh());
    await Promise.resolve();
    marks.push(fresh());
  });
  await run();
  assert.deepEqual(marks, [true, true, true]);
});

Deno.test("arguments pass through behind the predicate", async () => {
  const got = [];
  const run = latest((fresh, a, b = "default") => {
    got.push([fresh(), a, b]);
    return Promise.resolve(a);
  });
  assert.equal(await run("x", "y"), "x");
  assert.equal(await run("z"), "z");
  assert.deepEqual(got, [[true, "x", "y"], [true, "z", "default"]]);
});

Deno.test("two guarded functions never retire each other", async () => {
  // Each wrapper owns its own counter — the config screen's reload must not
  // invalidate the firmware screen's, however interleaved they run.
  const first = controlled();
  const second = controlled();
  const a = first.run("a");
  const b = second.run("b");
  first.gates[0]();
  second.gates[0]();
  await Promise.all([a, b]);
  assert.deepEqual(first.seen, ["a"]);
  assert.deepEqual(second.seen, ["b"]);
});

Deno.test("a synchronous early return still counts as the newest call", async () => {
  // Some refreshes bail out before their first await (the config screen on
  // an empty group). The bail-out must still retire an older in-flight
  // reply: what the operator asked for LAST is the truth on screen.
  const { run, gates, seen } = controlled();
  const old = run("old");
  const guard = latest(() => {});
  guard();                               // unrelated wrapper: no effect
  run("new");                            // overtakes without ever resolving
  gates[0]();
  assert.equal(await old, "stale");
  assert.deepEqual(seen, []);
});
