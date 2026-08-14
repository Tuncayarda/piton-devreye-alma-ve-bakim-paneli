#!/usr/bin/env python3
"""The PISCU/PBX screen and the live MQTT monitor."""
from __future__ import annotations

from ... import telemetry
from ..presenters import inventory_for, piscu_body
from ..response import respond
from .helpers import single
from ... import i18n


def get_piscu(query):
    return respond(200, piscu_body(inventory_for(single(query, "set", 1))))


def get_mqtt(query):
    return respond(200, telemetry.MONITOR.state())


def post_mqtt_start(body):
    inventory = inventory_for(body.get("set"))
    broker = inventory.piscu_ip()
    if not broker:
        return respond(400, {"error": i18n.t("error.piscuAddressNotFound")})
    telemetry.MONITOR.start(broker)
    return respond(200, telemetry.MONITOR.state())


def post_mqtt_stop(body):
    telemetry.MONITOR.stop()
    return respond(200, telemetry.MONITOR.state())


GET = {
    "/api/piscu": get_piscu,
    "/api/mqtt": get_mqtt,
}

POST = {
    "/api/mqtt/start": post_mqtt_start,
    "/api/mqtt/stop": post_mqtt_stop,
}
