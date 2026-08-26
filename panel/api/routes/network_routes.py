#!/usr/bin/env python3
"""The computer's own network: what it holds, what it needs, what was added.

Everything a run does automatically is reachable by hand here, plus the one
thing it cannot decide on its own — WHICH adapter. When the computer is on a
foreign network entirely there is no route to follow and the best guess is a
guess; the picker on this screen is the answer to that.
"""
from __future__ import annotations

from ... import network
from ..presenters import inventory_for
from ..response import respond
from .helpers import single


def get_network(query):
    inventory = inventory_for(single(query, "set", 1))
    factory = str(single(query, "factoryIp", "") or "").strip()
    return respond(200, network.state(inventory, {"factoryIp": factory}))


def post_prepare(body):
    """Add the missing addresses now, without waiting for a run."""
    inventory = inventory_for(body.get("set"))
    factory = str(body.get("factoryIp") or "").strip()
    result = network.ensure(inventory, {"factoryIp": factory})
    return respond(200, {**network.state(inventory, {"factoryIp": factory}),
                         "added": result["added"], "failed": result["failed"]})


def post_release(body):
    """Take back the addresses this application added.

    One address when `ip` is given, all of them otherwise. Only addresses this
    process put there can be released: the record is what says so, and nothing
    the panel did not add is ever removed.
    """
    inventory = inventory_for(body.get("set"))
    address = str(body.get("ip") or "").strip()
    released = (1 if network.release(address) else 0) if address \
        else network.release_all()
    return respond(200, {**network.state(inventory), "released": released})


def post_settings(body):
    """Store the adapter choice and prepare it immediately.

    Picking an adapter PREPARES straight away. The panel does not guess which
    cable goes to the switch, so that one click is the only thing it was
    waiting for; making the user press a second button afterwards would be
    asking them to confirm what they just said.

    The prefix, host octet and automatic-enable flag used to be settings. They
    are now fixed backend policy (/24, the default host octet, always enabled),
    so legacy fields are harmlessly ignored.
    """
    inventory = inventory_for(body.get("set"))
    if "adapter" in body:
        result = network.select_adapter(inventory, body.get("adapter"))
    else:
        result = network.ensure(inventory)
    return respond(200, {**network.state(inventory),
                         "added": result["added"], "failed": result["failed"],
                         "released": result.get("released", [])})


GET = {
    "/api/network": get_network,
}

POST = {
    "/api/network/prepare": post_prepare,
    "/api/network/release": post_release,
    "/api/network/settings": post_settings,
}
