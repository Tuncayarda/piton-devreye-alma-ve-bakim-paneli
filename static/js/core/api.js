// The local API client.
//
// A password travels ONLY in the body of `tryCredentials()`, once. It is
// never stored, never written to global state, never attached to another
// request. The server does not send it back either.

import { transport } from "./transport.js";
import { t } from "./i18n.js";

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
      throw new ApiError(t("error.serviceUnreachable"), 0, {});
    }
    const body = envelope.body && typeof envelope.body === "object" &&
        !Array.isArray(envelope.body)
      ? envelope.body
      : {};
    if (!envelope.ok) {
      throw new ApiError(
        body.error || t("error.requestFailed", { status: envelope.status }),
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
    // What this package is and what it may show. Re-read after entering or
    // leaving admin mode and after a project change, because all three move
    // the list of screens.
    edition: () => get("/api/edition"),
    selectProject: (key) => post("/api/project/select", { key }),

    // The service key. `adminKey` carries no secret — "is one in the
    // machine", "was it recognised", and a counter that moves when the
    // answer changes.
    adminKey: () => get("/api/admin/key"),
    adminMode: (enter) => post("/api/admin/mode", { enter }),
    adminKeyVolumes: () => get("/api/admin/key/volumes"),
    adminKeyWrite: (volume, label) =>
      post("/api/admin/key/write", { volume, label }),
    // Whole drives rather than mounted volumes: what this lists is about to
    // be erased. `adminKeyPrepare` is the one destructive call in the API.
    adminKeyDrives: () => get("/api/admin/key/drives"),
    adminKeyPrepare: (drive, label) =>
      post("/api/admin/key/prepare", { drive, label }),
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
    // The image installed before an address is written. The path never
    // travels: the OS dialog opens on the server side and only the file's
    // name comes back. `clear` forgets the choice.
    ipPreflashFile: (clear = false) =>
      post("/api/ip/preflash-file", { clear }),
    ipRun: (body) => post("/api/ip/run", body),
    // Test flow: ask the selected devices to move to the factory address.
    // For a Compartment LCD "factory" means each display's own set-1 address,
    // and the server runs the Android flow rather than the HTTP one.
    ipFactoryReset: (body) => post("/api/ip/factory-reset", body),
    // The bench flow: one switch port, one address typed by hand. Only the
    // Compartment LCD has it — see panel/api/routes/ip_routes.py.
    ipLcdAssign: (body) => post("/api/ip/lcd-assign", body),

    // The computer's own network. A device on the factory address sits on
    // another network than the train set, so the panel gives itself an
    // address there; these are the manual controls for what a run does on its
    // own. Every answer carries the whole state back, so the screen never has
    // to guess what changed.
    network: (set) => get("/api/network", { set }),
    networkPrepare: (set) => post("/api/network/prepare", { set }),
    // With no `ip`, every address the panel added is taken back. An address
    // the panel did not add can never be released — the server matches
    // against its own record.
    networkRelease: (set, ip) => post("/api/network/release", { set, ip }),
    networkSettings: (values) => post("/api/network/settings", values),

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
    firmwarePick: (set, group, devices) =>
      post("/api/firmware/pick", { set, group, devices }),
    firmwareRemove: (set, group, devices) =>
      post("/api/firmware/remove", { set, group, devices }),
    firmwareInstall: (set, group, devices) =>
      post("/api/firmware/install", { set, group, devices }),

    // ── the ADB screen ──
    // No `set` on any of these, and that is the whole point: this screen's
    // devices are a list of addresses the user keeps, not a project (see
    // panel/adb/pool.py).
    adb: () => get("/api/adb"),
    // The runner alone, polled once a second while an operation runs. Its
    // `generation` counter is what lets the client tell in one integer
    // whether anything moved.
    adbState: () => get("/api/adb/state"),
    adbDevices: (body) => post("/api/adb/devices", body),
    // The picker opens in the OS; the path never travels from the browser.
    adbImport: () => post("/api/adb/import", {}),
    // Nor does the destination: the server picks it (Documents).
    adbExport: () => post("/api/adb/export", {}),
    adbPackages: (devices, keyword) =>
      post("/api/adb/packages", { devices, keyword }),
    adbApk: () => post("/api/adb/apk", {}),
    adbAutostart: (devices, name) =>
      post("/api/adb/autostart", { devices, package: name }),
    // Which files an autostart install would write. Asked before the
    // confirmation dialog so it names the paths the server will really use.
    adbAutostartFiles: (name) =>
      post("/api/adb/autostart/files", { package: name }),
    adbRun: (body) => post("/api/adb/run", body),
    adbCancel: () => post("/api/adb/cancel", {}),

    // ── the switch screen ──
    // No `set` here either: a switch is reached by address, and the screen
    // works on whichever one the operator found (panel/switch).
    switchScreen: () => get("/api/switch"),
    switchInfo: (ip) => get("/api/switch/info", { ip }),
    switchPorts: (ip) => get("/api/switch/ports", { ip }),
    // A sweep is a queued job, not an inline call: a /24 runs for minutes.
    switchDiscover: (cidr) => post("/api/switch/discover", { cidr }),
    switchDiscoverCancel: () => post("/api/switch/discover/cancel", {}),
    // THE ONE CALL THAT CARRIES A PASSWORD, and it carries it once. The
    // value comes straight from the dialog's field; it is not stored, not
    // written to the state above, and not sent again.
    switchLogin: (ip, username, password, applyToGroup) =>
      post("/api/switch/login", { ip, username, password, applyToGroup }),
    switchLogout: (ip) => post("/api/switch/logout", { ip }),
    switchPoe: (ip, port, mode) => post("/api/switch/poe", { ip, port, mode }),
    switchPort: (ip, port, body) =>
      post("/api/switch/port", { ip, port, ...body }),
    switchBatch: (ip, poe, ports) =>
      post("/api/switch/batch", { ip, poe, ports }),
    switchNetwork: (ip, values) => post("/api/switch/network", { ip, ...values }),
    switchConfigSave: (ip) => post("/api/switch/config-save", { ip }),
    switchReboot: (ip) => post("/api/switch/reboot", { ip }),
    switchFactoryReset: (ip, confirm) =>
      post("/api/switch/factory-reset", { ip, confirm }),

    checklistExport: (set) => post("/api/checklist/export", { set }),

    piscu: (set) => get("/api/piscu", { set }),
    mqtt: () => get("/api/mqtt"),
    mqttStart: (set) => post("/api/mqtt/start", { set }),
    mqttStop: () => post("/api/mqtt/stop"),
  };
}

export const api = createApi();
