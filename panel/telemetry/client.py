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
import uuid

from .. import settings
from .. import i18n

# What makes THIS panel's broker sessions its own. MQTT keys a session by
# client id, and the broker answers a duplicate id by evicting the session
# that holds it — so with the ids fixed ("commissioning_devicemap", ...),
# two panels on one bench disconnected each other mid-collect and each saw
# a scan that randomly came back empty. The suffix is drawn once per
# process: every reconnect of one panel keeps reusing its own session, and
# the readable prefix still says in the broker's log who is asking why.
_INSTANCE = uuid.uuid4().hex[:8]


class MqttUnavailable(RuntimeError):
    """paho-mqtt is not installed, or the broker could not be reached."""


def build_client(client_id: str):
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        raise MqttUnavailable(
            i18n.t("error.mqttNotInstalled"))
    return mqtt.Client(CallbackAPIVersion.VERSION2,
                       client_id=f"{client_id}_{_INSTANCE}")


# How long the inbox may be QUIET before the collection is called complete.
# Retained messages are not a stream: the broker delivers every one it holds
# in a burst right after the subscription is acknowledged, so once the first
# has arrived, a third of a second of silence means the burst is over. The
# full window is only ever waited out when NOTHING arrives — and that case
# is bounded by the window, exactly as before.
IDLE_CUTOFF = 0.3
# And how long an acknowledged, EMPTY subscription is given before "there is
# nothing retained here" is believed. Emptiness has no burst to end.
EMPTY_GRACE = 1.0


def _collected(now: float, deadline: float, wanted: int, count: int,
               last: float, acked: int, acked_at: float) -> bool:
    """Is the retained collection over? Pure, so it can be tested alone.

    Over when the window runs out; when every subscription is acknowledged
    AND something arrived AND the inbox has been quiet for IDLE_CUTOFF (the
    retained burst is delivered right after each SUBACK, so all-acked +
    quiet means every burst has ended, not merely the first topic's); or
    when every subscription is acknowledged, nothing at all arrived, and
    EMPTY_GRACE has passed since the last SUBACK — emptiness has no burst
    to end, so it gets a floor instead.
    """
    if now >= deadline:
        return True
    if acked < wanted:
        return False
    if count:
        return now - last >= IDLE_CUTOFF
    return bool(acked_at) and now - acked_at >= EMPTY_GRACE


def _collect(broker: str, port: int, topics, window: float,
             client_id: str) -> dict:
    """Collect retained messages from one or more topics, one connection.

    A snapshot used to open THREE connections and sleep two full windows
    unconditionally — ~9 s on the critical path of every scan, measured in
    the field, for messages that arrive in the first fraction of a second.
    One client subscribes to everything at once now, and the wait ends when
    the retained burst does (IDLE_CUTOFF above).
    """
    client = build_client(client_id)
    inbox: dict[str, bytes] = {}
    lock = threading.Lock()
    # `acked` COUNTS subscriptions; `acked_at` is when the LAST one landed.
    # A timestamp alone let the cutoff fire after the first topic's burst
    # while a second subscription was still unacknowledged — its retained
    # set had not even been requested yet.
    marks = {"last": 0.0, "acked": 0, "acked_at": 0.0}
    wanted = [topics] if isinstance(topics, str) else list(topics)

    def on_connect(c, userdata, flags, rc, properties=None):
        for topic in wanted:
            c.subscribe(topic)

    def on_subscribe(c, userdata, mid, reason_codes, properties=None):
        with lock:
            marks["acked"] += 1
            marks["acked_at"] = time.monotonic()

    def on_message(c, userdata, message):
        with lock:
            inbox.setdefault(message.topic, message.payload)
            marks["last"] = time.monotonic()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        client.connect(broker, port, keepalive=10)
        client.loop_start()
        deadline = time.monotonic() + window
        while True:
            now = time.monotonic()
            with lock:
                snapshot = (len(inbox), marks["last"], marks["acked"],
                            marks["acked_at"])
            if _collected(now, deadline, len(wanted), *snapshot):
                break
            time.sleep(0.05)
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


def parse_device_map(inbox: dict) -> dict | None:
    """The DeviceMap payload out of a collected inbox, or None."""
    for topic, payload in inbox.items():
        if topic != settings.MQTT_DEVICE_MAP_TOPIC:
            continue
        try:
            return json.loads(payload)
        except ValueError:
            continue
    return None


def parse_app_status(inbox: dict) -> dict:
    """{ClientId: payload} for every ALFA/AppStatus message in the inbox."""
    found: dict[str, dict] = {}
    prefix = settings.MQTT_APP_STATUS_PREFIX + "/"
    for topic, payload in inbox.items():
        if not topic.startswith(prefix):
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        found[data.get("ClientId") or topic.rsplit("/", 1)[-1]] = data
    return found


def parse_sip_extensions(inbox: dict) -> dict:
    """{ip: extension} for every ALFA/SipPort message in the inbox."""
    found: dict[str, str] = {}
    prefix = settings.MQTT_SIP_PORT_PREFIX + "/"
    for topic, payload in inbox.items():
        if not topic.startswith(prefix):
            continue
        ip = topic.rsplit("/", 1)[-1]
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        value = data.get("SipPort") if isinstance(data, dict) else None
        if value not in (None, ""):
            found[ip] = str(value)
    return found


def collect_all(broker: str, port: int | None = None,
                window: float | None = None) -> dict:
    """Every retained source a snapshot needs, over ONE connection.

    Raises MqttUnavailable when the broker cannot be reached at all; a
    reachable broker with nothing retained returns an empty inbox, which
    the parsers above turn into their own "nothing there" answers.
    """
    return _collect(broker, port or settings.MQTT_PORT,
                    [settings.MQTT_DEVICE_MAP_TOPIC,
                     f"{settings.MQTT_APP_STATUS_PREFIX}/#",
                     f"{settings.MQTT_SIP_PORT_PREFIX}/#"],
                    window or settings.MQTT_TIMEOUT,
                    "commissioning_snapshot")
