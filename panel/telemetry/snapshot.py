#!/usr/bin/env python3
"""One scan's worth of MQTT telemetry."""
from __future__ import annotations

from .. import settings
from .client import (MqttUnavailable, collect_all, parse_app_status,
                     parse_device_map, parse_sip_extensions)
from .. import i18n


class TelemetrySnapshot:
    """The MQTT picture gathered during one scan.

    A non-empty `error` leaves MQTT-backed devices grey with that text as the
    reason. Silently returning an empty dict and marking the devices failed
    would be misleading.
    """

    def __init__(self, broker: str | None):
        self.broker = broker
        self.records: dict[str, dict] = {}      # IP -> DeviceMap record
        self.apps: dict[str, dict] = {}         # ClientId -> AppStatus
        self.sip: dict[str, str] = {}           # IP -> SIP extension
        self.set_no = None
        self.error: str | None = None

    def collect(self, expected_set: int | None = None) -> TelemetrySnapshot:
        if not self.broker:
            self.error = i18n.t("error.piscuNotFound")
            return self
        # ONE connection for all three retained sources. Three used to be
        # opened in sequence with two unconditional full-window sleeps —
        # ~9 s on every scan's critical path for messages that arrive in
        # the first fraction of a second (see client._collect's cutoff).
        try:
            inbox = collect_all(self.broker)
        except MqttUnavailable as exc:
            self.error = str(exc)
            return self
        except Exception:
            self.error = i18n.t("error.mqttUnreachable", broker=self.broker)
            return self
        raw = parse_device_map(inbox)

        if not raw:
            self.error = i18n.t("error.deviceMapNotReceived",
                                topic=settings.MQTT_DEVICE_MAP_TOPIC)
        else:
            for switch in raw.get("Switches") or []:
                self.set_no = switch.get("TrainSet", self.set_no)
                set_no = switch.get("TrainSet", expected_set)
                if switch.get("IP"):
                    self._index(switch["IP"], switch, set_no)
                for device in switch.get("Devices") or []:
                    if device.get("IP"):
                        self._index(device["IP"], device, set_no)
            if (expected_set is not None and self.set_no is not None
                    and str(self.set_no) != str(expected_set)):
                # Another set's telemetry must not leak into this set's rows.
                self.records.clear()
                self.error = i18n.t("error.brokerSetMismatch",
                                    reported=self.set_no,
                                    expected=expected_set)

        self.apps = parse_app_status(inbox)
        self.sip = parse_sip_extensions(inbox)
        return self

    def sip_extension(self, ip: str) -> str:
        """The extension announced for this device under ALFA/SipPort."""
        return self.sip.get(str(ip), "")

    def _index(self, ip, record: dict, set_no) -> None:
        """Index the record under both the template and the resolved IP.

        Addresses in the broker's DeviceMap are TEMPLATES (10.n.1.4) while the
        panel looks a device up by its resolved address (10.1.1.4). Storing
        only the key as received made every lookup miss and dropped every
        MQTT-backed device to red with "not found in telemetry".
        """
        from ..inventory.device_map import resolve_template

        keys = {str(ip)}
        if set_no is not None:
            keys.add(resolve_template(str(ip), set_no))
        for key in keys:
            self.records[key] = record

    def record(self, ip: str) -> dict | None:
        return self.records.get(ip)

    def app_record(self, ip: str, keyword: str) -> dict | None:
        """Match on DeviceIP first; fall back to ClientId when it is absent."""
        for data in self.apps.values():
            if str(data.get("DeviceIP", "")).strip() == ip:
                return data
        wanted = keyword.lower()
        for key, data in self.apps.items():
            if (wanted in str(key).lower()
                    and not str(data.get("DeviceIP", "")).strip()):
                return data
        return None

    def dto(self) -> dict:
        return {"broker": self.broker, "error": self.error,
                "setNo": self.set_no, "recordCount": len(self.records),
                "appCount": len(self.apps)}
