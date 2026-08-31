import assert from "node:assert/strict";

import { createApi } from "../../static/js/core/api.js";
import {
  CAPABILITY_FLAG,
  createTransport,
  TRANSPORT_FLAG,
} from "../../static/js/core/transport.js";
import { applyCatalogue, t } from "../../static/js/core/i18n.js";
import { activePanelError } from "../../static/js/views/ip/ports.js";

// The real catalogue, exactly as the app loads it over /api/language.
// Without it every message here would render as its own key, and this
// file would be asserting that the wiring is broken.
applyCatalogue({
  language: "en",
  languages: ["en", "tr"],
  messages: JSON.parse(
    Deno.readTextFileSync(
      new URL("../../panel/messages/en.json", import.meta.url),
    ),
  ),
});

const ok = (body = {}) => ({ ok: true, status: 200, body });
const CAPABILITY = "A".repeat(43);

Deno.test("the api surface keeps its 82 methods", () => {
  const api = createApi({ request: () => ok() });
  const methods = Object.keys(api).filter((name) => name !== "ApiError").sort();
  assert.deepEqual(
    methods,
    [
      "adb",
      "adbApk",
      "adbAutostart",
      "adbAutostartFiles",
      "adbCancel",
      "adbDevices",
      "adbExport",
      "adbImport",
      "adbPackages",
      "adbRun",
      "adbState",
      "adminKey",
      "adminKeyDrives",
      "adminKeyPrepare",
      "adminKeyVolumes",
      "adminKeyWrite",
      "adminMode",
      "checklist",
      "checklistExport",
      "config",
      "configApply",
      "configFields",
      "configReset",
      "configTarget",
      "device",
      "edition",
      "firmware",
      "firmwareInstall",
      "firmwarePick",
      "firmwareRemove",
      "forgetAllCredentials",
      "forgetCredentials",
      "ipFactoryReset",
      "ipLcdAssign",
      "ipPanel",
      "ipPlan",
      "ipPreflashFile",
      "ipProtected",
      "ipRun",
      "job",
      "jobCancel",
      "jobFile",
      "jobRemove",
      "jobs",
      "language",
      "mqtt",
      "mqttStart",
      "mqttStop",
      "network",
      "networkPrepare",
      "networkRelease",
      "networkSettings",
      "piscu",
      "project",
      "refresh",
      "remote",
      "remoteDisconnect",
      "remotePair",
      "remotePairCancel",
      "remotePairPoll",
      "remoteSignin",
      "remoteSignup",
      "scan",
      "selectProject",
      "setLanguage",
      "state",
      "switchBatch",
      "switchConfigSave",
      "switchDiscover",
      "switchDiscoverCancel",
      "switchFactoryReset",
      "switchInfo",
      "switchLogin",
      "switchLogout",
      "switchNetwork",
      "switchPoe",
      "switchPort",
      "switchPorts",
      "switchReboot",
      "switchScreen",
      "tryCredentials",
      "version",
    ],
  );
});

Deno.test("a DeviceMap fallback cannot make IP assignment ready", () => {
  const panel = {
    switchName: "SW-1",
    hasCredentials: true,
    source: "devicemap",
    note: "The switch is unreachable",
  };

  assert.equal(
    activePanelError(panel, { id: "sw1" }, false),
    "The switch is unreachable",
  );
});

Deno.test("a live switch panel passes the readiness gate", () => {
  const panel = {
    switchName: "SW-1",
    hasCredentials: true,
    source: "switch",
  };

  assert.equal(activePanelError(panel, { id: "sw1" }, false), "");
});

Deno.test("empty query values are dropped from the URL", async () => {
  const calls = [];
  const api = createApi({
    request: (...args) => {
      calls.push(args);
      return ok({ done: true });
    },
  });

  await api.ipPlan(2, "Intercom", "", "sw-1");
  const body = { set: 2, switch: "sw-1", ports: "1,2" };
  await api.ipRun(body);

  assert.deepEqual(calls[0], [
    "GET",
    "/api/ip/plan?set=2&groups=Intercom&switch=sw-1",
    {},
  ]);
  assert.deepEqual(calls[1], ["POST", "/api/ip/run", body]);
});

Deno.test("a failing envelope becomes an ApiError carrying the body", async () => {
  const body = { error: "A scan is running", state: { scanRunning: true } };
  const api = createApi({
    request: () => ({ ok: false, status: 409, body }),
  });

  await assert.rejects(
    () => api.version(),
    (error) => {
      assert.equal(error.name, "Error");
      assert.equal(error.constructor, api.ApiError);
      assert.equal(error.status, 409);
      assert.equal(error.message, "A scan is running");
      assert.equal(error.body, body);
      return true;
    },
  );
});

Deno.test("a transport-thrown message survives to the ApiError", async () => {
  // The transport words its own failures (an invalid bridge envelope, a
  // missing capability, pywebview absent, the handshake timeout). The api
  // layer used to flatten every one of them into the generic "service
  // unreachable" line; the wording has to reach the caller.
  const api = createApi({
    request: () => {
      throw new Error(t("error.bridgeReadyTimeout"));
    },
  });

  await assert.rejects(
    () => api.version(),
    (error) => {
      assert.equal(error.constructor, api.ApiError);
      assert.equal(error.status, 0);
      assert.equal(error.message, t("error.bridgeReadyTimeout"));
      assert.deepEqual(error.body, {});
      return true;
    },
  );
});

Deno.test("a wordless transport failure falls back to the generic line", async () => {
  const api = createApi({
    request: () => Promise.reject(new Error("")),
  });

  await assert.rejects(
    () => api.version(),
    (error) => {
      assert.equal(error.status, 0);
      assert.equal(error.message, t("error.serviceUnreachable"));
      return true;
    },
  );
});

Deno.test("a malformed envelope reports the service as unreachable", async () => {
  const api = createApi({ request: () => ({ ok: "yes" }) });

  await assert.rejects(
    () => api.version(),
    (error) => {
      assert.equal(error.status, 0);
      assert.equal(error.message, t("error.serviceUnreachable"));
      assert.deepEqual(error.body, {});
      return true;
    },
  );
});

Deno.test("without the transport flag the request goes over HTTP", async () => {
  const root = new EventTarget();
  let call = null;
  root[TRANSPORT_FLAG] = undefined;
  root[CAPABILITY_FLAG] = null;
  root.fetch = (path, options) => {
    call = { path, options };
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: () => Promise.resolve({ done: true }),
    });
  };
  const transport = createTransport(root);

  const result = await transport.request("POST", "/api/scan", { set: 3 });

  assert.deepEqual(result, ok({ done: true }));
  assert.equal(call.path, "/api/scan");
  assert.equal(call.options.method, "POST");
  assert.equal(call.options.body, '{"set":3}');
  assert.equal(call.options.cache, "no-store");
  assert.equal(call.options.headers["Content-Type"], "application/json");
});

Deno.test("in bridge mode the call goes to pywebview, never to fetch", async () => {
  const root = new EventTarget();
  let fetchCount = 0;
  let call = null;
  root[TRANSPORT_FLAG] = "bridge";
  root[CAPABILITY_FLAG] = CAPABILITY;
  root.fetch = () => {
    fetchCount += 1;
  };
  root.pywebview = {
    api: {
      invoke: (...args) => {
        call = args;
        return ok({ version: "1.0" });
      },
    },
  };
  const transport = createTransport(root);

  const result = await transport.request("GET", "/api/version");

  assert.deepEqual(call, [CAPABILITY, "GET", "/api/version", {}]);
  assert.deepEqual(result, ok({ version: "1.0" }));
  assert.equal(fetchCount, 0);
});

Deno.test("a bridge that is not ready yet waits for pywebviewready", async () => {
  const root = new EventTarget();
  root[TRANSPORT_FLAG] = "bridge";
  root[CAPABILITY_FLAG] = CAPABILITY;
  root.fetch = () => {
    throw new Error("fetch must not be used");
  };
  const transport = createTransport(root);
  const pending = transport.request("GET", "/api/version");

  setTimeout(() => {
    root.pywebview = {
      api: { invoke: () => ok({ ready: true }) },
    };
    root.dispatchEvent(new Event("pywebviewready"));
  }, 0);

  assert.deepEqual(await pending, ok({ ready: true }));
});

Deno.test("the second check finds a bridge that raced the listener setup", async () => {
  class RacingRoot extends EventTarget {
    addEventListener(type, listener, options) {
      super.addEventListener(type, listener, options);
      if (type === "pywebviewready" && !this.pywebview) {
        this.pywebview = {
          api: {
            invoke: () => ok({ ready: true }),
          },
        };
      }
    }
  }

  const root = new RacingRoot();
  root[TRANSPORT_FLAG] = "bridge";
  root[CAPABILITY_FLAG] = CAPABILITY;
  root.fetch = () => {
    throw new Error("fetch must not be used");
  };
  const transport = createTransport(root);

  assert.deepEqual(
    await transport.request("GET", "/api/version"),
    ok({ ready: true }),
  );
});

Deno.test("a failing bridge invoke never falls back to HTTP", async () => {
  const root = new EventTarget();
  let fetchCount = 0;
  root[TRANSPORT_FLAG] = "bridge";
  root[CAPABILITY_FLAG] = CAPABILITY;
  root.fetch = () => {
    fetchCount += 1;
  };
  root.pywebview = {
    api: {
      invoke: () => {
        throw new Error("the bridge closed");
      },
    },
  };
  const transport = createTransport(root);

  await assert.rejects(() => transport.request("GET", "/api/version"));
  assert.equal(fetchCount, 0);
});

Deno.test("a missing bridge capability stays fail-closed", async () => {
  const root = new EventTarget();
  let fetchCount = 0;
  let invokeCount = 0;
  root[TRANSPORT_FLAG] = "bridge";
  root.fetch = () => {
    fetchCount += 1;
  };
  root.pywebview = {
    api: {
      invoke: () => {
        invokeCount += 1;
        return ok();
      },
    },
  };
  const transport = createTransport(root);

  await assert.rejects(() => transport.request("GET", "/api/version"));
  assert.equal(fetchCount, 0);
  assert.equal(invokeCount, 0);
});
