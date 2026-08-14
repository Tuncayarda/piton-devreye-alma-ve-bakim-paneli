#!/usr/bin/env python3
"""Collecting retained messages from the broker.

Two retained sources are read (the same ones device_verify.py uses):

    ALFA/DeviceMap      live state of every device (NoError, Uptime, ...)
    ALFA/AppStatus/#    version + hardware id of devices running an app

This happens ONCE per full scan and the result is shared with every
MQTT-backed device in that scan: 30 broker connections for 30 devices makes
no sense.

If paho-mqtt is missing or the broker is unreachable, nothing is invented —
the devices stay grey and the reason is recorded.
"""
from __future__ import annotations

import json
import threading
import time

from .. import settings
from .. import i18n


class MqttUnavailable(RuntimeError):
    """paho-mqtt is not installed, or the broker could not be reached."""


def build_client(client_id: str):
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        raise MqttUnavailable(
            i18n.t("error.mqttNotInstalled"))
    return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)


def _collect(broker: str, port: int, topic: str, window: float,
             client_id: str, first_only: bool) -> dict:
    """Collect retained messages. With `first_only`, stop at the first one."""
    client = build_client(client_id)
    inbox: dict[str, bytes] = {}
    done = threading.Event()

    def on_connect(c, userdata, flags, rc, properties=None):
        c.subscribe(topic)

    def on_message(c, userdata, message):
        inbox.setdefault(message.topic, message.payload)
        if first_only:
            done.set()

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(broker, port, keepalive=10)
        client.loop_start()
        if first_only:
            done.wait(window)
        else:
            time.sleep(window)
    except Exception as exc:
        raise MqttUnavailable(
            i18n.t("error.mqttConnectFailed",
                   broker=broker, port=port)) from exc
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
    return inbox


def fetch_device_map(broker: str, port: int | None = None,
                     window: float | None = None) -> dict | None:
    """The live ALFA/DeviceMap. None when no message arrives."""
    inbox = _collect(broker, port or settings.MQTT_PORT,
                     settings.MQTT_DEVICE_MAP_TOPIC,
                     window or settings.MQTT_TIMEOUT,
                     "commissioning_devicemap", True)
    for payload in inbox.values():
        try:
            return json.loads(payload)
        except ValueError:
            continue
    return None


def fetch_app_status(broker: str, port: int | None = None,
                     window: float | None = None) -> dict:
    """Application status messages under ALFA/AppStatus/#.

    Returns: {ClientId: payload}
    """
    inbox = _collect(broker, port or settings.MQTT_PORT,
                     f"{settings.MQTT_APP_STATUS_PREFIX}/#",
                     window or settings.MQTT_TIMEOUT,
                     "commissioning_appstatus", False)
    found: dict[str, dict] = {}
    for topic, payload in inbox.items():
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        found[data.get("ClientId") or topic.rsplit("/", 1)[-1]] = data
    return found


def fetch_sip_extensions(broker: str, port: int | None = None,
                         window: float | None = None) -> dict:
    """ALFA/SipPort/<ip> — the SIP extension per device.

        ALFA/SipPort/10.1.1.40  {"SipPort": 6001}

    A Compartment LCD writes its extension to the device log only once at app
    start; when the log buffer wraps the line is gone and the number becomes
    unreadable. The same value sits retained here and can be read without
    touching the device or restarting the app.

    Topic names carry resolved IPs, not templates.

    Returns: {ip: extension}
    """
    inbox = _collect(broker, port or settings.MQTT_PORT,
                     f"{settings.MQTT_SIP_PORT_PREFIX}/#",
                     window or settings.MQTT_TIMEOUT,
                     "commissioning_sipport", False)
    found: dict[str, str] = {}
    for topic, payload in inbox.items():
        ip = topic.rsplit("/", 1)[-1]
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        value = data.get("SipPort") if isinstance(data, dict) else None
        if value not in (None, ""):
            found[ip] = str(value)
    return found
