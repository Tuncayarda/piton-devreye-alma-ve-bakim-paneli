// The race guard every screen refresh needs, in one place.
//
// The panel's requests are answered by real devices, so a reply can take
// seconds — and the operator can ask again (change the group, change the
// set, press reload) while the first answer is still on the wire. A late
// old reply must never overwrite a newer one. Seven screens each carried
// their own copy of the same counter for this, and the copies had already
// drifted (only some of them re-checked the train set as well); a guard
// that exists seven times is seven places to get it wrong, which is the
// same argument that extracted core/selection.js.
//
// The shape: `latest(run)` returns a function that calls `run` with a
// `fresh()` predicate in front of its own arguments. `fresh()` answers
// whether THIS call is still the newest one, so `run` checks it after
// every await — a refresh with several requests in it (the IP screen
// fetches the plan, then every switch's panel) has several points where a
// newer call may have overtaken it, which is why the caller holds the
// predicate rather than this module holding a single check.
//
// What it deliberately does NOT do is scope to the train set. Some screens
// must also drop a reply when `state.setNo` moved (IP, firmware), some are
// set-free on purpose (ADB, switch — their benches belong to no train),
// and that decision belongs on the screen where a reader can see it:
// `if (!fresh() || setNo !== state.setNo) return;` says both facts in one
// line at the site that owns them.
export function latest(run) {
  let round = 0;
  return function call(...args) {
    round += 1;
    const mine = round;
    return run(() => mine === round, ...args);
  };
}
