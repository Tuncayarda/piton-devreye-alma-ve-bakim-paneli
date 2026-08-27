#!/usr/bin/env python3
"""The one call the rest of the panel makes: "make these devices reachable".

`ensure()` is deliberately quiet and deliberately honest. Quiet, because a
run must not stop to ask permission for a step the user cannot evaluate
anyway — they asked for an IP assignment, and reaching the devices is part of
doing that. Honest, because it reports every address it added: the caller
turns that into a queue row, so a change to the machine's network is never
invisible.

It never raises. An operation that could not be prepared is still worth
attempting — the computer may be reachable by a route this module cannot see —
and the failure it then hits is a better error message than anything that
could be guessed here.
"""
from __future__ import annotations

import json
import platform
import threading

from .. import i18n, settings
from ..inventory.device_map import Inventory
from . import adapters as adapter_module
from . import aliases, commands, planning

_LOCK = threading.RLock()

# The operator only chooses the physical adapter.  The address shape is part of
# the commissioning protocol, not a preference: every alias is a /24 and uses
# the existing high host-octet default.  Keep the fixed values in the DTO for
# older frontends which still read them, but never load overrides from disk.
DEFAULTS = {"adapter": "", "octet": planning.DEFAULT_HOST_OCTET,
            "prefix": planning.DEFAULT_PREFIX, "enabled": True}


def preferences() -> dict:
    """The adapter choice, plus the fixed address policy for the DTO."""
    try:
        raw = json.loads(
            settings.network_settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    values = dict(DEFAULTS)
    if isinstance(raw, dict) and isinstance(raw.get("adapter"), str):
        values["adapter"] = raw["adapter"]
    return values


def save_preferences(values: dict) -> dict:
    """Store only the adapter choice; address policy is deliberately fixed.

    RAISES OSError when the choice cannot be written. It used to be swallowed,
    and the cost of that was a screen saying the interface had been chosen
    while nothing had been saved: the next start asked again, with nothing on
    screen to explain why. Choosing the adapter is the one thing the panel
    cannot work out for itself, so losing that answer quietly is the worst
    way to lose it.
    """
    with _LOCK:
        current = preferences()
        adapter = (values or {}).get("adapter", current["adapter"])
        if not isinstance(adapter, str):
            adapter = current["adapter"]
        path = settings.network_settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"adapter": adapter}, indent=2),
                        encoding="utf-8")
        return preferences()


def _known_networks(found, chosen, pinned: str):
    """Networks which settle whether the *chosen* adapter is ready.

    With an explicit choice, an address on another adapter is not proof of
    readiness.  This distinction is what makes changing en3 -> en6 work: an
    application alias left on en3 must not suppress the /24 alias on en6.
    Automatic selection still considers the whole machine, as before.
    """
    if pinned and chosen is not None:
        return chosen.networks
    return adapter_module.local_networks(found)


def _search_addresses(options: dict | None) -> list[str]:
    """Addresses an operation names but the open set does not contain.

    Two sources. The IP screen's search fields, where only the ends matter —
    `required_networks` turns each into its /24 and a range spanning two
    networks needs both. And `extraAddresses`, which a set transfer fills with
    the addresses of the set the devices are being moved out of: without a
    route there the run cannot see the devices it is meant to move, which is
    the exact failure this whole package exists to remove.
    """
    options = options or {}
    named = [str(options.get(name) or "").strip()
             for name in ("searchNetwork", "searchFirst", "searchLast")
             if str(options.get(name) or "").strip()]
    extra = [str(address or "").strip()
             for address in (options.get("extraAddresses") or [])
             if str(address or "").strip()]
    return list(dict.fromkeys(named + extra))


def _factory_ip(options: dict | None) -> str:
    return (str((options or {}).get("factoryIp") or "").strip()
            or settings.FACTORY_IP)


def _targets(inventory: Inventory, factory_ip: str) -> list[str]:
    """Addresses that identify the right adapter, most telling first.

    The factory network leads: every device arrives on 10.1.1.12 and, once
    the panel has run here before, its own 10.1.1.225 is on that same adapter.
    The switches come next — an adapter already inside the set's network is
    just as certain a match.
    """
    return [factory_ip] + [switch.ip for switch in inventory.switches()]


def state(inventory: Inventory, options: dict | None = None) -> dict:
    """What the Network screen shows: adapters, what is needed, what was
    added.

    Reads only. The same computation `ensure` acts on, so the screen and the
    run can never disagree about what is missing.
    """
    values = preferences()
    found = adapter_module.list_adapters()
    factory = _factory_ip(options)
    chosen = adapter_module.choose(found, _targets(inventory, factory),
                                   override=values["adapter"])
    required = planning.required_networks(
        inventory, factory_ip=factory, extra=_search_addresses(options),
        prefix=planning.DEFAULT_PREFIX,
        known=_known_networks(found, chosen, values["adapter"]))
    base = planning.network_of(factory, planning.DEFAULT_PREFIX)
    return {
        "supported": commands.supported(),
        "system": platform.system(),
        # The address the screen names when it explains why any of this is
        # needed. From here rather than written into the page, so the two can
        # never say different things.
        "factoryIp": factory,
        # The address the panel gives itself on the factory network — the
        # 10.1.1.225/24 the user should be able to read off the screen rather
        # than work out from an octet field.
        "baseAddress": (f"{base.network_address + values['octet']}"
                        f"/{planning.DEFAULT_PREFIX}" if base else ""),
        "setNo": inventory.set_no,
        "adapters": [adapter.dto() for adapter in found],
        "adapter": chosen.dto() if chosen else None,
        # No adapter and nothing pinned: the panel will not guess, so the
        # screen has to ask. Told apart from "this machine has no adapter at
        # all", which nothing on screen can fix.
        "needsAdapter": chosen is None and bool(adapter_module.usable(found)),
        "preferences": values,
        "required": [entry.dto() for entry in required],
        "aliases": aliases.active(),
    }


def readiness(inventory: Inventory, options: dict | None = None) -> dict:
    """Can this computer reach the devices at all? The short answer.

    `state()` is what the Network screen draws; this is the same computation
    reduced to what another screen needs in order to say "do not press that
    button yet".

    The distinction that matters is between MISSING and CANNOT:

    * `missing` — networks the computer is not in. Nothing to warn about: the
      run calls `ensure` before its first port and adds them itself.
    * `needsAdapter` — the panel will not guess which cable goes to the
      switch, and nobody has told it (see `adapters.choose`). Then nothing
      gets added, and the run fails on every port with "device not found" —
      which is exactly what this exists to prevent somebody discovering
      halfway through a train.
    """
    found = adapter_module.list_adapters()
    values = preferences()
    factory = _factory_ip(options)
    chosen = adapter_module.choose(found, _targets(inventory, factory),
                                   override=values["adapter"])
    required = planning.required_networks(
        inventory, factory_ip=factory, extra=_search_addresses(options),
        prefix=planning.DEFAULT_PREFIX,
        known=_known_networks(found, chosen, values["adapter"]))
    needs_adapter = chosen is None and bool(adapter_module.usable(found))
    return {
        "supported": commands.supported(),
        "adapter": chosen.name if chosen else "",
        "needsAdapter": needs_adapter,
        "missing": [str(entry.network) for entry in required],
        "factoryIp": factory,
    }


def ensure(inventory: Inventory, options: dict | None = None,
           emit=None) -> dict:
    """Add whatever addresses this operation needs. Never raises.

    Returns {"added": [...], "failed": [...], "required": [...]}. `emit(text)`
    is called once per address added, so a run can put it on the queue.
    """
    # Adapter choice, reachability calculation and the writes based on that
    # calculation are one transaction.  A scan job may call ``ensure`` while
    # the Network screen changes en3 -> en6 on another thread; releasing the
    # lock between those steps lets the stale scan add an alias back to en3
    # after the selection has already migrated it.  ``select_adapter`` calls
    # this function while holding the same RLock, so the nested acquisition is
    # deliberate.
    with _LOCK:
        return _ensure_locked(inventory, options, emit)


def _ensure_locked(inventory: Inventory, options: dict | None = None,
                   emit=None) -> dict:
    """Implementation of :func:`ensure`; caller holds ``_LOCK``."""
    result = {"added": [], "failed": [], "required": [], "needsAdapter": False}
    values = preferences()
    # `aliases.WRITES_ALLOWED` is checked here as well as at the point of the
    # write, so a switched-off run reports nothing rather than a list of
    # identical failures (see the note on that flag).
    if not commands.supported() or not aliases.WRITES_ALLOWED:
        return result
    factory = _factory_ip(options)
    try:
        found = adapter_module.list_adapters()
        adapter = adapter_module.choose(found, _targets(inventory, factory),
                                        override=values["adapter"])
        required = planning.required_networks(
            inventory, factory_ip=factory, extra=_search_addresses(options),
            prefix=planning.DEFAULT_PREFIX,
            known=_known_networks(found, adapter, values["adapter"]))
    except Exception as exc:
        result["failed"].append({"network": "", "error": _short(exc)})
        return result

    result["required"] = [entry.dto() for entry in required]
    if not required:
        return result
    if adapter is None:
        # NOT a failure entry. The panel refuses to guess which cable goes to
        # the switch, and `needsAdapter` already says so in a form the screen
        # and the job queue can put into the user's own language. Adding it to
        # `failed` as well printed a raw English "no adapter" underneath the
        # Turkish question that was already on screen — twice said, once
        # untranslated.
        result["needsAdapter"] = bool(adapter_module.usable(found))
        return result

    # Addresses already spoken for: DeviceMap's own plan, the factory address,
    # and whatever this computer already holds.
    taken = planning.occupied(inventory, factory)
    taken |= adapter_module.local_addresses(found)
    taken |= {entry.get("ip", "") for entry in aliases.active()}

    for entry in required:
        try:
            address = planning.choose_host(entry.network, taken,
                                           octet=planning.DEFAULT_HOST_OCTET)
            record = aliases.add(adapter.handle, address,
                                 entry.network.prefixlen,
                                 adapter_name=adapter.name)
        except Exception as exc:
            result["failed"].append({"network": str(entry.network),
                                     "error": _short(exc)})
            continue
        taken.add(address)
        result["added"].append(record)
        if emit:
            emit(f"[network] {address}/{entry.network.prefixlen} "
                 f"added to {adapter.name}")
    return result


def select_adapter(inventory: Inventory, name: str,
                   options: dict | None = None) -> dict:
    """Validate and apply an adapter choice, moving only our own aliases.

    The validation happens before any address is removed.  When the preference
    really changes, aliases owned by this process on other adapters are removed
    and ``ensure`` recreates the required /24 aliases on the new adapter.  Host
    addresses which the panel did not add are never candidates for removal.
    """
    with _LOCK:
        requested = str(name or "").strip()
        previous = preferences()["adapter"]
        found = adapter_module.list_adapters()
        selected = None
        if requested:
            selected = next((entry for entry in adapter_module.usable(found)
                             if entry.name == requested), None)
            if selected is None:
                raise ValueError(i18n.t("net.noUsableAdapter"))

        # Re-selecting the same item is idempotent: do not flap routes or
        # devices. ``ensure`` is re-entrant and still repairs a missing alias.
        if requested == previous:
            return ensure(inventory, options)

        released, migration_failures = [], []
        try:
            save_preferences({"adapter": requested})
        except OSError as exc:
            # The session carries on with whatever was stored before — but
            # the user is told, because the screen would otherwise show a
            # choice that is gone at the next start.
            migration_failures.append({
                "network": "",
                "error": i18n.t("net.choiceNotSaved", detail=_short(exc)),
            })
        if selected is not None:
            target_handles = {selected.name, selected.handle}
            for record in list(aliases.active()):
                if str(record.get("handle") or "") in target_handles:
                    continue
                try:
                    removed = aliases.remove(record)
                except Exception as exc:
                    removed = False
                    detail = _short(exc)
                else:
                    detail = i18n.t("error.noConnection")
                if removed:
                    released.append(record)
                    continue
                network = planning.network_of(
                    str(record.get("ip") or ""), planning.DEFAULT_PREFIX)
                migration_failures.append({
                    "network": str(network or ""), "error": detail})

        result = ensure(inventory, options)
        result["released"] = released
        result["failed"] = migration_failures + result["failed"]
        return result


def _short(exc: BaseException) -> str:
    text = str(exc).strip()
    return (text or type(exc).__name__)[:160]
