#!/usr/bin/env python3
"""Live MQTT subscriber for the monitoring screen."""
from __future__ import annotations

import threading
import time

from .. import settings
from .client import MqttUnavailable, build_client
from .. import i18n


class MqttMonitor:
    """A bounded subscriber for the MQTT monitoring screen.

    Runs when the user opens the screen and presses Start, stops when they
    close it. The message buffer is fixed size (`LIMIT`) so a window left open
    for hours does not fill memory, and payloads are clipped — the stream view
    is a live gauge, not a recording system.
    """

    LIMIT = 300
    PAYLOAD_LIMIT = 400

    def __init__(self):
        self._lock = threading.Lock()
        self._messages: list[dict] = []
        self._counts: dict[str, int] = {}
        self._client = None
        # The slot is RESERVED before any I/O happens (see `start`). The
        # check-then-connect used to release the lock across the broker
        # connection, so two Start clicks landing together both passed the
        # "not running" test and both connected — and the loser's paho
        # client could never be stopped again while its closure went on
        # feeding `_messages`.
        self._starting = False
        self._broker: str | None = None
        self._error: str | None = None
        self._total = 0

    def running(self) -> bool:
        return self._client is not None

    def start(self, broker: str, port: int | None = None,
              topic: str = "#") -> None:
        with self._lock:
            if self._client is not None or self._starting:
                return
            self._starting = True
            self._error = None
        try:
            client = build_client("commissioning_monitor")
        except MqttUnavailable as exc:
            with self._lock:
                # Roll the reservation back: nothing was started, and a
                # stuck `_starting` would refuse every later Start.
                self._error = str(exc)
                self._starting = False
            return

        def on_connect(c, userdata, flags, rc, properties=None):
            c.subscribe(topic)

        def on_message(c, userdata, message):
            try:
                payload = message.payload.decode("utf-8", "replace")
            except Exception:
                payload = i18n.t("telemetry.binaryPayload")
            with self._lock:
                self._total += 1
                self._counts[message.topic] = (
                    self._counts.get(message.topic, 0) + 1)
                self._messages.append({
                    "time": time.time(),
                    "topic": message.topic,
                    "payload": payload[:self.PAYLOAD_LIMIT],
                })
                if len(self._messages) > self.LIMIT:
                    del self._messages[:len(self._messages) - self.LIMIT]

        client.on_connect = on_connect
        client.on_message = on_message
        try:
            client.connect(broker, port or settings.MQTT_PORT, keepalive=15)
            client.loop_start()
        except Exception:
            with self._lock:
                self._error = i18n.t("error.mqttBrokerFailed", broker=broker)
                self._starting = False
            return
        with self._lock:
            # A stop() that arrived while this start was mid-connect has
            # revoked the reservation; installing the client anyway would
            # hand shutdown a subscriber it already believes is gone.
            if not self._starting:
                installed = False
            else:
                self._client, self._broker = client, broker
                self._starting = False
                installed = True
        if not installed:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def stop(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            # Revoke an in-flight start(): its tail checks the reservation
            # before installing, and tears its fresh client down instead.
            self._starting = False
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def state(self) -> dict:
        with self._lock:
            topics = sorted(self._counts.items(), key=lambda x: -x[1])[:20]
            return {
                "running": self._client is not None,
                "broker": self._broker,
                "error": self._error,
                "total": self._total,
                "topics": [{"name": name, "count": count}
                           for name, count in topics],
                "messages": list(reversed(self._messages[-60:])),
            }


MONITOR = MqttMonitor()
