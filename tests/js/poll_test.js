// core/poll.js — the shared repeating round. The house rule it encodes
// (setTimeout chained AFTER the run, never setInterval) is enforced across
// the tree by tests/test_frontend.py; what is asserted here is the handle's
// own contract: the beat runs while `while` holds, dies quietly when it
// stops holding, never overlaps itself, and `now()` is a safe "read once
// immediately".
//
// Real timers, tiny intervals, generous margins — Deno's test sanitizer
// also proves cleanup: a timer left armed past a test's end fails it.
import assert from "node:assert/strict";

import { poll } from "../../static/js/core/poll.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

Deno.test("the beat runs while armed and ends with stop()", async () => {
  let runs = 0;
  const round = poll({ run: () => { runs += 1; }, interval: 5 });
  assert.equal(round.active(), false);
  round.arm();
  assert.equal(round.active(), true);
  await sleep(40);
  round.stop();
  assert.equal(round.active(), false);
  const settled = runs;
  assert.ok(settled >= 2, `the beat ran (${settled} rounds)`);
  await sleep(25);
  assert.equal(runs, settled, "stop() really ends it");
});

Deno.test("a beat whose reason went away dies quietly", async () => {
  // The screens gate on onScreen()/scanning()/running(): when the answer
  // turns false the pending round must neither run nor re-arm — one round
  // too many is a request against a device nobody is looking at.
  let alive = true;
  let runs = 0;
  const round = poll({
    run: () => { runs += 1; },
    interval: 5,
    while: () => alive,
  });
  round.arm();
  await sleep(20);
  alive = false;
  const settled = runs;
  await sleep(25);
  assert.ok(runs <= settled + 1, "at most the round already in flight");
  assert.equal(round.active(), false, "and nothing re-armed");
  // Arming against a false gate is also a no-op, not a queued surprise.
  round.arm();
  assert.equal(round.active(), false);
});

Deno.test("rounds are chained after the run, so they cannot pile up", async () => {
  // A slow reply stretches the beat instead of overlapping it — the whole
  // reason the house rule bans setInterval.
  let inFlight = 0;
  let worst = 0;
  const round = poll({
    run: async () => {
      inFlight += 1;
      worst = Math.max(worst, inFlight);
      await sleep(15);              // three intervals long
      inFlight -= 1;
    },
    interval: 5,
  });
  round.arm();
  await sleep(60);
  round.stop();
  await sleep(20);                  // let a final in-flight run drain
  assert.equal(worst, 1, "two rounds never ran at once");
});

Deno.test("now() runs at once, swallows the pending timer, re-arms", async () => {
  // The resume button's shape: "read once as soon as it resumes, then keep
  // the beat" — without doubling up with a round already queued.
  let runs = 0;
  const round = poll({ run: () => { runs += 1; }, interval: 60 });
  round.arm();                      // a distant round is pending
  await round.now();
  assert.equal(runs, 1, "the read happened immediately");
  assert.equal(round.active(), true, "and the beat carries on");
  round.stop();
  await sleep(15);
  assert.equal(runs, 1, "the swallowed timer never fired as a second run");
});

Deno.test("a run that throws does not kill the beat", async () => {
  // A dropped poll is not worth a message — the next one is an interval
  // away, which only works if the next one still happens.
  let runs = 0;
  const round = poll({
    run: () => {
      runs += 1;
      if (runs === 1) throw new Error("one dropped reply");
    },
    interval: 5,
  });
  round.arm();
  await sleep(30);
  round.stop();
  assert.ok(runs >= 2, "the round after the failure still ran");
});
