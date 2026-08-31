// One repeating round, armed with setTimeout AFTER the previous round
// finished — the house rule (see the header of app.js): with setInterval a
// slow device makes requests pile up, with a chained timeout the interval
// is the GAP between rounds and a slow reply only stretches the beat.
//
// The switch and ADB screens each hand-rolled this pair of functions
// (schedulePoll/pollRound) and the IP screen rolled it three more times for
// its three rounds; the copies were near-identical and none was tested.
// The timers here have also broken twice before in the same way — a round
// rebuilt on every render never elapses (the double-timer bug recorded in
// views/ip/index.js) — so the handle exposes `active()` for the one caller
// pattern that is safe on a render path: arm only what is not armed.
//
//   const round = poll({ run, interval, while: () => onScreen() });
//   round.arm();                          // start the beat (interval first)
//   round.now();                          // run once now, then keep the beat
//   round.stop();                         // disarm (leave() calls this)
//   if (!round.active()) round.arm();     // render-safe re-arm
//
// `while` is asked before arming and again when the timer fires, so a beat
// whose reason has gone away (screen left, sweep finished, refresh paused)
// dies quietly instead of running one round too many. `run` is expected to
// report its own failures — a dropped poll is not worth a message when the
// next one is an interval away — so a throw is swallowed here and the beat
// carries on.
export function poll({ run, interval, while: alive = () => true }) {
  let timer = null;

  function stop() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function arm() {
    stop();
    if (!alive()) return;
    timer = setTimeout(round, interval);
  }

  // Also the "read once as soon as it resumes" path: stop any pending
  // timer first so a round already on its way cannot double up with this
  // one, run, then re-arm — exactly the shape every hand-rolled copy had.
  async function round() {
    stop();
    if (!alive()) return;
    try {
      await run();
    } catch { /* the run reports its own failures; the next round retries */ }
    arm();
  }

  return { arm, stop, now: round, active: () => timer !== null };
}
