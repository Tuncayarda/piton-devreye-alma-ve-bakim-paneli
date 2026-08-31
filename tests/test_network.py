#!/usr/bin/env python3
"""Preparing the computer's own network (panel.network).

The failure this covers was reported from the field and is the reason the
package exists:

    computer            10.17.1.222/24
    switches            10.17.1.100, 10.17.1.101
    intercoms (factory) 10.1.1.12

The switches read fine — they are inside the computer's own /24. The devices
do not: an unconfigured intercom answers on 10.1.1.12 and the computer has no
route there, so every probe failed before a packet left the machine. Every
port reported "device not found" and the address had to be added by hand.

NOTHING HERE TOUCHES THE HOST'S NETWORK. The commands are pure functions and
are built for all three platforms on whichever one is running the suite (the
same approach as tests/test_elevation.py); everything that would execute one
runs against a fake `subprocess`.

That is not a style preference. The suite once DID reconfigure a developer's
machine: full scans and IP runs are exercised end to end against fake devices,
those jobs prepare the network before they start, and `ifconfig alias` ran for
real — four addresses were left on a live interface by `unittest discover`.
Faking `subprocess` in this file was never going to catch it, because every
other test that starts a job went through the same code. The suite now sets
`PANEL_NETWORK_WRITES=0` for everything (tests/support/base.py); the classes
below turn it back on only around a faked command.
"""
from __future__ import annotations

import errno
import ipaddress
import json
import os
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from .support import fakes
from .support.base import ROOT, PanelTest  # noqa: F401  (sys.path + temp data)

from panel import editions, errors, i18n, ip_assign, settings
from panel.inventory import device_map
from panel.probe import camera as camera_probe
from panel.network import (adapters, aliases, commands, planning, prepare,
                           routes)


# ───────────────────────────────────────────────────── write opt-in ────────
class AllowsWrites:
    """Mixin for the tests that exercise the writing path."""

    def allow_writes(self):
        """Turn the suite-wide write block off for this test only.

        Safe because every command in these tests goes to a fake; the block
        exists to stop the OTHER tests — scans, IP runs — from reaching a real
        `ifconfig`. See the module docstring.
        """
        patch = mock.patch.object(aliases, "WRITES_ALLOWED", True)
        patch.start()
        self.addCleanup(patch.stop)


# ─────────────────────────────────────────────────────────── commands ──────
class Commands(unittest.TestCase):
    """The argument list is the whole decision; a wrong one is invisible."""

    def test_every_platform_builds_an_add_command(self):
        built = {system: commands.add_command("en0", "10.1.1.225", 24, system)
                 for system in commands.SUPPORTED_SYSTEMS}
        self.assertEqual(built["Darwin"],
                         ["ifconfig", "en0", "alias", "10.1.1.225",
                          "netmask", "255.255.255.0"])
        self.assertEqual(built["Linux"],
                         ["ip", "addr", "add", "10.1.1.225/24",
                          "dev", "en0"])
        self.assertEqual(built["Windows"],
                         ["netsh", "interface", "ipv4", "add", "address",
                          "name=en0", "address=10.1.1.225",
                          "mask=255.255.255.0", "store=active"])

    def test_every_platform_builds_a_remove_command(self):
        self.assertEqual(
            commands.remove_command("en0", "10.1.1.225", 24, "Darwin"),
            ["ifconfig", "en0", "-alias", "10.1.1.225"])
        # Linux needs the prefix back: `ip addr del` without one removes
        # whichever prefix it finds first, which could be the real address.
        self.assertEqual(
            commands.remove_command("eth0", "10.1.1.225", 24, "Linux"),
            ["ip", "addr", "del", "10.1.1.225/24", "dev", "eth0"])
        self.assertEqual(
            commands.remove_command("12", "10.1.1.225", 24, "Windows"),
            ["netsh", "interface", "ipv4", "delete", "address",
             "name=12", "address=10.1.1.225", "store=active"])

    def test_the_windows_address_is_never_persistent(self):
        """`store=active` is the crash safety net, not a detail.

        Without it the address goes into the registry and survives a reboot;
        a process killed mid-run would leave the machine reconfigured with
        nobody left to undo it.
        """
        for build in (commands.add_command, commands.remove_command):
            self.assertIn("store=active",
                          build("12", "10.1.1.225", 24, "Windows"))

    def test_no_command_replaces_an_existing_configuration(self):
        """Only ever add beside; never `set`, never a persistent writer."""
        forbidden = ("set", "New-NetIPAddress", "networksetup")
        for system in commands.SUPPORTED_SYSTEMS:
            for build in (commands.add_command, commands.remove_command):
                argv = build("en0", "10.1.1.225", 24, system)
                for word in forbidden:
                    self.assertNotIn(word, argv, f"{system}: {argv}")

    def test_an_unknown_system_is_refused_rather_than_guessed(self):
        self.assertFalse(commands.supported("Plan9"))
        with self.assertRaises(ValueError):
            commands.add_command("en0", "10.1.1.225", 24, "Plan9")

    def test_the_netmask_follows_the_prefix(self):
        self.assertEqual(commands.netmask(24), "255.255.255.0")
        self.assertEqual(commands.netmask(16), "255.255.0.0")


# ─────────────────────────────────────────────────────────── adapters ──────
IFCONFIG_MACOS = (
    "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n"
    "\tinet 127.0.0.1 netmask 0xff000000\n"
    "en5: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
    "\tether 5c:01:3b:8a:76:43\n"
    "\tinet 10.17.1.222 netmask 0xffffff00 broadcast 10.17.1.255\n"
    "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
    "\tether 92:c7:de:a4:89:02\n"
    "\tinet 192.168.1.44 netmask 0xffffff00 broadcast 192.168.1.255\n"
    "utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
    "\tinet 10.9.9.2 --> 10.9.9.2 netmask 0xffffffff\n"
)

IP_LINK = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN "
    "link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n"
    "2: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP "
    "link/ether 5c:01:3b:8a:76:43 brd ff:ff:ff:ff:ff:ff\n"
    "3: wlp2s0: <BROADCAST,MULTICAST,UP> mtu 1500 state DOWN "
    "link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff\n"
)

IP_ADDR = (
    "1: lo    inet 127.0.0.1/8 scope host lo\n"
    "2: enp3s0    inet 10.17.1.222/24 brd 10.17.1.255 scope global enp3s0\n"
)

# `ipconfig /all` on a Turkish Windows — the labels are translated, the
# numbers are not. Real output, kept as it arrived.
IPCONFIG_TR = (
    "Windows IP Yapılandırması\n"
    "\n"
    "Ethernet bağdaştırıcısı Ethernet:\n"
    "   Fiziksel Adres. . . . . . . . . . : 5C-01-3B-8A-76-43\n"
    "   IPv4 Adresi . . . . . . . . . . . : 10.17.1.222(Tercih Edilen)\n"
    "   Alt Ağ Maskesi  . . . . . . . . . : 255.255.255.0\n"
    "   Varsayılan Ağ Geçidi. . . . . . . : 10.17.1.101\n"
)

WINDOWS_QUERY_OUTPUT = (
    "A\t12\t5C-01-3B-8A-76-43\tUp\tEthernet\n"
    "A\t18\tAA-BB-CC-DD-EE-FF\tDisconnected\tWi-Fi\n"
    "I\t12\t10.17.1.222\t24\n"
    "I\t18\t169.254.5.5\t16\n"
)


class PosixAdapters(unittest.TestCase):

    def test_macos_hex_netmasks_become_prefixes(self):
        found = adapters.parse_posix_addresses(
            "\tinet 10.17.1.222 netmask 0xffffff00 broadcast 10.17.1.255")
        self.assertEqual(found, [("10.17.1.222", 24)])

    def test_the_four_field_formats_all_parse(self):
        for text, expected in (
                ("inet 10.0.2.15/24", ("10.0.2.15", 24)),
                ("inet 10.0.2.15 netmask 0xffff0000", ("10.0.2.15", 16)),
                ("inet 10.0.2.15 netmask 255.255.255.0", ("10.0.2.15", 24)),
                (("inet addr:10.0.2.15  Bcast:10.0.2.255  "
                 "Mask:255.255.255.0"), ("10.0.2.15", 24))):
            self.assertIn(expected, adapters.parse_posix_addresses(text), text)

    def test_the_field_computer_is_read_out_of_ifconfig(self):
        with mock.patch.object(adapters.interfaces, "dump",
                               lambda: IFCONFIG_MACOS):
            found = adapters.list_adapters("Darwin")
        by_name = {adapter.name: adapter for adapter in found}
        self.assertEqual(by_name["en5"].addresses, [("10.17.1.222", 24)])
        self.assertEqual(by_name["en5"].mac, "5c:01:3b:8a:76:43")
        self.assertTrue(by_name["en5"].up)
        # The tunnel and the loopback are software, and an address added to
        # one goes nowhere.
        self.assertTrue(by_name["utun4"].virtual)
        self.assertTrue(by_name["lo0"].virtual)
        self.assertFalse(by_name["en5"].virtual)

    def test_a_linux_box_without_ifconfig_is_still_readable(self):
        """`ip -o addr` carries no MAC and `ip -o link` no address.

        Neither is usable alone, and taking only the first left a current
        Ubuntu with no readable interface at all.
        """
        def run(argv, timeout=None):
            if argv[:3] == ["ip", "-o", "link"]:
                return 0, IP_LINK
            if argv[:3] == ["ip", "-o", "addr"]:
                return 0, IP_ADDR
            return None, ""

        with mock.patch.object(adapters.interfaces, "dump", lambda: ""), \
                mock.patch.object(adapters.interfaces, "run_command", run):
            found = adapters.list_adapters("Linux")
        by_name = {adapter.name: adapter for adapter in found}
        self.assertEqual(by_name["enp3s0"].addresses, [("10.17.1.222", 24)])
        self.assertEqual(by_name["enp3s0"].mac, "5c:01:3b:8a:76:43")
        self.assertTrue(by_name["enp3s0"].up)
        # UP without LOWER_UP is "enabled", not "plugged in".
        self.assertFalse(by_name["wlp2s0"].up)


class WindowsAdapters(unittest.TestCase):

    def test_the_powershell_answer_gives_the_index_netsh_needs(self):
        found = adapters.parse_windows_query(WINDOWS_QUERY_OUTPUT)
        by_name = {adapter.name: adapter for adapter in found}
        self.assertEqual(by_name["Ethernet"].handle, "12")
        self.assertEqual(by_name["Ethernet"].mac, "5c:01:3b:8a:76:43")
        self.assertEqual(by_name["Ethernet"].addresses, [("10.17.1.222", 24)])
        self.assertTrue(by_name["Ethernet"].up)
        self.assertFalse(by_name["Wi-Fi"].up)

    def test_the_ipconfig_fallback_pairs_addresses_by_position(self):
        """No label is read — they are all translated.

        Within a block the mask line follows the address line, so an address
        is taken only when the next number is a valid netmask. That is what
        keeps the default gateway (10.17.1.101 here) from being read as one
        of this computer's own addresses.
        """
        found = adapters.parse_ipconfig_addresses(IPCONFIG_TR)
        self.assertEqual(found, [("10.17.1.222", 24)])

    def test_getmac_is_read_by_column_not_by_header(self):
        text = ('"Ethernet","Intel(R) I219-LM","5C-01-3B-8A-76-43",'
                '"\\Device\\Tcpip_{GUID}"\n')
        self.assertEqual(adapters.parse_getmac_csv(text),
                         {"5c:01:3b:8a:76:43": "Ethernet"})


class AdapterChoice(unittest.TestCase):
    """Which card the address lands on — or none, which is a real answer.

    The rule is "point at a fact or say nothing". An earlier version ranked
    the adapters (carrier, wired, addressed) when no fact was available, and
    on a laptop tethered to a phone it picked the phone: the address went to
    a card with nothing on the far end, the run failed exactly as before, and
    the screen claimed an interface had been chosen.
    """

    FACTORY = "10.1.1.12"

    def _adapters(self):
        return [
            adapters.Adapter(name="lo0", handle="lo0",
                             addresses=[("127.0.0.1", 8)], up=True,
                             virtual=True),
            adapters.Adapter(name="utun4", handle="utun4",
                             addresses=[("10.9.9.2", 32)], up=True,
                             virtual=True),
            # The phone hotspot: up, wired by name, and addressed. Everything
            # the old ranking rewarded.
            adapters.Adapter(name="en0", handle="en0", mac="92:c7:de:a4:89:02",
                             addresses=[("172.20.10.3", 28)], up=True),
            adapters.Adapter(name="en5", handle="en5", mac="5c:01:3b:8a:76:43",
                             addresses=[("10.17.1.222", 24)], up=True),
        ]

    def test_the_adapter_on_the_factory_network_is_the_first_answer(self):
        found = self._adapters()
        found.append(adapters.Adapter(name="en7", handle="en7",
                                      addresses=[("10.1.1.225", 24)], up=True))
        chosen = adapters.choose(found, [self.FACTORY, "10.17.1.100"])
        self.assertEqual(chosen.name, "en7")

    def test_the_adapter_holding_the_switch_network_is_the_second(self):
        chosen = adapters.choose(self._adapters(),
                                 [self.FACTORY, "10.17.1.100"])
        self.assertEqual(chosen.name, "en5")

    def test_the_phone_hotspot_is_never_picked_as_a_fallback(self):
        """The reported complaint, as an assertion.

        Nothing here holds an address on the devices' network, so there is no
        answer to give and none is invented.
        """
        found = [entry for entry in self._adapters()
                 if entry.name in ("lo0", "utun4", "en0")]
        self.assertIsNone(adapters.choose(found, [self.FACTORY, "10.17.1.100"]))

    def test_a_virtual_adapter_is_never_chosen(self):
        only_virtual = [entry for entry in self._adapters() if entry.virtual]
        self.assertIsNone(adapters.choose(only_virtual, ["10.9.9.2"]))
        # Not even when a tunnel is the one holding the target's network.
        self.assertIsNone(adapters.choose(self._adapters(), ["10.9.9.2"]))

    def test_the_users_choice_beats_everything(self):
        chosen = adapters.choose(self._adapters(),
                                 [self.FACTORY, "10.17.1.100"], override="en0")
        self.assertEqual(chosen.name, "en0")

    def test_the_picker_still_offers_the_likeliest_first(self):
        """Not choosing is not the same as having nothing to show.

        `choose` stays silent, but the list the user picks from is ordered:
        carrier, then wired, then already addressed.
        """
        found = [
            adapters.Adapter(name="eth9", handle="eth9", up=False),
            adapters.Adapter(name="eth1", handle="eth1", up=True),
            adapters.Adapter(name="eth0", handle="eth0", up=True,
                             addresses=[("192.168.1.5", 24)]),
        ]
        self.assertIsNone(adapters.choose(found, ["10.1.1.12"]))
        self.assertEqual([entry.name for entry in adapters.usable(found)],
                         ["eth0", "eth1", "eth9"])

    def test_nothing_is_chosen_when_there_is_nothing_to_choose(self):
        self.assertIsNone(adapters.choose([], ["10.1.1.12"]))


# ─────────────────────────────────────────────────────────── planning ──────
class RequiredNetworks(PanelTest):
    """The field diagnosis, as an assertion."""

    def _inventory(self):
        # Set 17: switches on 10.17.1.100/101, devices on 10.17.1.x.
        topology = fakes.device_map(
            [{"Name": "Intercom 1", "Type": "Announcement",
              "SubType": "Intercom", "IP": "10.17.1.10", "Port": 11,
              "IsActive": True}],
            switch_ip="10.17.1.100", switch_name="Yatakli_1")
        topology["Switches"].append({
            "Name": "Yatakli_2", "IP": "10.17.1.101", "IsActive": True,
            "Devices": []})
        return self.build_map(topology)

    def test_the_reported_failure_needs_exactly_the_factory_network(self):
        """Computer on 10.17.1.222/24: the switches are fine, 10.1.1.12 is not."""
        required = planning.required_networks(
            self._inventory(),
            known=[ipaddress.ip_network("10.17.1.0/24")])
        self.assertEqual([str(entry.network) for entry in required],
                         ["10.1.1.0/24"])
        self.assertEqual(required[0].target, settings.FACTORY_IP)

    def test_a_foreign_network_needs_the_set_as_well(self):
        required = planning.required_networks(
            self._inventory(),
            known=[ipaddress.ip_network("192.168.1.0/24")])
        self.assertEqual(sorted(str(entry.network) for entry in required),
                         ["10.1.1.0/24", "10.17.1.0/24"])

    def test_a_wide_local_prefix_already_covers_the_narrow_one(self):
        """Reachability is membership, not equality.

        A machine on 10.1.0.0/16 reaches 10.1.1.12 already; adding a second
        address for the same range would be noise.
        """
        required = planning.required_networks(
            self._inventory(),
            known=[ipaddress.ip_network("10.1.0.0/16"),
                   ipaddress.ip_network("10.17.0.0/16")])
        self.assertEqual(required, [])

    def test_a_search_range_outside_both_is_added(self):
        required = planning.required_networks(
            self._inventory(),
            known=[ipaddress.ip_network("10.1.1.0/24"),
                   ipaddress.ip_network("10.17.1.0/24")],
            extra=["192.168.7.20"])
        self.assertEqual([str(entry.network) for entry in required],
                         ["192.168.7.0/24"])

    def test_an_overridden_factory_address_is_the_one_used(self):
        required = planning.required_networks(
            self._inventory(), factory_ip="172.16.4.9",
            known=[ipaddress.ip_network("10.17.1.0/24")])
        self.assertIn("172.16.4.0/24",
                      [str(entry.network) for entry in required])
        self.assertNotIn("10.1.1.0/24",
                         [str(entry.network) for entry in required])


class HostAddress(PanelTest):

    NETWORK = ipaddress.ip_network("10.1.1.0/24")

    def test_the_default_is_the_documented_two_two_five(self):
        self.assertEqual(planning.choose_host(self.NETWORK, set()),
                         "10.1.1.225")

    def test_an_address_devicemap_plans_for_is_stepped_over(self):
        taken = {"10.1.1.225", "10.1.1.226"}
        self.assertEqual(planning.choose_host(self.NETWORK, taken),
                         "10.1.1.227")

    def test_the_panel_never_takes_a_device_address(self):
        inventory = self.build_map(fakes.device_map(
            [{"Name": "Odd", "Type": "Announcement", "SubType": "Intercom",
              "IP": "10.1.1.225", "Port": 11, "IsActive": True}],
            switch_ip="10.1.1.100"))
        taken = planning.occupied(inventory)
        self.assertIn("10.1.1.225", taken)
        # The factory address is in there whether DeviceMap mentions it or not.
        self.assertIn(settings.FACTORY_IP, taken)
        self.assertNotEqual(planning.choose_host(self.NETWORK, taken),
                            "10.1.1.225")

    def test_the_network_and_broadcast_addresses_are_never_taken(self):
        chosen = planning.choose_host(ipaddress.ip_network("10.1.1.0/24"),
                                      set(), octet=254, limit=255)
        self.assertEqual(chosen, "10.1.1.254")

    def test_a_full_network_says_so_instead_of_inventing_an_address(self):
        tiny = ipaddress.ip_network("10.1.1.0/30")
        with self.assertRaises(ValueError):
            planning.choose_host(tiny, {"10.1.1.1", "10.1.1.2"})


# ─────────────────────────────────────────────────────── the registry ──────
class ProjectWidth(PanelTest):
    """A project states how wide its network is, and everything follows.

    Three things used to be one global number each: the mask written to a
    device, the width of the alias the panel gives itself, and the mask
    verified on a camera. Gaziray is where that broke — the third octet is the
    CAR, so its four cars sit on four /24s and the broker on a fifth, and a
    /24 alias left five addresses on the adapter with still no route to MQTT.

    YATAKLI AND VIP STATE NOTHING, and these tests are the lock on that: they
    fall through to the same globals they always did and must come out of
    every change here bit for bit.
    """

    FOREIGN = ipaddress.ip_network("192.168.1.0/24")

    def plan(self, edition: str, project: str):
        """The addresses the panel would give itself, from a foreign network."""
        editions.activate(edition)
        editions.use_project(project)
        found = editions.map_path(editions.current_project())
        inventory = device_map.load(7, found, cache=False)
        required = planning.required_networks(
            inventory, factory_ip="10.1.1.12", prefix=prepare._prefix(),
            broker=editions.broker_ip(inventory), known=[self.FOREIGN])
        taken = planning.occupied(inventory, "10.1.1.12")
        return [f"{planning.choose_host(entry.network, taken, anchor=entry.anchor)}"
                f"/{entry.network.prefixlen}" for entry in required]

    def tearDown(self):
        editions.activate(os.environ["DAP_EDITION"])
        super().tearDown()

    def test_yatakli_and_vip_are_untouched(self):
        """The regression lock. These two work; they must not move."""
        self.assertEqual(self.plan("vip-yatakli", "yatakli"),
                         ["10.1.1.225/24", "10.7.1.225/24"])
        self.assertEqual(self.plan("vip-yatakli", "vip"),
                         ["10.1.1.225/24", "10.7.2.225/24"])

    def test_a_project_prefix_widens_the_alias(self):
        """Gaziray: five narrow addresses become two wide ones.

        And the wide one COVERS THE BROKER, which the five did not: 10.n.0.1
        is on a network of its own and no device in the map is near it.
        """
        addresses = self.plan("gaziray", "gaziray")
        self.assertEqual(addresses, ["10.1.1.225/16", "10.7.1.225/16"])
        held = ipaddress.ip_network("10.7.1.225/16", strict=False)
        self.assertIn(ipaddress.ip_address("10.7.0.1"), held)

    def test_the_host_sits_where_the_devices_are(self):
        """GDM's cameras are on a /24 and the project runs a /16.

        Counted from the base of that /16 the panel would take 192.168.0.225,
        which a camera cannot answer: replying means leaving its own subnet
        through a gateway it has no reason to have. The address has to land
        inside the devices' own /24 and keep the wide mask.
        """
        addresses = self.plan("gdm", "gdm")
        self.assertIn("192.168.201.225/16", addresses)
        self.assertNotIn("192.168.0.225/16", addresses)
        # Both directions, spelled out.
        panel = ipaddress.ip_network("192.168.201.225/16", strict=False)
        camera = ipaddress.ip_address("192.168.201.21")
        self.assertIn(camera, panel)
        camera_side = ipaddress.ip_network("192.168.201.21/24", strict=False)
        self.assertIn(ipaddress.ip_address("192.168.201.225"), camera_side)

    def test_the_broker_is_a_required_network(self):
        """The broker is a role, not a device, so nothing else asks for it."""
        inventory = self.build_map(fakes.device_map(
            [{"Name": "Intercom_1", "Type": "Announcement",
              "SubType": "Intercom", "IP": "10.1.1.10", "Port": 11,
              "IsActive": True}], switch_ip="10.1.1.100"))
        without = planning.required_networks(
            inventory, factory_ip="10.1.1.12",
            known=[ipaddress.ip_network("10.1.1.0/24")])
        self.assertEqual([str(entry.network) for entry in without], [])
        with_broker = planning.required_networks(
            inventory, factory_ip="10.1.1.12", broker="10.9.0.1",
            known=[ipaddress.ip_network("10.1.1.0/24")])
        self.assertEqual([str(entry.network) for entry in with_broker],
                         ["10.9.0.0/24"])

    def test_the_span_lands_on_an_octet_boundary(self):
        """A project is laid out as a /24 or a /16, never as a /21.

        The addresses alone would give something tighter — Yatakli's run .1 to
        .101 and fit in a /25 — but that is an accident of which addresses are
        in use, not a boundary anybody drew, and answering it would fail a
        camera set to the /24 the train is actually built on.
        """
        for edition, project, expected in (
                ("vip-yatakli", "yatakli", "10.7.1.0/24"),
                ("vip-yatakli", "vip", "10.7.2.0/24"),
                ("gdm", "gdm", "192.168.201.0/24"),
                ("gaziray", "gaziray", "10.7.0.0/16"),
                ("fuar", "fuar", "10.1.0.0/16")):
            editions.activate(edition)
            editions.use_project(project)
            inventory = device_map.load(
                7, editions.map_path(editions.current_project()), cache=False)
            span = inventory.span(editions.broker_ip(inventory))
            self.assertEqual(str(span), expected, project)

    def test_the_mask_a_run_writes_reaches_the_whole_project(self):
        """The two halves of a project's width have to give one answer.

        `effective_prefix` is the mask an IP run WRITES to a device;
        `Inventory.span` is what the camera scan then DEMANDS of it. Nothing
        holds the two together — one is stated on the project, the other is
        computed from the map — so a project can be delivered with addresses
        across four /24s and still fall through to the /24 default, and the
        panel reports a mask fault on the very device it configured itself.
        Fuar was exactly that until it was given a prefix, and this is the
        check that would have said so.
        """
        for edition, project in (("vip-yatakli", "yatakli"),
                                 ("vip-yatakli", "vip"),
                                 ("gdm", "gdm"),
                                 ("gaziray", "gaziray"),
                                 ("fuar", "fuar")):
            editions.activate(edition)
            editions.use_project(project)
            inventory = device_map.load(
                7, editions.map_path(editions.current_project()), cache=False)
            span = str(inventory.span(editions.broker_ip(inventory)) or "")
            written = ip_assign.netmask_for(ip_assign.effective_prefix())
            self.assertEqual(
                [d.ip for d in inventory.devices if d.ip
                 and not camera_probe._mask_reaches(d.ip, written, span)], [],
                f"{project}: the run writes {written}, which does not reach "
                f"{span} — state a prefix on the project")

    def test_a_camera_mask_is_judged_on_reach_not_on_equality(self):
        """The CCTV scripts write /8 to the 10.x trains and /24 to GDM.

        Both are correct. What is NOT correct is a Gaziray camera on a /24 —
        it cannot see the other cars, the broker, or the panel — and that is
        the one this catches.
        """
        reaches = camera_probe._mask_reaches
        # Yatakli is one /24. Everything at least that wide passes.
        for mask in ("255.0.0.0", "255.255.0.0", "255.255.255.0"):
            self.assertTrue(reaches("10.7.1.24", mask, "10.7.1.0/24"), mask)
        # Half a /24 does not reach the other half of the train.
        self.assertFalse(reaches("10.7.1.24", "255.255.255.128",
                                 "10.7.1.0/24"))

        # Gaziray is a /16: a /24 leaves the camera on its own car.
        self.assertTrue(reaches("10.7.2.21", "255.0.0.0", "10.7.0.0/16"))
        self.assertFalse(reaches("10.7.2.21", "255.255.255.0", "10.7.0.0/16"))

        # GDM: the /24 the scripts write is exactly enough.
        self.assertTrue(reaches("192.168.201.21", "255.255.255.0",
                                "192.168.201.0/24"))

        # A question that cannot be asked is not a fault.
        self.assertTrue(reaches("10.7.1.24", "255.255.255.0", ""))
        self.assertTrue(reaches("10.7.1.24", "not-a-mask", "10.7.1.0/24"))


class NoLocalAddress(unittest.TestCase):
    """EADDRNOTAVAIL is the computer's fault, and has to read like it.

    The same fault as `StrandedRoutes`, seen from the device side. Reported as
    "device unreachable" it sends the user to the cabinet after a cable that
    was never the problem.
    """

    def test_the_message_names_the_computer_not_the_device(self):
        failure = OSError(errno.EADDRNOTAVAIL,
                          "Can't assign requested address")
        self.assertEqual(errors.user_message(failure),
                         i18n.t("error.noLocalAddress"))

    def test_it_is_found_through_the_wrappers_requests_adds(self):
        """The real OSError sits two or three levels below what is caught."""
        inner = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
        self.assertEqual(errors.user_message(ConnectionError(inner)),
                         i18n.t("error.noLocalAddress"))

    def test_the_text_alone_is_enough_when_the_errno_is_lost(self):
        """urllib3 sometimes re-raises with the message only."""
        self.assertEqual(
            errors.user_message(
                ConnectionError("[Errno 49] Can't assign requested address")),
            i18n.t("error.noLocalAddress"))

    def test_it_still_counts_as_unreachable(self):
        failure = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
        self.assertIsInstance(errors.classify(failure),
                              errors.UnreachableError)

    def test_an_ordinary_refusal_keeps_its_own_message(self):
        refused = ConnectionRefusedError(errno.ECONNREFUSED,
                                         "Connection refused")
        self.assertEqual(errors.user_message(refused),
                         i18n.t("error.noConnection"))


class StrandedRoutes(unittest.TestCase):
    """A network whose route names an address the machine no longer has.

    Verbatim from the machine it happened on. `netstat -rnl` is the only
    place this is visible: `ifconfig` shows a healthy interface, `ping` says
    nothing came back, and every device in the /24 reads as dead hardware.
    """

    TABLE = """Routing tables

Internet:
Destination        Gateway            RT_IFA             \
Flags        Refs      Use    Mtu          Netif Expire
default            192.168.0.1        192.168.0.7        UGScg  \
     10        0   1500            en0
10.1.1/24          link#19            10.1.1.225         UCS    \
    254        0   1500            en6      !
10.1.1.1           0:10:f3:b7:d2:8a   10.1.1.225         UHLWIi \
      1       88   1500            en6   1199
127                127.0.0.1          127.0.0.1          UCS    \
      0        0  16384            lo0
192.168.0/24       link#12            192.168.0.7        UCS    \
      3        0   1500            en0
224.0.0/4          link#19            10.1.1.225         UmCS   \
      0        0   1500            en6
""".replace("\\\n", "")

    def test_the_dead_source_address_is_the_only_row_reported(self):
        broken = routes.stranded(self.TABLE, ["127.0.0.1", "192.168.0.7"])
        self.assertEqual(broken, [{"network": "10.1.1.0/24",
                                   "source": "10.1.1.225",
                                   "interface": "en6"}])

    def test_a_healthy_machine_reports_nothing(self):
        self.assertEqual(
            routes.stranded(self.TABLE,
                            ["127.0.0.1", "192.168.0.7", "10.1.1.225"]), [])

    def test_host_and_multicast_routes_are_not_repeated_as_faults(self):
        """They are cloned from the network route and go when it goes.

        Two hundred rows saying the same thing would bury the one that is
        actionable.
        """
        listed = {entry["network"] for entry in routes.sources(self.TABLE)}
        self.assertNotIn("10.1.1.1/32", listed)
        self.assertNotIn("224.0.0.0/4", listed)
        self.assertIn("10.1.1.0/24", listed)

    def test_the_interface_column_is_found_by_its_header(self):
        """The Expire field is empty on most rows: the last word varies."""
        by_network = {entry["network"]: entry
                      for entry in routes.sources(self.TABLE)}
        self.assertEqual(by_network["192.168.0.0/24"]["interface"], "en0")
        self.assertEqual(by_network["10.1.1.0/24"]["interface"], "en6")

    def test_only_macos_is_asked(self):
        """`netstat` prints RT_IFA on BSD alone, and only macOS strands."""
        for system in ("Linux", "Windows"):
            self.assertEqual(routes.broken_networks(system), [])


class FakeRun:
    """Stands in for `interfaces.run_command`; records every call."""

    def __init__(self, code: int = 0, output: str = ""):
        self.code, self.output = code, output
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        return self.code, self.output


class AliasRegistry(AllowsWrites, unittest.TestCase):
    """Adding an address, writing it down, and always taking it back."""

    def setUp(self):
        self.allow_writes()
        path = aliases.record_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self.addCleanup(lambda: path.exists() and path.unlink())

    def _visible(self, *addresses):
        """The adapter list an add is verified against."""
        return lambda system=None: [adapters.Adapter(
            name="en5", handle="en5",
            addresses=[(address, 24) for address in addresses])]

    def test_an_alias_beside_an_address_of_the_same_network_gets_32(self):
        """Or macOS hands it the subnet route and strands it on removal.

        The field failure this prevents: the interface kept its own live
        address, every route in the /24 kept naming the alias that had been
        taken back, and each device probe died at once with "Can't assign
        requested address" — a whole scan failing in milliseconds.
        """
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.223", "10.1.1.225")):
            record = aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")

        self.assertIn("255.255.255.255", run.calls[0])
        self.assertEqual(record["prefix"], 32)

    def test_the_first_address_in_a_network_still_gets_the_full_prefix(self):
        """Nothing else serves the subnet route, so this alias has to."""
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.225")):
            record = aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")

        self.assertIn("255.255.255.0", run.calls[0])
        self.assertEqual(record["prefix"], 24)

    def test_an_address_in_another_network_does_not_narrow_the_alias(self):
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.17.1.222", "10.1.1.225")):
            record = aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")

        self.assertEqual(record["prefix"], 24)

    def test_a_sibling_host_alias_does_not_count_as_the_route(self):
        """A /32 sits inside the network without carrying it.

        Narrowing on that would leave the route uncreated and add one more
        useless host address on every run.
        """
        adapter = adapters.Adapter(
            name="en5", handle="en5",
            addresses=[("10.1.1.224", 32), ("10.1.1.225", 24)])
        with mock.patch.object(aliases.adapter_module, "list_adapters",
                               lambda system=None: [adapter]):
            self.assertEqual(
                aliases.alias_prefix("en5", "10.1.1.225", 24, "Darwin"), 24)

    def test_a_wider_address_already_carries_the_route(self):
        adapter = adapters.Adapter(
            name="en5", handle="en5",
            addresses=[("10.1.0.9", 16), ("10.1.1.225", 24)])
        with mock.patch.object(aliases.adapter_module, "list_adapters",
                               lambda system=None: [adapter]):
            self.assertEqual(
                aliases.alias_prefix("en5", "10.1.1.225", 24, "Darwin"), 32)

    def test_only_macos_narrows_the_alias(self):
        """`ip addr add` and `netsh` do not move a subnet route around."""
        with mock.patch.object(aliases.adapter_module, "list_adapters",
                               self._visible("10.1.1.223", "10.1.1.225")):
            for system in ("Linux", "Windows"):
                self.assertEqual(
                    aliases.alias_prefix("en5", "10.1.1.225", 24, system), 24)

    def test_an_added_address_is_recorded_and_then_removed(self):
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.225")):
            record = aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
            self.assertEqual(aliases.active(), [record])
            self.assertEqual(record["pid"], os.getpid())
            self.assertTrue(aliases.release("10.1.1.225"))
        self.assertEqual(aliases.active(), [])
        self.assertEqual(run.calls[0][:3], ["ifconfig", "en5", "alias"])
        self.assertEqual(run.calls[-1][:3], ["ifconfig", "en5", "-alias"])

    def test_the_record_is_written_before_the_command_runs(self):
        """A process killed between the two must still leave a trace.

        A record for an address that was never added is harmless — removing
        an address that is not there fails and is ignored. An address nobody
        knows about, on a field laptop, is not.
        """
        seen = {}

        def run(argv, timeout=None):
            seen["records"] = json.loads(
                aliases.record_file().read_text(encoding="utf-8"))
            return 0, ""

        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.225")):
            aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
        self.assertEqual(seen["records"]["aliases"][0]["ip"], "10.1.1.225")

    def test_a_command_that_fails_claims_nothing(self):
        run = FakeRun(code=1, output="ifconfig: permission denied")
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible()):
            with self.assertRaises(RuntimeError) as caught:
                aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
        self.assertIn("permission denied", str(caught.exception))
        self.assertEqual(aliases.active(), [])

    def test_an_address_that_did_not_appear_is_not_reported_as_added(self):
        """Exit code 0 is not proof; the address has to be on the adapter.

        Reporting it as added would send the run off after devices it cannot
        reach and hide the reason.
        """
        run = FakeRun(code=0)
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.9.9.9")):
            with self.assertRaises(RuntimeError):
                aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
        self.assertEqual(aliases.active(), [])

    def test_release_all_takes_back_every_address_of_this_session(self):
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.225", "10.17.1.225")):
            aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
            aliases.add("en5", "10.17.1.225", 24, "en5", "Darwin")
            self.assertEqual(len(aliases.active()), 2)
            self.assertEqual(aliases.release_all(), 2)
        self.assertEqual(aliases.active(), [])

    def test_a_dead_owners_address_is_swept_at_start_up(self):
        """A crash skips the teardown; the pid says whether that happened."""
        aliases._write_records([
            {"ip": "10.1.1.225", "prefix": 24, "handle": "en5",
             "adapter": "en5", "system": "Darwin", "pid": 999999},
            {"ip": "10.2.2.225", "prefix": 24, "handle": "en5",
             "adapter": "en5", "system": "Darwin", "pid": os.getpid()},
        ])
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases, "process_alive", lambda pid: False):
            self.assertEqual(aliases.sweep_stale(), 1)
        # Only the dead owner's address was removed; ours is untouched.
        self.assertEqual([entry["ip"] for entry in aliases.active()],
                         ["10.2.2.225"])
        self.assertEqual(len(run.calls), 1)
        self.assertIn("10.1.1.225", run.calls[0])

    def test_another_live_panels_address_is_left_alone(self):
        aliases._write_records([
            {"ip": "10.1.1.225", "prefix": 24, "handle": "en5",
             "adapter": "en5", "system": "Darwin", "pid": 4242},
        ])
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases, "process_alive", lambda pid: True):
            self.assertEqual(aliases.sweep_stale(), 0)
        self.assertEqual(run.calls, [])

    def test_only_addresses_the_panel_added_can_be_released(self):
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run):
            self.assertFalse(aliases.release("10.17.1.222"))
        self.assertEqual(run.calls, [])

    def test_a_torn_write_cannot_take_the_record_file_with_it(self):
        """The record is all that stands between an added address and a
        stranded one (rule 2 in the module note), and it used to be
        rewritten IN PLACE: a process killed — or a disk filling — halfway
        through the write left half a JSON document behind, `_read_records`
        read that as "no records at all", and every address in the file
        stayed on the adapter with nothing left pointing at it. The write
        now lands beside the file and is swapped in whole, so a torn write
        tears the scratch copy and never the record."""
        aliases._write_records([
            {"ip": "10.1.1.225", "prefix": 24, "handle": "en5",
             "adapter": "en5", "system": "Darwin", "pid": os.getpid()}])

        real_write_text = Path.write_text

        def torn(path, text, encoding=None):
            # Half the document reaches the disk before the "crash".
            real_write_text(path, text[:len(text) // 2], encoding=encoding)
            raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(Path, "write_text", torn):
            aliases._write_records([])          # any later rewrite

        self.assertEqual(
            [entry["ip"] for entry in aliases._read_records()],
            ["10.1.1.225"],
            "the half-written file must not replace the record")

    def test_the_record_holds_no_credential(self):
        run = FakeRun()
        with mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.adapter_module, "list_adapters",
                                  self._visible("10.1.1.225")):
            record = aliases.add("en5", "10.1.1.225", 24, "en5", "Darwin")
        self.assertEqual(set(record),
                         {"ip", "prefix", "handle", "adapter", "system",
                          "pid", "addedAt"})


# ──────────────────────────────────────────────────── the whole thing ──────
class Prepare(AllowsWrites, PanelTest):
    """`ensure` end to end, with the OS faked out."""

    def setUp(self):
        super().setUp()
        self.allow_writes()
        for path in (aliases.record_file(), settings.network_settings_file()):
            if path.exists():
                path.unlink()
        self.addCleanup(aliases.release_all)

    def _inventory(self):
        topology = fakes.device_map(
            [{"Name": "Intercom 1", "Type": "Announcement",
              "SubType": "Intercom", "IP": "10.17.1.10", "Port": 11,
              "IsActive": True}],
            switch_ip="10.17.1.100", switch_name="Yatakli_1")
        return self.build_map(topology)

    def _host(self, added):
        """A machine on 10.17.1.222/24 that accepts whatever it is given."""
        def list_adapters(system=None):
            return [adapters.Adapter(
                name="en5", handle="en5", mac="5c:01:3b:8a:76:43",
                addresses=[("10.17.1.222", 24)]
                + [(ip, 24) for ip in added], up=True)]
        return list_adapters

    def test_the_field_failure_is_repaired_in_one_call(self):
        added: list[str] = []

        def run(argv, timeout=None):
            if "alias" in argv:
                added.append(argv[argv.index("alias") + 1])
            return 0, ""

        # One patch reaches all three call sites: `prepare` and `aliases` both
        # hold the same module object, not a copy of the function.
        with mock.patch.object(adapters, "list_adapters", self._host(added)), \
                mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.platform, "system",
                                  lambda: "Darwin"), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            result = prepare.ensure(self._inventory())

        # Exactly one address, on the factory network, at the documented host.
        self.assertEqual([entry["ip"] for entry in result["added"]],
                         ["10.1.1.225"])
        self.assertEqual(result["added"][0]["adapter"], "en5")
        self.assertEqual(result["failed"], [])

    def test_startup_prepares_the_saved_adapter_once_after_stale_cleanup(self):
        """The factory alias exists before the first scan timer fires."""
        from panel.api import lifecycle

        inventory = self._inventory()
        prepare.save_preferences({"adapter": "en6"})
        addresses = {"en6": [("10.17.1.222", 24)]}
        owned: list[dict] = []
        events: list[str] = []

        def list_adapters(system=None):
            return [adapters.Adapter(
                name="en6", handle="en6", addresses=list(addresses["en6"]),
                up=True)]

        def add(handle, ip, prefix, adapter_name="", system=None):
            record = {"ip": ip, "prefix": prefix, "handle": handle,
                      "adapter": adapter_name, "system": "Darwin",
                      "pid": os.getpid()}
            events.append(f"add:{handle}:{ip}/{prefix}")
            addresses[handle].append((ip, prefix))
            owned.append(record)
            return record

        load = mock.Mock(return_value=inventory)
        with mock.patch.object(lifecycle, "_STARTED", False), \
                mock.patch.object(lifecycle, "_LOADED_DEFAULTS", 0), \
                mock.patch.object(lifecycle.config_sync,
                                  "load_saved_defaults", return_value=0), \
                mock.patch.object(lifecycle.device_map, "load", load), \
                mock.patch.object(lifecycle.network, "sweep_stale",
                                  side_effect=lambda: events.append("sweep")), \
                mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases, "active", lambda: list(owned)), \
                mock.patch.object(aliases, "add", add), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            lifecycle.start()
            lifecycle.start()

        load.assert_called_once_with(1)
        self.assertEqual(events, ["sweep", "add:en6:10.1.1.225/24"])
        self.assertEqual(
            [(entry["handle"], entry["ip"], entry["prefix"])
             for entry in owned],
            [("en6", "10.1.1.225", 24)])

    def test_startup_does_not_guess_when_an_adapter_is_missing_or_ambiguous(self):
        from panel.api import lifecycle

        inventory = self._inventory()
        cases = {
            "missing": [],
            "ambiguous": [
                adapters.Adapter(name="en3", handle="en3",
                                 addresses=[("192.168.3.10", 24)], up=True),
                adapters.Adapter(name="en6", handle="en6",
                                 addresses=[("192.168.6.10", 24)], up=True),
            ],
        }
        for label, found in cases.items():
            with self.subTest(label=label):
                add = mock.Mock()
                with mock.patch.object(lifecycle, "_STARTED", False), \
                        mock.patch.object(lifecycle, "_LOADED_DEFAULTS", 0), \
                        mock.patch.object(lifecycle.config_sync,
                                          "load_saved_defaults",
                                          return_value=0), \
                        mock.patch.object(lifecycle.device_map, "load",
                                          return_value=inventory), \
                        mock.patch.object(lifecycle.network, "sweep_stale"), \
                        mock.patch.object(adapters, "list_adapters",
                                          return_value=found), \
                        mock.patch.object(aliases, "add", add), \
                        mock.patch.object(prepare.commands, "supported",
                                          lambda system=None: True):
                    lifecycle.start()
                add.assert_not_called()

    def test_nothing_is_added_when_everything_is_already_reachable(self):
        def list_adapters(system=None):
            return [adapters.Adapter(
                name="en5", handle="en5",
                addresses=[("10.17.1.222", 24), ("10.1.1.225", 24)], up=True)]

        run = FakeRun()
        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters), \
                mock.patch.object(aliases.interfaces, "run_command", run):
            result = prepare.ensure(self._inventory())
        self.assertEqual(result["added"], [])
        self.assertEqual(run.calls, [])

    def test_legacy_address_customisation_is_ignored(self):
        """The adapter is the only setting; aliases are always .225/24."""
        prepare.save_preferences({
            "adapter": "en5", "enabled": False, "octet": 77, "prefix": 16})
        values = prepare.preferences()
        self.assertEqual(values["adapter"], "en5")
        self.assertTrue(values["enabled"])
        self.assertEqual(values["octet"], planning.DEFAULT_HOST_OCTET)
        self.assertEqual(values["prefix"], planning.DEFAULT_PREFIX)
        stored = json.loads(
            settings.network_settings_file().read_text(encoding="utf-8"))
        self.assertEqual(stored, {"adapter": "en5"})

    def test_a_machine_with_no_adapter_is_not_a_question(self):
        """Nothing to add it to, and no click that would change that.

        Told apart from "pick one": `needsAdapter` stays false, so the screen
        says the machine has no usable adapter instead of asking a question
        with no answer.
        """
        def list_adapters(system=None):
            return []

        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters):
            result = prepare.ensure(self._inventory())
        self.assertEqual(result["added"], [])
        self.assertFalse(result["needsAdapter"])

    def test_declining_to_guess_is_not_reported_as_a_failure(self):
        """"No adapter" is a question, and it is asked in one place only.

        It used to land in `failed` as well, which printed a raw English
        "no adapter" under the translated question already on the screen —
        said twice, once in the wrong language.
        """
        def list_adapters(system=None):
            return [adapters.Adapter(name="en0", handle="en0",
                                     addresses=[("172.20.10.3", 28)], up=True)]

        with mock.patch.object(adapters, "list_adapters", list_adapters):
            result = prepare.ensure(self._inventory())
        self.assertTrue(result["needsAdapter"])
        self.assertEqual(result["failed"], [])

    def test_a_command_failure_is_reported_rather_than_raised(self):
        """The operation is still worth attempting; its own error says more."""
        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("10.17.1.222", 24)], up=True)]

        def run(argv, timeout=None):
            return 1, "ifconfig: ioctl (SIOCAIFADDR): permission denied"

        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.platform, "system",
                                  lambda: "Darwin"), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            result = prepare.ensure(self._inventory())
        self.assertEqual(result["added"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("permission denied", result["failed"][0]["error"])
        self.assertEqual(result["failed"][0]["network"], "10.1.1.0/24")

    def test_a_second_train_set_gets_its_own_address(self):
        """Set 14 means 10.14.1.225, on the same adapter, on the same pattern.

        The computer here is on no relevant network at all, so both the
        factory network and the set's own network have to be given one.
        """
        added: list[str] = []

        def list_adapters(system=None):
            return [adapters.Adapter(
                name="en5", handle="en5",
                addresses=[("192.168.1.44", 24)]
                + [(ip, 24) for ip in added], up=True)]

        def run(argv, timeout=None):
            if "alias" in argv:
                added.append(argv[argv.index("alias") + 1])
            return 0, ""

        topology = fakes.device_map([], switch_ip="10.14.1.100")
        inventory = self.build_map(topology)
        # No adapter holds either network, so the user has pinned one.
        prepare.save_preferences({"adapter": "en5"})

        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.platform, "system",
                                  lambda: "Darwin"), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            result = prepare.ensure(inventory)

        self.assertEqual(sorted(entry["ip"] for entry in result["added"]),
                         ["10.1.1.225", "10.14.1.225"])
        self.assertTrue(all(entry["prefix"] == 24
                            for entry in result["added"]))

    def test_changing_adapter_moves_only_the_panels_alias_to_the_new_one(self):
        """An alias on en3 must not make en6 look prepared already.

        This is the field regression: the application opened on en3 and added
        10.1.1.225 there; choosing en6 changed the label but no address moved,
        because the old alias made ``required_networks`` return an empty list.
        """
        inventory = self._inventory()
        prepare.save_preferences({"adapter": "en3"})
        addresses = {
            "en3": [("192.168.1.44", 24), ("10.1.1.225", 24)],
            # en6 is the cable to the switch and already has the set address.
            "en6": [("10.17.1.222", 24)],
        }
        owned = [{"ip": "10.1.1.225", "prefix": 24, "handle": "en3",
                  "adapter": "en3", "system": "Darwin", "pid": os.getpid()}]
        calls = []

        def list_adapters(system=None):
            return [adapters.Adapter(name=name, handle=name,
                                     addresses=list(items), up=True)
                    for name, items in addresses.items()]

        def remove(record, system=None):
            calls.append(("remove", record["handle"], record["ip"],
                          record["prefix"]))
            addresses[record["handle"]] = [
                item for item in addresses[record["handle"]]
                if item[0] != record["ip"]]
            owned.remove(record)
            return True

        def add(handle, ip, prefix, adapter_name="", system=None):
            calls.append(("add", handle, ip, prefix))
            record = {"ip": ip, "prefix": prefix, "handle": handle,
                      "adapter": adapter_name, "system": "Darwin",
                      "pid": os.getpid()}
            addresses[handle].append((ip, prefix))
            owned.append(record)
            return record

        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases, "active", lambda: list(owned)), \
                mock.patch.object(aliases, "remove", remove), \
                mock.patch.object(aliases, "add", add), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            result = prepare.select_adapter(inventory, "en6")

        self.assertEqual(calls, [
            ("remove", "en3", "10.1.1.225", 24),
            ("add", "en6", "10.1.1.225", 24),
        ])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["adapter"], "en6")
        self.assertEqual(result["added"][0]["prefix"], 24)
        self.assertEqual([(entry["handle"], entry["ip"]) for entry in owned],
                         [("en6", "10.1.1.225")])
        # The ordinary host address was never in aliases.active and stays put.
        self.assertIn(("192.168.1.44", 24), addresses["en3"])
        self.assertEqual(prepare.preferences()["adapter"], "en6")

    def test_adapter_selection_is_atomic_against_a_stale_ensure(self):
        """A scan started on en3 cannot add there after en6 is selected."""
        inventory = self._inventory()
        prepare.save_preferences({"adapter": "en3"})
        addresses = {
            "en3": [("10.17.1.221", 24)],
            "en6": [("10.17.1.222", 24)],
        }
        owned: list[dict] = []
        stale_at_snapshot = threading.Event()
        release_stale = threading.Event()
        selector_added = threading.Event()
        errors: list[BaseException] = []

        def list_adapters(system=None):
            return [adapters.Adapter(name=name, handle=name,
                                     addresses=list(items), up=True)
                    for name, items in addresses.items()]

        def active():
            if (threading.current_thread().name == "stale-network-ensure"
                    and not stale_at_snapshot.is_set()):
                stale_at_snapshot.set()
                if not release_stale.wait(2):
                    raise TimeoutError("stale ensure was not released")
            return list(owned)

        def add(handle, ip, prefix, adapter_name="", system=None):
            record = {"ip": ip, "prefix": prefix, "handle": handle,
                      "adapter": adapter_name, "system": "Darwin",
                      "pid": os.getpid()}
            addresses[handle].append((ip, prefix))
            owned.append(record)
            if threading.current_thread().name == "adapter-selector":
                selector_added.set()
            return record

        def remove(record, system=None):
            addresses[record["handle"]] = [
                item for item in addresses[record["handle"]]
                if item[0] != record["ip"]]
            owned.remove(record)
            return True

        def run_stale_ensure():
            try:
                prepare.ensure(inventory)
            except BaseException as exc:                 # test thread boundary
                errors.append(exc)

        def run_selection():
            try:
                prepare.select_adapter(inventory, "en6")
            except BaseException as exc:                 # test thread boundary
                errors.append(exc)

        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases, "active", active), \
                mock.patch.object(aliases, "add", add), \
                mock.patch.object(aliases, "remove", remove), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            stale = threading.Thread(target=run_stale_ensure,
                                     name="stale-network-ensure")
            selector = threading.Thread(target=run_selection,
                                        name="adapter-selector")
            selector_started = False
            overlapped = False
            try:
                stale.start()
                self.assertTrue(stale_at_snapshot.wait(1))
                selector.start()
                selector_started = True
                # Before the fix, selection ran past the stale calculation
                # and added on en6 while en3 was paused.  The transaction lock
                # keeps it outside until the stale call is complete.
                overlapped = selector_added.wait(0.5)
            finally:
                # Keep both test threads inside the fake network boundary even
                # when an assertion above fails: no cleanup path may reach the
                # developer machine's real adapter commands.
                release_stale.set()
                stale.join(2)
                if selector_started:
                    selector.join(2)

        self.assertFalse(stale.is_alive())
        self.assertFalse(selector.is_alive())
        self.assertFalse(overlapped)
        self.assertEqual(errors, [])
        self.assertEqual(prepare.preferences()["adapter"], "en6")
        self.assertEqual(
            [(entry["handle"], entry["ip"], entry["prefix"])
             for entry in owned],
            [("en6", "10.1.1.225", 24)])
        self.assertNotIn(("10.1.1.225", 24), addresses["en3"])

    def test_an_unknown_adapter_cannot_remove_the_current_alias(self):
        inventory = self._inventory()
        prepare.save_preferences({"adapter": "en3"})
        found = [adapters.Adapter(name="en3", handle="en3", up=True)]
        remove = mock.Mock()
        with mock.patch.object(adapters, "list_adapters", return_value=found), \
                mock.patch.object(aliases, "remove", remove):
            with self.assertRaises(ValueError):
                prepare.select_adapter(inventory, "en6")
        remove.assert_not_called()
        self.assertEqual(prepare.preferences()["adapter"], "en3")

    def test_reselecting_the_same_adapter_does_not_flap_its_alias(self):
        inventory = self._inventory()
        prepare.save_preferences({"adapter": "en6"})
        found = [adapters.Adapter(
            name="en6", handle="en6", up=True,
            addresses=[("10.17.1.222", 24), ("10.1.1.225", 24)])]
        remove, add = mock.Mock(), mock.Mock()
        with mock.patch.object(adapters, "list_adapters", return_value=found), \
                mock.patch.object(aliases, "remove", remove), \
                mock.patch.object(aliases, "add", add):
            result = prepare.select_adapter(inventory, "en6")
        remove.assert_not_called()
        add.assert_not_called()
        self.assertEqual(result["added"], [])

    def test_no_adapter_is_a_question_not_a_guess(self):
        """The phone hotspot must not be picked, and must not be prepared on."""
        def list_adapters(system=None):
            return [adapters.Adapter(name="en0", handle="en0",
                                     addresses=[("172.20.10.3", 28)], up=True)]

        run = FakeRun()
        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases.interfaces, "run_command", run):
            result = prepare.ensure(self._inventory())
            shown = prepare.state(self._inventory())

        self.assertEqual(result["added"], [])
        self.assertTrue(result["needsAdapter"])
        self.assertEqual(run.calls, [])
        # The screen asks rather than showing a wrong answer.
        self.assertIsNone(shown["adapter"])
        self.assertTrue(shown["needsAdapter"])

    def test_the_base_address_is_spelled_out_for_the_screen(self):
        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("10.1.1.225", 24)], up=True)]

        with mock.patch.object(adapters, "list_adapters", list_adapters):
            shown = prepare.state(self._inventory())
        self.assertEqual(shown["baseAddress"], "10.1.1.225/24")
        # An adapter already on the factory network answers the question, so
        # nothing is asked and nothing is guessed.
        self.assertEqual(shown["adapter"]["name"], "en5")
        self.assertFalse(shown["needsAdapter"])

    def test_a_legacy_settings_file_cannot_override_the_fixed_address_shape(self):
        settings.network_settings_file().write_text(json.dumps({
            "adapter": "en5", "octet": 99, "prefix": 16,
            "enabled": False}), encoding="utf-8")
        values = prepare.preferences()
        self.assertEqual(values["adapter"], "en5")
        self.assertTrue(values["enabled"])
        self.assertEqual(values["octet"], planning.DEFAULT_HOST_OCTET)
        self.assertEqual(values["prefix"], planning.DEFAULT_PREFIX)

    def test_every_job_that_talks_to_a_device_prepares_first(self):
        """A write cannot reach a device the computer has no route to.

        The scan and the assignment run always did this. Configuration and
        firmware did not, and an operator who changed set and went straight
        to one of them — or who had paused the automatic rounds — met
        "device unreachable" on every row for no visible reason.
        """
        import pathlib as _pathlib

        root = _pathlib.Path(settings.ROOT) / "panel" / "api" / "tasks"
        for name in ("scan_task.py", "ip_task.py", "config_task.py",
                     "firmware_task.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertIn("prepare_network(job", source, name)

    def test_a_train_set_needs_two_networks_not_one(self):
        """The field case this whole package exists for.

        The operator opens set 8. Every device is still on the address it
        left the factory on — 10.1.1.x, the same for every set — while the
        switches and the addresses about to be written are 10.8.1.x. Both
        have to be reachable, and a laptop on the depot's own network is in
        neither.
        """
        topology = fakes.device_map(
            [{"Name": "Compartment_Lcd_1", "Type": "LCD",
              "SubType": "Compartment", "IP": "10.n.1.40", "Port": 13,
              "IsActive": True}],
            switch_ip="10.n.1.100", switch_name="Yatakli_1")
        self.build_map(topology)
        inventory = device_map.load(8, self.map_path, cache=False)

        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("10.17.1.222", 24)],
                                     up=True)]

        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters):
            found = prepare.readiness(inventory)

        self.assertEqual(sorted(found["missing"]),
                         ["10.1.1.0/24", "10.8.1.0/24"])

    def test_not_knowing_the_adapter_is_reported_as_its_own_answer(self):
        """Missing networks are routine — the run adds them itself. Not
        knowing WHICH card to add them to is not: nothing is added and every
        port fails with "device not found", which is what the IP screen has
        to say before the button is pressed rather than after."""
        def list_adapters(system=None):
            # Up and usable, but nowhere near the devices: the laptop is on
            # the depot network, or on a phone's hotspot.
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("192.168.4.20", 24)],
                                     up=True)]

        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters):
            found = prepare.readiness(self._inventory())

        self.assertTrue(found["needsAdapter"])
        self.assertEqual(found["adapter"], "")

    def test_a_choice_that_cannot_be_saved_is_reported_not_swallowed(self):
        """Picking the interface is the one thing the panel cannot work out
        for itself. Losing that answer quietly — the screen saying it was
        chosen while nothing was written — means the next start asks again
        with nothing on screen to explain why."""
        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("10.17.1.222", 24)],
                                     up=True)]

        def refuse(*_args, **_kwargs):
            raise PermissionError(13, "Permission denied")

        with (mock.patch.object(prepare.adapter_module, "list_adapters",
                                list_adapters),
              mock.patch.object(prepare.settings, "network_settings_file",
                                side_effect=refuse)):
            result = prepare.select_adapter(self._inventory(), "en5")

        reasons = " ".join(entry["error"] for entry in result["failed"])
        self.assertIn("Permission denied", reasons)

    def test_a_pinned_adapter_settles_it_for_good(self):
        prepare.save_preferences({"adapter": "en5"})

        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("192.168.4.20", 24)],
                                     up=True)]

        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters):
            found = prepare.readiness(self._inventory())

        self.assertFalse(found["needsAdapter"])
        self.assertEqual(found["adapter"], "en5")

    def test_the_screen_and_the_run_agree_on_what_is_missing(self):
        def list_adapters(system=None):
            return [adapters.Adapter(name="en5", handle="en5",
                                     addresses=[("10.17.1.222", 24)],
                                     up=True)]

        with mock.patch.object(prepare.adapter_module, "list_adapters",
                               list_adapters):
            shown = prepare.state(self._inventory())
        self.assertEqual([entry["network"] for entry in shown["required"]],
                         ["10.1.1.0/24"])
        self.assertEqual(shown["adapter"]["name"], "en5")
        self.assertTrue(shown["supported"])


class ServiceRoutes(AllowsWrites, PanelTest):
    """The API surface the Network screen talks to."""

    def setUp(self):
        super().setUp()
        self.allow_writes()
        self.addCleanup(aliases.release_all)

    def test_the_state_endpoint_answers_with_the_whole_picture(self):
        from panel import api

        self.build_map(fakes.device_map([], switch_ip="10.17.1.100"))
        response = api.call("GET", "/api/network?set=17")
        self.assertEqual(response.status, 200)
        for key in ("supported", "system", "adapters", "preferences",
                    "required", "aliases"):
            self.assertIn(key, response.body)

    def test_picking_an_adapter_prepares_in_the_same_request(self):
        """One click is the whole interaction.

        The panel does not guess which cable reaches the switch, so naming it
        is the only thing it was waiting for; a second button afterwards would
        be asking the user to confirm what they just said.
        """
        from panel import api

        self.build_map(fakes.device_map([], switch_ip="10.17.1.100"))
        added: list[str] = []

        def list_adapters(system=None):
            return [adapters.Adapter(
                name="en5", handle="en5",
                addresses=[("192.168.1.44", 24)]
                + [(ip, 24) for ip in added], up=True)]

        def run(argv, timeout=None):
            if "alias" in argv:
                added.append(argv[argv.index("alias") + 1])
            return 0, ""

        with mock.patch.object(adapters, "list_adapters", list_adapters), \
                mock.patch.object(aliases.interfaces, "run_command", run), \
                mock.patch.object(aliases.platform, "system",
                                  lambda: "Darwin"), \
                mock.patch.object(prepare.commands, "supported",
                                  lambda system=None: True):
            response = api.call("POST", "/api/network/settings",
                                body={"adapter": "en5", "set": 17})

        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["added"])
        self.assertIn("10.1.1.225",
                      [entry["ip"] for entry in response.body["added"]])

    def test_legacy_address_settings_are_ignored_by_the_route(self):
        from panel import api, network

        picture = {"preferences": dict(prepare.DEFAULTS), "aliases": []}
        result = {"added": [], "failed": [], "required": [],
                  "needsAdapter": False}
        with mock.patch.object(network, "ensure", return_value=result), \
                mock.patch.object(network, "state", return_value=picture):
            response = api.call("POST", "/api/network/settings", body={
                "set": 17, "octet": 1, "prefix": 8, "enabled": False})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["preferences"]["octet"],
                         planning.DEFAULT_HOST_OCTET)
        self.assertEqual(response.body["preferences"]["prefix"], 24)
        self.assertTrue(response.body["preferences"]["enabled"])

    def test_an_unknown_adapter_is_refused_before_any_alias_is_removed(self):
        from panel import api

        self.build_map(fakes.device_map([], switch_ip="10.17.1.100"))
        found = [adapters.Adapter(name="en3", handle="en3", up=True)]
        remove = mock.Mock()
        with mock.patch.object(adapters, "list_adapters", return_value=found), \
                mock.patch.object(aliases, "remove", remove):
            response = api.call("POST", "/api/network/settings",
                                body={"adapter": "en6", "set": 17})
        self.assertEqual(response.status, 400)
        remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()


# ────────────────────────────────────── an address for a named network ─────
class EnsureNamedNetwork(AllowsWrites, PanelTest):
    """`ensure_network` — the switch screen's own network preparation.

    `ensure()` reads what the PROJECT needs out of the DeviceMap. The switch
    screen has no project: it sweeps a network the operator typed, which may
    be one nothing in the inventory mentions. Without an address on it the
    sweep finds nothing at all, and the empty result is indistinguishable from
    "there are no switches here" — no packet ever left the machine.
    """

    def setUp(self):
        super().setUp()
        self.allow_writes()
        self.added = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(
            aliases, "add",
            side_effect=lambda handle, ip, prefix, adapter_name="", **k: (
                self.added.append((handle, ip, prefix)) or
                {"ip": ip, "prefix": prefix, "adapter": adapter_name})))
        self.stack.enter_context(mock.patch.object(
            aliases, "active", return_value=[]))

    def with_adapters(self, found):
        self.stack.enter_context(mock.patch.object(
            adapters, "list_adapters", return_value=found))

    def choose_adapter(self, name):
        """Stand in for the choice made on the Network screen."""
        self.stack.enter_context(mock.patch.object(
            prepare, "preferences",
            return_value={"adapter": name, "search": [], "factoryIp": ""}))

    def test_an_address_is_added_on_the_chosen_adapter(self):
        """With an interface chosen, the panel puts itself on the network.

        The choice is what makes this possible at all: `adapters.choose` picks
        an interface that is ALREADY on the target network, and for a network
        the machine is not on there is by definition no such interface. So
        this path needs the operator's answer, and the next test is what
        happens without it.
        """
        self.with_adapters([adapters.Adapter(
            name="Ethernet", handle="en5", addresses=[("10.1.1.4", 24)],
            up=True)])
        self.choose_adapter("en5")
        result = prepare.ensure_network(ipaddress.IPv4Network("10.9.9.0/24"))
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(self.added[0][0], "en5")
        self.assertTrue(self.added[0][1].startswith("10.9.9."))
        self.assertEqual(self.added[0][2], 24)

    def test_nothing_is_added_when_it_is_already_reachable(self):
        """An address the computer holds is a route it has, whoever put it
        there. Adding a second would be noise on the interface."""
        self.with_adapters([adapters.Adapter(
            name="Ethernet", handle="en5", addresses=[("10.1.1.4", 24)])])
        result = prepare.ensure_network(ipaddress.IPv4Network("10.1.1.0/24"))
        self.assertEqual(result["added"], [])
        self.assertEqual(self.added, [])

    def test_it_declines_to_guess_which_cable_reaches_the_switches(self):
        """No adapter already on the target network and none chosen.

        The panel does not rank interfaces — a laptop tethered to a phone had
        the address put on the phone. `needsAdapter` sends the question to the
        Network screen instead.
        """
        self.with_adapters([adapters.Adapter(
            name="Wi-Fi", handle="en0", addresses=[("192.168.1.20", 24)],
            up=True)])
        result = prepare.ensure_network(ipaddress.IPv4Network("10.9.9.0/24"))
        self.assertEqual(result["added"], [])
        self.assertTrue(result["needsAdapter"])

    def test_no_network_is_not_an_error(self):
        """`target_network` returns None for an expression it cannot read."""
        self.assertEqual(prepare.ensure_network(None)["added"], [])

    def test_a_failed_write_is_reported_not_raised(self):
        """The sweep still runs: the computer may have a route this cannot
        see, and the empty result says more than a guess here."""
        self.with_adapters([adapters.Adapter(
            name="Ethernet", handle="en5", addresses=[("10.1.1.4", 24)],
            up=True)])
        self.choose_adapter("en5")
        self.stack.enter_context(mock.patch.object(
            aliases, "add", side_effect=RuntimeError("ifconfig refused")))
        result = prepare.ensure_network(ipaddress.IPv4Network("10.9.9.0/24"))
        self.assertEqual(result["added"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("ifconfig", result["failed"][0]["error"])
