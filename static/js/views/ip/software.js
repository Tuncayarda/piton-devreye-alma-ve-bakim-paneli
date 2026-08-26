// Pure helpers for the Compartment LCD software step on the IP screen.
//
// Keeping these decisions outside the DOM renderer makes the safety gate easy
// to test: only actionable rows with a real DeviceMap id enter the APK choice,
// and a per-device source address can never be replaced by the Intercom's
// shared factory-address override.

export const LCD_ASSIGNMENT_KIND = 'compartment-lcd';

// DeviceMap names are operator-facing identifiers, not translation keys.
// Keep them byte-for-byte as text throughout the IP and APK views.
export function deviceMapName(row) {
  return row && row.name != null ? String(row.name) : '';
}

export function isCompartmentPlan(plan) {
  return !!plan && plan.assignmentKind === LCD_ASSIGNMENT_KIND;
}

// In the bench flow the selected ports are physical switch ports, not the
// ports where DeviceMap normally places each LCD.  The server therefore keeps
// two deliberately separate lists:
//
// * rows          — the physical ports that will be power-cycled;
// * candidateRows — the immutable DeviceMap identities/IPs that may be found.
//
// Never infer an identity from a physical port in the browser.  The runner
// proves that mapping from the source address and the switch MAC table.
export function usesPhysicalPortDiscovery(plan) {
  return isCompartmentPlan(plan) && plan.physicalPortMode === true;
}

export function deviceCandidateRows(plan) {
  if (!plan) return [];
  if (usesPhysicalPortDiscovery(plan)) {
    return Array.isArray(plan.candidateRows) ? plan.candidateRows : [];
  }
  return Array.isArray(plan.rows) ? plan.rows : [];
}

export function softwareRows(plan) {
  const seen = new Set();
  return deviceCandidateRows(plan).filter(row => {
    const id = String(row.deviceId || '');
    // Candidate rows describe real DeviceMap records.  Older plans publish an
    // explicit actionable flag; the new candidate list need not repeat it.
    if (row.actionable === false || !id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export function softwareDeviceIds(plan) {
  return softwareRows(plan).map(row => String(row.deviceId));
}

export function softwareFiles(plan) {
  const software = (plan && plan.software) || {};
  return software.files && typeof software.files === 'object'
    ? software.files : {};
}

export function missingSoftwareRows(plan) {
  const files = softwareFiles(plan);
  return softwareRows(plan).filter(
    row => !(files[row.deviceId] && files[row.deviceId].selected));
}

// Firmware endpoints return only the records affected by the last operation.
// Merge them into the plan instead of discarding the other rows' choices.
export function mergedSoftware(plan, reply) {
  const current = (plan && plan.software) || {};
  const changed = reply && reply.files && typeof reply.files === 'object'
    ? reply.files : {};
  return { ...current, files: { ...softwareFiles(plan), ...changed } };
}

// Is every row's source its own address rather than one shared one?
//
// True for a Compartment LCD: each display arrives on the set-1 form of its
// own DeviceMap address, not on one address they all share.
export function perDeviceSource(plan) {
  return !!plan && plan.sourceMode === 'perDevice';
}

export function sourceAddress(plan, row, sharedOverride = '') {
  if (perDeviceSource(plan)) return row.sourceIp || row.factoryIp || '';
  return sharedOverride || row.sourceIp || row.factoryIp || '';
}
