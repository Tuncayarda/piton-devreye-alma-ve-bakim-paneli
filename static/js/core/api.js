// The local API client.
//
// A password travels ONLY in the body of `tryCredentials()`, once. It is
// never stored, never written to global state, never attached to another
// request. The server does not send it back either.

import { transport } from "./transport.js";

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

export function createApi(carrier = transport) {
  async function request(method, path, payload = {}) {
    let envelope;
    try {
      envelope = await carrier.request(method, path, payload);
      if (
        !envelope || typeof envelope.ok !== "boolean" ||
        !Number.isInteger(envelope.status)
      ) throw new Error("invalid response");
    } catch {
      throw new ApiError("The panel service is unreachable", 0, {});
    }
    const body = envelope.body && typeof envelope.body === "object" &&
        !Array.isArray(envelope.body)
      ? envelope.body
      : {};
    if (!envelope.ok) {
      throw new ApiError(
        body.error || `The request failed (${envelope.status})`,
        envelope.status,
        body,
      );
    }
    return body;
  }

  const get = (path, query = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") {
        params.set(key, String(value));
      }
    }
    const encoded = params.toString();
    return request("GET", path + (encoded ? `?${encoded}` : ""));
  };

  const post = (path, body = {}) => request("POST", path, body);

  return {
    ApiError,

    version: () => get("/api/version"),
    // The message catalogue. Fetched before the first paint; the POST comes
    // back with the whole new catalogue so nothing renders half-translated.
    language: () => get("/api/language"),
    setLanguage: (code) => post("/api/language", { language: code }),
    project: (set) => get("/api/project", { set }),
    state: (set) => get("/api/state", { set }),
    device: (set, id) => get("/api/device", { set, id }),
    checklist: (set) => get("/api/checklist", { set }),

    jobs: () => get("/api/jobs"),
    job: (id) => get("/api/job", { id }),
    jobCancel: (id) => post("/api/job/cancel", { id }),
    jobRemove: (id) => post("/api/job/remove", { id }),
    // The client does not hold the path to open; the server reads it from
    // the job record.
    jobFile: (id, row, reveal = false) =>
      post("/api/job/file", { id, row, reveal }),

    // `auto`: the UI's minute-long discovery round. Told apart from a
    // manually started scan and pruned from history (see jobs.queue).
    scan: (set, auto = false) => post("/api/scan", { set, auto }),
    refresh: (set, devices) => post("/api/refresh", { set, devices }),

    // The only place a password appears. The caller clears the form the
    // moment the reply arrives and keeps nothing.
    tryCredentials: (set, deviceId, username, password, applyToGroup) =>
      post("/api/credentials", {
        set,
        deviceId,
        username,
        password,
        applyToGroup,
      }),
    forgetCredentials: (set, deviceId) =>
      post("/api/credentials/forget", { set, deviceId }),
    forgetAllCredentials: () => post("/api/credentials/forget", { all: true }),

    adminLogin: (password) => post("/api/admin/login", { password }),

    // `groups`: comma-separated group names — a run can target several
    // device groups.
    ipPlan: (set, groups, ports, sw) =>
      get("/api/ip/plan", { set, groups, ports, switch: sw }),
    ipPanel: (set, sw) => get("/api/ip/panel", { set, switch: sw }),
    // Ports the run must not touch: the computer's location and the
    // switch-to-switch links. All found from MAC tables, none asked for.
    ipProtected: (set) => get("/api/ip/protected", { set }),
    // Diagnostics: which device sits on which candidate address. The device
    // reports its own extension, so "whose address is this" is answered
    // exactly. Read-only.
    ipAddressMap: (set, sw, group, factoryIp) =>
      get("/api/ip/address-map", { set, switch: sw, group, factoryIp }),
    ipRun: (body) => post("/api/ip/run", body),
    // Test flow: ask the selected devices to move to the factory address.
    ipFactoryReset: (body) => post("/api/ip/factory-reset", body),

    config: (set, id, group) => get("/api/config", { set, id, group }),
    // A fast endpoint that never reaches the device: field list + targets.
    // On a group change the screen waits for this, not the slow device read.
    configFields: (set, id, group) =>
      get("/api/config/fields", { set, id, group }),
    configReset: (set, deviceId, group) =>
      post("/api/config/reset", { set, deviceId, group }),
    // scope: 'group' = the value goes to the whole group, 'device' = only
    // that device.
    configTarget: (set, deviceId, field, value, group, scope = "device") =>
      post("/api/config/target", { set, deviceId, field, value, group, scope }),
    configApply: (set, group, devices) =>
      post("/api/config/apply", { set, group, devices }),

    // An image is chosen per device. With `devices` given only those are
    // assigned/cleared, otherwise every device in the group.
    firmware: (set, group) => get("/api/firmware", { set, group }),
    // The file picker opens in the OS: the browser does not reveal the real
    // path. The request lasts until the user closes the window — no timeout.
    firmwarePick: (set, group, devices, version) =>
      post("/api/firmware/pick", { set, group, devices, version }),
    firmwareVersion: (set, group, devices, version) =>
      post("/api/firmware/version", { set, group, devices, version }),
    firmwareRemove: (set, group, devices) =>
      post("/api/firmware/remove", { set, group, devices }),
    firmwareInstall: (set, group, devices) =>
      post("/api/firmware/install", { set, group, devices }),

    checklistExport: (set) => post("/api/checklist/export", { set }),

    piscu: (set) => get("/api/piscu", { set }),
    mqtt: () => get("/api/mqtt"),
    mqttStart: (set) => post("/api/mqtt/start", { set }),
    mqttStop: () => post("/api/mqtt/stop"),
  };
}

export const api = createApi();
