// When an automatic round may run — the decision alone, without the timers.
//
// Kept out of app.js so the rule that is easiest to get wrong can be stated
// as a test: PAUSING STOPS THE ROUNDS THE PANEL STARTS BY ITSELF, and nothing
// else. A scan the user asked for is still theirs to ask for, and a job
// already in the queue is not the panel's to skip. Reading a device is not
// free — a Compartment LCD is read over adb, and a round arriving mid-session
// takes the connection out from under whoever is working on that panel.

// Runs that WRITE to devices. No round starts on its own while one is in
// progress (the server-side counterpart: panel.api.presenters.
// WRITING_JOB_KINDS).
export const WRITING_JOB_KINDS = new Set([
  'ip', 'ipfactory', 'config', 'firmware',
]);

export function writingRunInProgress(jobs) {
  return (jobs || []).some(
    job => WRITING_JOB_KINDS.has(job.kind)
      && (job.state === 'running' || job.state === 'queued'));
}

// The discovery round: every address in DeviceMap, one timeout per device
// that does not answer.
export function scanRoundAllowed(state) {
  return !!state.meta && state.autoRefresh !== false && !state.scanRunning
    && !writingRunInProgress(state.jobs);
}

// The light round: only devices that went green in the last discovery. Held
// back by ANY running job, not only the writing ones — this round reads on
// the request's own thread and is the only path that can collide.
export function lightRoundAllowed(state) {
  return !!state.meta && state.autoRefresh !== false && !state.scanRunning
    && !(state.jobs || []).some(job => job.state === 'running');
}
