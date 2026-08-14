// Chooses, in one place, how the UI reaches Python.
//
// On an ordinary browser page there is no marker and the existing
// same-origin HTTP endpoints are used. The single HTML generated for the
// desktop writes this explicitly before any module runs:
//
//   window.__PANEL_TRANSPORT__ = 'bridge';
//   window.__PANEL_CAPABILITY__ = '<per-session-random-value>';
//
// Bridge mode deliberately does not fall back to HTTP. If the bridge cannot
// be established the error goes to the caller; anything else would hide a
// packaging fault and put the app back on the local network loop.

export const TRANSPORT_FLAG = "__PANEL_TRANSPORT__";
export const CAPABILITY_FLAG = "__PANEL_CAPABILITY__";

const BRIDGE_MODE = "bridge";
const BRIDGE_TIMEOUT_MS = 15000;
const CAPABILITY_PATTERN = /^[A-Za-z0-9_-]{43}$/;

const isObject = (value) =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value);

function validateEnvelope(envelope) {
  if (
    !isObject(envelope) ||
    typeof envelope.ok !== "boolean" ||
    !Number.isInteger(envelope.status)
  ) {
    throw new Error("The desktop bridge returned an invalid response");
  }
  return {
    ok: envelope.ok,
    status: envelope.status,
    body: isObject(envelope.body) ? envelope.body : {},
  };
}

export function createTransport(root = globalThis) {
  let bridgePromise = null;

  const isBridgeMode = () => root[TRANSPORT_FLAG] === BRIDGE_MODE;

  const bridgeCapability = () => {
    const capability = root[CAPABILITY_FLAG];
    if (
      typeof capability !== "string" ||
      !CAPABILITY_PATTERN.test(capability)
    ) {
      throw new Error("The desktop bridge capability is invalid");
    }
    return capability;
  };

  const bridgeApi = () => {
    const api = root.pywebview && root.pywebview.api;
    return api && typeof api.invoke === "function" ? api : null;
  };

  // pywebviewready can arrive between the first check and the listener
  // being installed. Looking a second time after the listener is added
  // closes that race. If the API is already there we do not wait for the
  // event at all.
  const awaitBridge = () => {
    const ready = bridgeApi();
    if (ready) return ready;
    if (bridgePromise) return bridgePromise;

    bridgePromise = new Promise((resolve, reject) => {
      let settled = false;
      let timer = null;
      const setTimer = (root.setTimeout || globalThis.setTimeout).bind(root);
      const clearTimer = (root.clearTimeout || globalThis.clearTimeout).bind(root);

      const cleanup = () => {
        root.removeEventListener("pywebviewready", onReady);
        if (timer !== null) clearTimer(timer);
      };
      const finish = (settle, value) => {
        if (settled) return;
        settled = true;
        cleanup();
        settle(value);
      };
      const onReady = () => {
        const api = bridgeApi();
        if (api) finish(resolve, api);
        else finish(reject, new Error("The desktop bridge is not ready"));
      };

      root.addEventListener("pywebviewready", onReady, { once: true });

      // The event may have arrived just before the listener above was set.
      const readyMeanwhile = bridgeApi();
      if (readyMeanwhile) {
        finish(resolve, readyMeanwhile);
        return;
      }

      timer = setTimer(() =>
        finish(
          reject,
          new Error("The desktop bridge did not become ready in time"),
        ), BRIDGE_TIMEOUT_MS);
    });
    return bridgePromise;
  };

  const httpRequest = async (method, path, body) => {
    const options = {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    };
    if (method !== "GET") {
      options.method = method;
      options.body = JSON.stringify(body || {});
    }
    const response = await root.fetch(path, options);
    let payload = {};
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }
    }
    return {
      ok: response.ok,
      status: response.status,
      body: isObject(payload) ? payload : {},
    };
  };

  const bridgeRequest = async (method, path, body) => {
    const capability = bridgeCapability();
    const api = await awaitBridge();
    const envelope = await api.invoke(capability, method, path, body || {});
    return validateEnvelope(envelope);
  };

  return {
    request(method, path, body = {}) {
      return isBridgeMode()
        ? bridgeRequest(method, path, body)
        : httpRequest(method, path, body);
    },
  };
}

export const transport = createTransport();
