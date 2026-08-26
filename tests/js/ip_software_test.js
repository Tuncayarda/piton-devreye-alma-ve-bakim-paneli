import assert from "node:assert/strict";

import { applyCatalogue } from "../../static/js/core/i18n.js";
import {
  IP_TARGETS,
  local,
  selectAssignmentSwitch,
  targetLabel,
} from "../../static/js/views/ip/state.js";
import {
  deviceCandidateRows,
  deviceMapName,
  isCompartmentPlan,
  mergedSoftware,
  missingSoftwareRows,
  softwareDeviceIds,
  sourceAddress,
  usesPhysicalPortDiscovery,
} from "../../static/js/views/ip/software.js";
import { planRowStateKey } from "../../static/js/views/ip/plan_table.js";
import { portIsSelectable } from "../../static/js/views/ip/panel.js";
import { parsePorts } from "../../static/js/views/ip/ports.js";

function lcdPlan() {
  return {
    assignmentKind: "compartment-lcd",
    physicalPortMode: true,
    sourceMode: "perDevice",
    allowedPorts: Array.from({ length: 24 }, (_, index) => index + 1),
    rows: [
      {
        port: 8,
        deviceId: null,
        name: "Compartment LCD",
        group: "Compartment LCD",
        actionable: true,
        sourceIp: "",
        targetIp: "",
      },
    ],
    candidateRows: [
      {
        port: 13,
        deviceId: "lcd-1",
        name: "Compartment_Lcd_1",
        actionable: true,
        sourceIp: "10.1.1.40",
        factoryIp: "10.1.1.40",
      },
      {
        port: 14,
        deviceId: "lcd-2",
        name: "Compartment_Lcd_2",
        actionable: true,
        sourceIp: "10.1.1.41",
        factoryIp: "10.1.1.41",
      },
    ],
    software: {
      supported: true,
      extension: "apk",
      files: {
        "lcd-1": { selected: true, name: "panel.apk", size: 2048 },
        "lcd-2": { selected: false, name: "", size: 0 },
      },
    },
  };
}

Deno.test("the IP picker keeps the DeviceMap Compartment LCD group verbatim", () => {
  applyCatalogue({
    language: "tr",
    languages: ["en", "tr"],
    messages: JSON.parse(
      Deno.readTextFileSync(
        new URL("../../panel/messages/tr.json", import.meta.url),
      ),
    ),
  });
  const lcd = IP_TARGETS.find((target) => target.id === "Compartment LCD");
  assert.deepEqual(lcd.groups, ["Compartment LCD"]);
  assert.equal(lcd.label, "Compartment LCD");
  assert.equal(targetLabel(lcd), "Compartment LCD");
});

Deno.test("DeviceMap row names are never translated or normalized", () => {
  const row = { name: "Compartment_Lcd_1" };
  assert.equal(deviceMapName(row), "Compartment_Lcd_1");
  assert.equal(deviceMapName({ name: "<LCD & 2>" }), "<LCD & 2>");
});

Deno.test("changing the operation switch retires switch-derived UI state", () => {
  const before = {
    switchId: local.switchId,
    portText: local.portText,
    protected: local.protected,
    searchingProtected: local.searchingProtected,
    installApk: local.installApk,
    apkPickerOpen: local.apkPickerOpen,
  };
  try {
    local.switchId = "sw1";
    local.portText = "13-23";
    local.protected = { computer: { switchId: "sw1", port: 1 } };
    local.searchingProtected = true;
    local.installApk = true;
    local.apkPickerOpen = true;

    selectAssignmentSwitch("sw2");

    assert.equal(local.switchId, "sw2");
    assert.equal(local.portText, null);
    assert.equal(local.protected, null);
    assert.equal(local.searchingProtected, false);
    assert.equal(local.installApk, false);
    assert.equal(local.apkPickerOpen, false);
  } finally {
    Object.assign(local, before);
  }
});

Deno.test("the operation switch picker is rendered above the port picker", () => {
  const source = Deno.readTextFileSync(
    new URL("../../static/js/views/ip/index.js", import.meta.url),
  );
  const start = source.indexOf("function settingsCard");
  const end = source.indexOf("function factoryResetSelection", start);
  const settingsCard = source.slice(start, end);
  const switchPicker = settingsCard.indexOf("switchArea(plan)");
  const portPicker = settingsCard.indexOf("portArea(data, check");
  assert.ok(switchPicker >= 0, "switch picker is missing from the settings card");
  assert.ok(portPicker >= 0, "port picker is missing from the settings card");
  assert.ok(switchPicker < portPicker, "switch picker must be above ports");
});

Deno.test("an inactive panel port uses the safe switch transition", () => {
  const source = Deno.readTextFileSync(
    new URL("../../static/js/views/ip/index.js", import.meta.url),
  );
  const start = source.indexOf("function togglePort");
  const end = source.indexOf("async function start", start);
  const togglePort = source.slice(start, end);
  assert.match(
    togglePort,
    /selectAssignmentSwitch\(context\.switchId\);\s*local\.portText = String\(number\);/,
  );
  assert.doesNotMatch(togglePort, /local\.switchId\s*=/);
});

Deno.test("only actionable DeviceMap rows enter the APK operation", () => {
  const plan = lcdPlan();
  assert.equal(isCompartmentPlan(plan), true);
  assert.equal(usesPhysicalPortDiscovery(plan), true);
  assert.deepEqual(
    deviceCandidateRows(plan).map((row) => row.name),
    ["Compartment_Lcd_1", "Compartment_Lcd_2"],
  );
  assert.deepEqual(softwareDeviceIds(plan), ["lcd-1", "lcd-2"]);
  assert.deepEqual(
    missingSoftwareRows(plan).map((row) => row.deviceId),
    ["lcd-2"],
  );
});

Deno.test("a firmware reply updates its rows without losing other choices", () => {
  const plan = lcdPlan();
  const software = mergedSoftware(plan, {
    files: {
      "lcd-2": { selected: true, name: "new.apk", size: 4096 },
    },
  });
  assert.equal(software.files["lcd-1"].name, "panel.apk");
  assert.equal(software.files["lcd-2"].name, "new.apk");
});

Deno.test("a per-device LCD source cannot be replaced by a shared override", () => {
  const plan = lcdPlan();
  assert.equal(
    sourceAddress(plan, plan.candidateRows[0], "10.1.1.12"),
    "10.1.1.40",
  );
  assert.equal(
    sourceAddress(
      { sourceMode: "shared" },
      { factoryIp: "10.1.1.12" },
      "10.1.1.15",
    ),
    "10.1.1.15",
  );
});

Deno.test("an LCD bench plan accepts an arbitrary physical PoE port", () => {
  const plan = lcdPlan();
  assert.deepEqual(parsePorts("8", plan.allowedPorts), {
    ports: [8],
    error: "",
  });

  const intercom = parsePorts("8", [13, 14]);
  assert.deepEqual(intercom.ports, []);
  assert.notEqual(intercom.error, "");
});

Deno.test("only physical PoE ports become selectable in LCD bench mode", () => {
  assert.equal(
    portIsSelectable({ number: 8, poe: true, defined: false }, true),
    true,
  );
  assert.equal(
    portIsSelectable({ number: 25, poe: false, defined: true }, true),
    false,
  );
  assert.equal(
    portIsSelectable({ number: 8, poe: true, defined: false }, false),
    false,
  );
  assert.equal(
    portIsSelectable({ number: 13, poe: true, defined: true }, false),
    true,
  );
});

Deno.test("a generic physical plan row explains automatic identity matching", () => {
  const plan = lcdPlan();
  assert.equal(
    planRowStateKey(plan, plan.rows[0]),
    "ipplan.automaticDeviceMatch",
  );
  assert.equal(
    planRowStateKey(
      { assignmentKind: "intercom" },
      { actionable: true, deviceId: "intercom-1" },
    ),
    "ipplan.inThePlan",
  );
});
