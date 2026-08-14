#!/usr/bin/env python3
"""IP assignment: plan, front panel, diagnostics and the runs."""
from __future__ import annotations

from ... import ip_assign, jobs
from ...inventory import catalog
from ...inventory.device_map import resolve_template
from ..presenters import credentials_for, find_device, inventory_for
from ..response import respond
from ..tasks import factory_reset_task, ip_assign_task
from .helpers import first_switch_id, name_list, single
from ... import i18n

_ONLY_INTERCOM = "error.intercomOnly"


def get_plan(query):
    inventory = inventory_for(single(query, "set", 1))
    # The IP assignment engine supports Intercom only. Without a parameter
    # that fixed scope is used; a different target is rejected outright rather
    # than quietly turned into Intercom.
    names = name_list(single(query, "groups") or single(query, "group", ""))
    groups = ip_assign.resolve_groups(names or ["Intercom"])
    if not groups:
        return respond(400, {"error": i18n.t(_ONLY_INTERCOM)})
    candidates = [device for device in inventory.devices
                  if device.port and any(catalog.group_matches(group, device)
                                         for group in groups)]
    # The plan belongs to whichever switch the target groups' devices are on.
    switch_id = single(query, "switch") or (
        candidates[0].switch_id if candidates
        else first_switch_id(inventory))
    allowed = set(ip_assign.allowed_ports(inventory, switch_id))
    text = single(query, "ports", "")
    if text:
        ports = ip_assign.parse_ports(text, allowed)
    else:
        # Default: only ports that hold a device of the selected groups.
        # Pre-selecting empty ports misleads the user.
        ports = sorted({int(device.port) for device in candidates
                        if device.switch_id == switch_id
                        and str(device.port).isdigit()} & allowed)
    return respond(200, {
        **ip_assign.build_plan(inventory, [g["name"] for g in groups], ports,
                               switch_id),
        "allowedPorts": sorted(allowed),
        # Defaults the UI suggests: the address devices leave the factory on,
        # and the set's own network.
        "factoryIp": ip_assign.factory_ip(inventory),
        "searchNetwork": resolve_template("10.n.1.0", inventory.set_no),
        "searchNetmask": "255.255.255.0",
        # The search area can also be given as a range; the UI should know
        # the limit too (see ip_assign.SEARCH_LIMIT).
        "searchLimit": ip_assign.SEARCH_LIMIT,
        # Because devices all arrive on the same factory address, the run has
        # to flush the ARP cache on every port change. The app is launched
        # elevated, so this is expected; the field is diagnostic only.
        "arpFlush": ip_assign.can_flush_arp(),
        # groupDevices: how many devices of the selected groups sit on that
        # switch. The UI flags a switch with none, so nobody hunts for ports.
        "switches": [{"id": switch.id, "name": switch.name, "ip": switch.ip,
                      "groupDevices": sum(1 for device in candidates
                                          if device.switch_id == switch.id)}
                     for switch in inventory.switches()],
    })


def get_front_panel(query):
    inventory = inventory_for(single(query, "set", 1))
    switch = find_device(inventory,
                         first_switch_id(inventory, single(query, "switch")))
    return respond(200, ip_assign.front_panel(inventory, switch.id,
                                              credentials_for(switch)))


def get_address_map(query):
    # Read-only diagnostics: who is on the candidate addresses. Nothing is
    # written and PoE is untouched, so it does not enter the job queue.
    inventory = inventory_for(single(query, "set", 1))
    switch = find_device(inventory,
                         first_switch_id(inventory, single(query, "switch")))
    groups = [group["name"] for group in ip_assign.resolve_groups(
        [single(query, "group") or "Intercom"])]
    if not groups:
        return respond(400, {
            "error": i18n.t("error.addressMapIntercomOnly")})
    factory = str(single(query, "factoryIp", "") or "").strip()
    if factory and not ip_assign.is_ipv4(factory):
        return respond(400, {"error": i18n.t("error.factoryIpInvalid")})
    return respond(200, ip_assign.address_map(inventory, switch.id, groups,
                                              {"factoryIp": factory}))


def get_protected(query):
    # Every port the run must not touch. The client selects nothing: both the
    # computer's location and the switch-to-switch links come out of the MAC
    # learning tables. A switch that is down fails on its own timeout without
    # holding up the others.
    inventory = inventory_for(single(query, "set", 1))
    return respond(200, ip_assign.protected_ports(
        inventory, credentials_for=credentials_for))


def _search_options(body) -> dict:
    return {
        "factoryIp": str(body.get("factoryIp") or "").strip(),
        "searchNetwork": str(body.get("searchNetwork") or "").strip(),
        "searchNetmask": str(body.get("searchNetmask") or "").strip(),
        # An explicit address range instead of network + mask: the only way to
        # narrow the search when the project netmask is wide (e.g. /8).
        "searchFirst": str(body.get("searchFirst") or "").strip(),
        "searchLast": str(body.get("searchLast") or "").strip(),
    }


def _validate_search(options):
    ip_assign.search_candidates(options["searchNetwork"],
                                options["searchNetmask"],
                                first=options["searchFirst"],
                                last=options["searchLast"])


def post_run(body):
    inventory = inventory_for(body.get("set"))
    switch = find_device(inventory,
                         first_switch_id(inventory, body.get("switch")))
    allowed = set(ip_assign.allowed_ports(inventory, switch.id))
    ports = ip_assign.parse_ports(str(body.get("ports", "")), allowed)
    # Ports the run must not touch. Both are physical facts: the computer is
    # on one port of one switch, and the switches are linked by one port each.
    # Only the ones on the target switch matter to this run.
    #
    # The list is NOT TAKEN FROM THE CLIENT, it is found again as the run
    # starts: the UI's finding may be minutes old and a cable may have moved.
    # Being wrong here means cutting PoE on our own link.
    protected: dict[int, str] = {}
    try:
        for entry in ip_assign.protected_ports(
                inventory, credentials_for=credentials_for)["ports"]:
            if entry["switchId"] == switch.id:
                protected[int(entry["port"])] = entry["reason"]
    except Exception:
        pass
    # If discovery failed (the switch did not answer just then), fall back to
    # the UI's last finding — better than protecting nothing.
    if not protected:
        for entry in (body.get("protected") or []):
            if (isinstance(entry, dict) and entry.get("switchId") == switch.id
                    and str(entry.get("port", "")).isdigit()):
                protected[int(entry["port"])] = str(
                    entry.get("reason") or "protected link")[:80]
    # Checked here as well as in the queue: the user sees the error the moment
    # they press the button, and no dead job is left behind.
    ip_assign.assert_not_protected(ports, protected)
    # Selected groups run in turn, each with its own script. A group without
    # one never enters the queue.
    groups = [group["name"] for group in ip_assign.resolve_groups(
        name_list(body.get("groups") or body.get("group")))]
    if not groups:
        return respond(400, {"error": i18n.t(_ONLY_INTERCOM)})
    missing = ip_assign.groups_without_runner(groups)
    if missing:
        return respond(400, {
            "error": i18n.t("error.noRunnerForGroup",
                            groups=", ".join(missing))})
    # Addressing: the IP devices leave the factory on, and the network to scan
    # for those not found there. The candidate list is not built here, only
    # validated — the run builds it.
    options = {
        **_search_options(body),
        # Cycle power at the end to prove the setting reached flash. Off by
        # default because it lengthens the run (see ip_assign.runner).
        "persistenceCheck": bool(body.get("persistenceCheck")),
    }
    if options["factoryIp"] and not ip_assign.is_ipv4(options["factoryIp"]):
        return respond(400, {"error": i18n.t("error.factoryIpInvalid")})
    try:
        _validate_search(options)
    except ValueError as exc:
        return respond(400, {"error": str(exc)})

    # The title is kept short: it did not fit one line on the queue card and
    # was ellipsised down to "IP ATAMA · YATAKLI_2 · …". Group and port detail
    # already live on the rows and in the phase text.
    job = jobs.Job("ip", i18n.lazy("job.ipAssign", switch=switch.name),
                   inventory.set_no,
                   key=f"ip:{inventory.set_no}:{switch.id}")
    job, is_new = jobs.QUEUE.submit(
        job, ip_assign_task(inventory, switch.id, ports, protected, groups,
                            options))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


def post_factory_reset(body):
    # Test flow: gather the selected devices on the factory address again.
    # Not the run's inverse — a tool for building the starting state.
    inventory = inventory_for(body.get("set"))
    switch = find_device(inventory,
                         first_switch_id(inventory, body.get("switch")))
    allowed = set(ip_assign.allowed_ports(inventory, switch.id))
    ports = ip_assign.parse_ports(str(body.get("ports", "")), allowed)
    groups = [group["name"] for group in ip_assign.resolve_groups(
        name_list(body.get("groups") or body.get("group")))]
    if not groups:
        return respond(400, {"error": i18n.t(_ONLY_INTERCOM)})
    options = _search_options(body)
    if options["factoryIp"] and not ip_assign.is_ipv4(options["factoryIp"]):
        return respond(400, {"error": i18n.t("error.factoryIpInvalid")})
    # The device may not be at its DeviceMap address; as in the run, a search
    # range can be given here too.
    try:
        _validate_search(options)
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    job = jobs.Job("ipfactory",
                   i18n.lazy("job.factoryReset", switch=switch.name,
                             ports=ip_assign.format_ports(ports)),
                   inventory.set_no,
                   key=f"ipfactory:{inventory.set_no}:{switch.id}")
    job, is_new = jobs.QUEUE.submit(
        job, factory_reset_task(inventory, switch.id, ports, groups, options))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


GET = {
    "/api/ip/plan": get_plan,
    "/api/ip/panel": get_front_panel,
    "/api/ip/address-map": get_address_map,
    "/api/ip/protected": get_protected,
}

POST = {
    "/api/ip/run": post_run,
    "/api/ip/factory-reset": post_factory_reset,
}
