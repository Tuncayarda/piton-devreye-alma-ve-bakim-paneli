#!/usr/bin/env python3
"""IP assignment: plan, front panel, diagnostics and the runs."""
from __future__ import annotations

from pathlib import Path

from ... import firmware, i18n, ip_assign, jobs, network, settings
from ...inventory import catalog
from ...inventory.device_map import resolve_template
from ...system import files
from ..presenters import (
    credentials_for,
    find_device,
    inventory_for,
    inventory_for_write,
)
from ..response import respond
from ..tasks import factory_reset_task, ip_assign_task, lcd_manual_task
from .helpers import first_switch_id, name_list, single

_ONLY_INTERCOM = "error.intercomOnly"
_INTERCOM = "Intercom"
_COMPARTMENT_LCD = "Compartment LCD"


def _physical_switch(inventory, requested):
    """Resolve the physical switch selected for PoE/MAC operations."""
    switch = find_device(
        inventory, first_switch_id(inventory, requested))
    if switch.type != "Switch":
        raise ValueError(i18n.t("error.notASwitch"))
    return switch


def _assignment_policy(inventory, groups, plan: dict) -> dict:
    """UI policy for the selected assignment runner.

    Compartment LCDs do not share one factory address: their commissioning
    addresses preserve the DeviceMap host octet (10.1.1.40 … .50).  APK
    selections already belong to the firmware subsystem; only their safe
    display fields are copied into the plan, never a filesystem path.
    """
    names = [group["name"] for group in groups]
    lcd_only = names == [_COMPARTMENT_LCD]
    software_rows = (plan.get("candidateRows", [])
                     if lcd_only else plan.get("rows", []))
    device_ids = [row["deviceId"] for row in software_rows
                  if row.get("actionable") and row.get("deviceId")]
    selected = (firmware.selections(device_ids, set_no=inventory.set_no)
                if lcd_only else {})
    files = {
        device_id: {
            "selected": bool(record.get("selected")),
            "name": str(record.get("name") or ""),
            "size": int(record.get("size") or 0),
        }
        for device_id, record in selected.items()
    }
    return {
        "assignmentKind": "compartment-lcd" if lcd_only else "intercom",
        "sourceMode": "perDevice" if lcd_only else "shared",
        # Both targets can be put back where they started, but the two mean
        # different things and the screen has to say which. An Intercom goes
        # to ONE shared factory address; a Compartment LCD keeps its own host
        # octet and goes back to the set-1 form of it (10.1.1.40, .41, ...).
        "factoryResetSupported": names in ([_INTERCOM], [_COMPARTMENT_LCD]),
        "factoryResetKind": ("perDevice" if lcd_only else "shared"),
        # One display, one port, one address the operator types. Only the
        # Android flow can do this: it proves identity from the switch MAC
        # table rather than from what the device claims about itself.
        "manualAssignSupported": lcd_only,
        "software": {
            "supported": lcd_only,
            "extension": "apk" if lcd_only else "bin",
            "files": files,
        },
    }


def get_plan(query):
    inventory = inventory_for(single(query, "set", 1))
    # Without a parameter the established Intercom scope is used. A named
    # target is never quietly changed into another device group.
    names = name_list(single(query, "groups") or single(query, "group", ""))
    groups = ip_assign.resolve_groups(names or ["Intercom"])
    if not groups:
        return respond(400, {"error": i18n.t(_ONLY_INTERCOM)})
    candidates = [device for device in inventory.devices
                  if device.port and any(catalog.group_matches(group, device)
                                         for group in groups)]
    # The plan belongs to whichever switch the target groups' devices are on.
    requested_switch_id = single(query, "switch") or (
        candidates[0].switch_id if candidates
        else first_switch_id(inventory))
    switch = _physical_switch(inventory, requested_switch_id)
    device_switch_id = ip_assign.device_switch_for(
        inventory, groups, switch.id)
    lcd_only = [group["name"] for group in groups] == [_COMPARTMENT_LCD]
    # LCD test wiring is physical: any PoE port can carry any one of the
    # canonical displays.  The device identity/IP is discovered later from
    # the server-side candidate map and proved by the selected switch's MAC
    # table.  Intercom port semantics remain DeviceMap-bound.
    allowed = (set(range(1, settings.SWITCH_POE_PORTS + 1)) if lcd_only
               else set(ip_assign.devices_by_port(
                   inventory, groups, device_switch_id)))
    text = single(query, "ports", "")
    if text:
        ports = ip_assign.parse_ports(text, allowed)
    else:
        # Default: only ports that hold a device of the selected groups.
        # Pre-selecting empty ports misleads the user.
        ports = sorted({int(device.port) for device in candidates
                        if device.switch_id == device_switch_id
                        and str(device.port).isdigit()} & allowed)
    try:
        target_prefix = ip_assign.parse_prefix(single(query, "mask", ""))
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    plan = ip_assign.build_plan(inventory, [g["name"] for g in groups], ports,
                                switch.id, device_switch_id,
                                target_prefix=target_prefix)
    factory = ip_assign.factory_ip(inventory)
    return respond(200, {
        **plan,
        **_assignment_policy(inventory, groups, plan),
        "allowedPorts": sorted(allowed),
        # Defaults the UI suggests: the address devices leave the factory on,
        # and the set's own network.
        "factoryIp": factory,
        "searchNetwork": resolve_template("10.n.1.0", inventory.set_no),
        "searchNetmask": "255.255.255.0",
        # The search area can also be given as a range; the UI should know
        # the limit too (see ip_assign.SEARCH_LIMIT).
        "searchLimit": ip_assign.SEARCH_LIMIT,
        # The mask the run writes with the new address. The project's own
        # when it states one (Gaziray spans five /24s and needs a /16),
        # otherwise the system default; the bounds are what the server will
        # accept.
        "defaultTargetPrefix": ip_assign.effective_prefix(),
        "minTargetPrefix": ip_assign.MIN_TARGET_PREFIX,
        "maxTargetPrefix": ip_assign.MAX_TARGET_PREFIX,
        # The image queued for "flash before assigning", if any. Name and
        # size only — the path stays on this side (see ip_assign.preflash).
        "preflashFile": ip_assign.preflash_file(),
        # Because devices all arrive on the same factory address, the run has
        # to flush the ARP cache on every port change. The app is launched
        # elevated, so this is expected; the field is diagnostic only.
        "arpFlush": ip_assign.can_flush_arp(),
        # Can this computer reach the devices at all?
        #
        # The field case this answers: the operator picks set 8, and every
        # device is still on its 10.1.1.x factory address. Two networks have
        # to be reachable, not one — and if the panel cannot tell which cable
        # goes to the switch it adds neither, silently, and the run then fails
        # on every port. That was only visible in the job queue, after the
        # run had started. Now the screen knows before the button is pressed.
        "network": network.readiness(inventory, {"factoryIp": factory}),
        # groupDevices: how many devices of the selected groups sit on that
        # switch. The UI flags a switch with none, so nobody hunts for ports.
        "switches": [{
            "id": candidate_switch.id,
            "name": candidate_switch.name,
            "ip": candidate_switch.ip,
            # For an LCD-only override every physical switch can execute the
            # one canonical DeviceMap layout.  This count therefore describes
            # the rows that would be offered after choosing that switch, not
            # merely where DeviceMap nests them.
            "groupDevices": sum(
                1 for device in candidates
                if device.switch_id == ip_assign.device_switch_for(
                    inventory, groups, candidate_switch.id)),
        } for candidate_switch in inventory.switches()],
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
    if groups != [_INTERCOM]:
        return respond(400, {
            "error": i18n.t("error.addressMapIntercomOnly")})
    factory = str(single(query, "factoryIp", "") or "").strip()
    if factory and not ip_assign.is_ipv4(factory):
        return respond(400, {"error": i18n.t("error.factoryIpInvalid")})
    # "Who is on which address" is the first thing reached for when a run
    # found nothing, so it must not be the one place that still cannot see
    # the factory network. No job here, so nothing to report onto — the
    # Network screen shows what was added.
    network.ensure(inventory, {"factoryIp": factory})
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


def _protected_on(inventory, switch, body) -> dict[int, str]:
    """Ports this run must not touch, on the selected switch.

    Both are physical facts: the computer is on one port of one switch, and
    the switches are linked by one port each.

    The list is NOT TAKEN FROM THE CLIENT, it is found again as the run
    starts: the UI's finding may be minutes old and a cable may have moved.
    Being wrong here means cutting PoE on our own link.
    """
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
        for entry in ((body or {}).get("protected") or []):
            if (isinstance(entry, dict) and entry.get("switchId") == switch.id
                    and str(entry.get("port", "")).isdigit()):
                protected[int(entry["port"])] = str(
                    entry.get("reason") or "protected link")[:80]
    return protected


def _set_addresses(inventory, set_no: int) -> list[str]:
    """Every device address of one set — what a transfer has to reach.

    `network.ensure` reduces these to their /24s, so handing it the whole
    list is how the computer gets an address on the network the devices are
    being moved out of (or into) without anybody typing one.
    """
    if not set_no or int(set_no) == int(inventory.set_no):
        return []
    return [resolve_template(device.ip_template, int(set_no))
            for device in inventory.devices if device.ip_template]


def _addressing_options(body) -> dict:
    """The mask written with the new address.

    A run option rather than a setting: the project is a /24 world, but a
    display commissioned on a bench is sometimes given a /8 so it stays
    reachable while the rest of the train is still being addressed.
    """
    return {"targetPrefix": ip_assign.parse_prefix(body.get("targetMask"))}


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
    inventory = inventory_for_write(body.get("set"))
    switch = _physical_switch(inventory, body.get("switch"))
    # Resolve the operation before accepting a port.  LCD-only runs may use a
    # different physical switch while their immutable device/id/IP/port map is
    # taken from DeviceMap's one canonical LCD switch.
    groups = [group["name"] for group in ip_assign.resolve_groups(
        name_list(body.get("groups") or body.get("group")))]
    if not groups:
        return respond(400, {"error": i18n.t(_ONLY_INTERCOM)})
    missing = ip_assign.groups_without_runner(groups)
    if missing:
        return respond(400, {
            "error": i18n.t("error.noRunnerForGroup",
                            groups=", ".join(missing))})
    resolved_groups = ip_assign.resolve_groups(groups)
    device_switch_id = ip_assign.device_switch_for(
        inventory, resolved_groups, switch.id)
    lcd_only = groups == [_COMPARTMENT_LCD]
    allowed = (set(range(1, settings.SWITCH_POE_PORTS + 1)) if lcd_only
               else set(ip_assign.devices_by_port(
                   inventory, resolved_groups, device_switch_id)))
    ports = ip_assign.parse_ports(str(body.get("ports", "")), allowed)
    protected = _protected_on(inventory, switch, body)
    # Checked here as well as in the queue: the user sees the error the moment
    # they press the button, and no dead job is left behind.
    ip_assign.assert_not_protected(ports, protected)
    install_apk = body.get("installApk") is True
    if body.get("preflash") is True and _INTERCOM not in groups:
        return respond(400, {"error": i18n.t("error.firmwareTypeUnsupported")})
    if install_apk and _COMPARTMENT_LCD not in groups:
        return respond(400, {"error": i18n.t("error.firmwareTypeUnsupported")})
    # Addressing: the IP devices leave the factory on, and the network to scan
    # for those not found there. The candidate list is not built here, only
    # validated — the run builds it.
    try:
        addressing = _addressing_options(body)
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    options = {
        **_search_options(body),
        # The mask written with the new address.
        **addressing,
        # Flash the device before writing its address. For intercoms whose
        # firmware is too old to report itself correctly; the only moment one
        # is alone on the wire is inside the run (see ip_assign.preflash).
        **ip_assign.preflash_options(body),
        # APK paths never come from the client. The selected file is looked up
        # per set/device by the LCD runner in panel.firmware.
        "installApk": install_apk,
    }
    if options["factoryIp"] and not ip_assign.is_ipv4(options["factoryIp"]):
        return respond(400, {"error": i18n.t("error.factoryIpInvalid")})
    try:
        _validate_search(options)
        # The file is checked NOW, not when the first port is reached: a moved
        # or unreadable file found eight ports into a run is found at the
        # worst possible moment.
        ip_assign.validate_preflash(options)
        if install_apk:
            # Until a physical port is isolated we intentionally do not know
            # which canonical LCD is connected to it.  Validate every
            # possible server-side candidate now; the runtime installs only
            # the file belonging to the identity it actually proves.
            by_port = ip_assign.devices_by_port(
                inventory, resolved_groups, device_switch_id)
            lcd_devices = [device for device, group_name in by_port.values()
                           if group_name == _COMPARTMENT_LCD]
            if not lcd_devices:
                raise ValueError(i18n.t("error.firmwareNotDefined"))
            for device in lcd_devices:
                record = firmware.selection_for(
                    device.id, set_no=inventory.set_no)
                if not record.get("selected"):
                    raise ValueError(i18n.t("error.noFileForDevice"))
                target, _size = firmware.validate_file(record.get("path", ""))
                if Path(target).suffix.lower() != ".apk":
                    raise ValueError(i18n.t("error.apkInvalid"))
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


def _lcd_factory_reset(inventory, switch, body, groups):
    """Put the selected displays back on their set-1 addresses.

    Nothing like the Intercom flow, and the difference is the whole point of
    the separate path: intercoms are gathered onto ONE shared factory address
    over HTTP with PoE untouched, while a Compartment LCD keeps its own host
    octet and goes back to 10.1.1.40, .41, ... — the layout it left the
    factory in.  That is the ordinary Android run with the two sets the other
    way round, so it runs on exactly the same isolated-port, MAC-proved
    machinery instead of a second implementation.
    """
    allowed = set(range(1, settings.SWITCH_POE_PORTS + 1))
    ports = ip_assign.parse_ports(str(body.get("ports", "")), allowed)
    protected = _protected_on(inventory, switch, body)
    ip_assign.assert_not_protected(ports, protected)
    try:
        # `set` is where the displays are NOW; set 1 is where they go.
        source_set = ip_assign.parse_set(body.get("sourceSet"))
        options = {
            "targetPrefix": ip_assign.parse_prefix(body.get("targetMask")),
            "sourceSet": source_set or inventory.set_no,
            "targetSet": 1,
            "extraAddresses": _set_addresses(inventory, source_set),
        }
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    job = jobs.Job("ipfactory",
                   i18n.lazy("job.lcdFactoryReset", switch=switch.name,
                             ports=ip_assign.format_ports(ports)),
                   inventory.set_no,
                   key=f"ipfactory:{inventory.set_no}:{switch.id}")
    job, is_new = jobs.QUEUE.submit(
        job, ip_assign_task(inventory, switch.id, ports, protected, groups,
                            options))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


def post_factory_reset(body):
    # Test flow: gather the selected devices on the factory address again.
    # Not the run's inverse — a tool for building the starting state.
    # Here `set` means the set whose CURRENT addresses are searched.  For the
    # "external set" choice the client sends that entered set number; the
    # destination remains the fixed/selected factory address.  It is strict so
    # a mistyped external set can never fall back to set 1.
    inventory = inventory_for_write(body.get("set"))
    groups = [group["name"] for group in ip_assign.resolve_groups(
        name_list(body.get("groups") or body.get("group")))]
    # A display goes back to ITS OWN set-1 address, which is the ordinary
    # Android run with the two sets swapped — a different operation from the
    # Intercom one below, not a mode of it.
    if groups == [_COMPARTMENT_LCD]:
        return _lcd_factory_reset(
            inventory, _physical_switch(inventory, body.get("switch")), body,
            groups)
    switch = find_device(inventory,
                         first_switch_id(inventory, body.get("switch")))
    allowed = set(ip_assign.allowed_ports(inventory, switch.id))
    ports = ip_assign.parse_ports(str(body.get("ports", "")), allowed)
    if groups != [_INTERCOM]:
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


def post_lcd_assign(body):
    """One display, one port, one address the operator typed.

    Deliberately not part of `post_run`: that endpoint's whole contract is
    "DeviceMap decides which address goes where, the client only picks
    ports". Here the destination address IS the request, so it gets its own
    endpoint, its own validation and its own job, and it stays limited to the
    one device family whose identity can be proved from the switch instead of
    from what the device says about itself.
    """
    inventory = inventory_for_write(body.get("set"))
    switch = _physical_switch(inventory, body.get("switch"))
    groups = [group["name"] for group in ip_assign.resolve_groups(
        name_list(body.get("groups") or body.get("group"))
        or [_COMPARTMENT_LCD])]
    if groups != [_COMPARTMENT_LCD]:
        return respond(400, {"error": i18n.t("error.lcdManualOnly")})
    allowed = set(range(1, settings.SWITCH_POE_PORTS + 1))
    ports = ip_assign.parse_ports(str(body.get("port", "")), allowed)
    if len(ports) != 1:
        return respond(400, {"error": i18n.t("error.lcdManualOnePort")})
    protected = _protected_on(inventory, switch, body)
    try:
        ip_assign.assert_not_protected(ports, protected)
        target_ip = str(body.get("targetIp") or "").strip()
        if not ip_assign.is_ipv4(target_ip):
            raise ValueError(i18n.t("error.lcdManualTargetInvalid"))
        options = {
            "targetIp": target_ip,
            "targetPrefix": ip_assign.parse_prefix(body.get("targetMask")),
            # The computer needs a route to the address it is about to write,
            # otherwise the verification read cannot reach the display.
            "extraAddresses": [target_ip],
        }
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    job = jobs.Job("ip", i18n.lazy("job.lcdManualAssign", port=ports[0],
                                   ip=target_ip),
                   inventory.set_no,
                   key=f"ip:{inventory.set_no}:{switch.id}")
    job, is_new = jobs.QUEUE.submit(
        job, lcd_manual_task(inventory, switch.id, ports[0], protected,
                             options))
    return respond(200 if is_new else 202,
                   {**job.dto(rows=False), "new": is_new})


def post_preflash_file(body):
    """Choose (or forget) the image installed before an address is written.

    The path comes from the OPERATING SYSTEM'S dialog, never from the client:
    the browser does not reveal a real path and the user should not have to
    type one. Only the name and the size travel back.
    """
    if body.get("clear"):
        ip_assign.forget_preflash_file()
        return respond(200, {"preflashFile": ip_assign.preflash_file()})
    try:
        chosen = files.pick_file(i18n.t("ip.preflashFile"), ("bin",))
    except RuntimeError as exc:
        return respond(500, {"error": str(exc)})
    if not chosen:
        return respond(200, {"cancelled": True,
                             "preflashFile": ip_assign.preflash_file()})
    try:
        ip_assign.choose_preflash_file(chosen)
    except ValueError as exc:
        return respond(400, {"error": str(exc)})
    return respond(200, {"preflashFile": ip_assign.preflash_file()})


GET = {
    "/api/ip/plan": get_plan,
    "/api/ip/panel": get_front_panel,
    "/api/ip/address-map": get_address_map,
    "/api/ip/protected": get_protected,
}

POST = {
    "/api/ip/run": post_run,
    "/api/ip/factory-reset": post_factory_reset,
    "/api/ip/lcd-assign": post_lcd_assign,
    "/api/ip/preflash-file": post_preflash_file,
}
