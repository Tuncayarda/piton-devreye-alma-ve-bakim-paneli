#!/usr/bin/env python3
"""What each project is made of, and how the panel talks to it.

ONE PROJECT, ONE FILE. A module beside this one lists the rules that
project's equipment follows, and reading it tells you everything the panel
believes about that customer's train — nothing is inherited from a shared
default that would have to be read as well.

The rules themselves are named and shared (`_rules.py`), which is not the
same as inheriting them: a project references a rule BY NAME, deliberately,
and a project whose equipment differs writes its own rule instead. Today all
five trains happen to agree about most of their equipment; that is a fact
about the fleet, not a structure. The moment one of them stops agreeing, its
file changes and the other four do not.

WHY THIS EXISTS. `read_method_for` used to be one if-chain covering every
project at once, and the configuration field set was keyed by SubType alone.
Two customers whose "Intercom" is the same word but not the same device had
nowhere to say so — the first one to differ would have had to be handled by
a branch, and a branch is exactly what `panel/editions/catalogue.py` says
this application does not have.

A project not in the table gets `SHARED`: the union of the rules, which is
what a DeviceMap delivered on a service key gets (`panel.adminkey.pack`).
There is nowhere to declare rules for a map that arrived on a stick, and
refusing to read it at all would be worse than reading it the ordinary way.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._rules import (ANDROID_DISPLAY, ANNOUNCEMENT_HTTP, CONTROL_APP, PASSIVE,
                     SWITCH_KYLAND, VIDEO_ISAPI, Rule)
from . import fuar, gaziray, gdm, vip, yatakli


@dataclass(frozen=True)
class Profile:
    """One project's rules, in the order they are asked."""

    key: str
    rules: tuple[Rule, ...]

    def rule_for(self, device_type: str, subtype: str | None) -> Rule | None:
        return next((rule for rule in self.rules
                     if rule.covers(device_type, subtype)), None)

    def read_method(self, device_type: str, subtype: str | None) -> str:
        """Which reader reaches this device on this project.

        `PASSIVE` for anything no rule claims: the panel knows it from
        DeviceMap and asks it nothing. `tests/test_data.py` keeps that from
        becoming a hiding place — a device kind that falls through here and
        is not named as deliberately passive fails the build.
        """
        rule = self.rule_for(device_type, subtype)
        return rule.read if rule else PASSIVE

    def config_scope(self, device_type: str, subtype: str | None) -> str:
        """What decides this device's configuration field set.

        The SubType for most equipment, the Type for video — see `Rule`.
        Anything no rule claims is scoped by its SubType, which is what the
        screen showed before profiles existed.
        """
        rule = self.rule_for(device_type, subtype)
        return (rule.scope(device_type, subtype) if rule
                else (subtype or ""))


_MODULES = (yatakli, vip, gdm, gaziray, fuar)
BY_KEY = {module.KEY: Profile(module.KEY, module.RULES)
          for module in _MODULES}

# Every rule this application knows, for a map whose project has no file of
# its own. Ordered like a project's own list — the specific before the
# general — so an unknown map is read exactly as a known one would be.
SHARED = Profile("", (SWITCH_KYLAND, ANNOUNCEMENT_HTTP, VIDEO_ISAPI,
                      CONTROL_APP, ANDROID_DISPLAY))


def for_project(key: str) -> Profile:
    """The profile for this project key, or the shared rules.

    The key is the project's own — `Inventory.project` lowercased, which is
    the DeviceMap's file stem and is held equal to `Project.key` by
    `tests/test_editions.py`.
    """
    return BY_KEY.get(str(key or "").strip().lower(), SHARED)
