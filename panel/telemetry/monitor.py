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
        self._broker: str | None = None
        self._error: str | None = None
        self._total = 0

    def running(self) -> bool:
        return self._client is not None

    def start(self, broker: str, port: int | None = None,
              topic: str = "#") -> None:
        with self._lock:
            if self._client is not None:
                return
            self._error = None
        try:
            client = build_client("commissioning_monitor")
        except MqttUnavailable as exc:
            self._error = str(exc)
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
            self._error = i18n.t("error.mqttBrokerFailed", broker=broker)
            return
        with self._lock:
            self._client, self._broker = client, broker

    def stop(self) -> None:
        with self._lock:
            client, self._client = self._client, None
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
