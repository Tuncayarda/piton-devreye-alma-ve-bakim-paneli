#!/usr/bin/env python3
"""Switch access — the same behaviour as the Switch Management Panel.

Covered requirements:
  1. An account that works in the Switch Management Panel verifies here too.
  2. A wrong switch password is not accepted as success.
  3. Login HTML returned with HTTP 200 is not accepted as switch data.
 11. Two switches with the same name and different IPs are not confused.
"""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from panel import credentials, i18n, ip_assign, script_loader, status
from panel.errors import AuthError, VerificationError
from panel.probe import reader
from panel.probe import switch as switch_probe
from panel.system import interfaces

from .support import fakes
from .support.base import PanelTest


class SwitchAccess(PanelTest):

    def test_1_a_correct_account_works_in_both_panels(self):
        """The same account must verify in the sibling backend and here.

        Both applications go through one code path: switch_api.sw_get. The
        test does not merely assert that; it asks both against the same fake
        switch and shows the results are identical.
        """
        with fakes.kyland(username="admin", password="123") as switch:
            self.switch_port(switch.port)
            api = switch_probe.api()

            # The Switch Management Panel's own path
            theirs = api.is_switch("127.0.0.1", timeout=5,
                                   credentials=("admin", "123"))
            self.assertIsNotNone(theirs)
            self.assertFalse(theirs["locked"])

            # This panel's path
            ours = switch_probe.read("127.0.0.1", ("admin", "123"))

            self.assertEqual(theirs["model"], ours["model"])
            self.assertEqual(theirs["version"], ours["version"])
            self.assertEqual(theirs["mac"], ours["mac"])
            self.assertEqual(ours["version"], "F6014")

    def test_uptime_is_computed_from_the_operatetime_field(self):
        """KYLAND exposes no single uptime field; it arrives split."""
        compute = switch_probe.uptime_seconds
        self.assertEqual(
            compute({"operateTime": {"day": "1", "hour": "2",
                                     "minute": "3", "second": "4"}}),
            86400 + 2 * 3600 + 3 * 60 + 4)
        # A device with a single field uses that
        self.assertEqual(compute({"upTime": 90}), 90)
        # With no field, no value is invented
        self.assertIsNone(compute({"deviceName": "SWITCH"}))
        self.assertIsNone(compute({"operateTime": "07:30:39"}))

        with fakes.kyland(username="admin", password="123") as switch:
            self.switch_port(switch.port)
            data = switch_probe.read("127.0.0.1", ("admin", "123"))
            self.assertEqual(data["uptime"], 86400 + 2 * 3600 + 3 * 60 + 4)
            inventory = self.build_map(
                fakes.device_map([], switch_ip="127.0.0.1"))
            result = reader.read_device(inventory.switches()[0],
                                        credentials=("admin", "123"))
            self.assertEqual(result.fields["uptime"], "26:03:04")

    def test_2_a_wrong_password_is_not_a_success(self):
        with fakes.kyland(password="123") as switch:
            self.switch_port(switch.port)
            with self.assertRaises(AuthError):
                switch_probe.read("127.0.0.1", ("admin", "yanlis"))
            # No credentials falls into the same class
            with self.assertRaises(AuthError):
                switch_probe.read("127.0.0.1", None)

    def test_3_login_html_is_not_switch_data(self):
        """Even with the right password, 200 + HTML is not a success.

        What the user is told is the panel's own sentence, not the field
        script's: that one is untranslatable English from a borrowed file.
        A login page and a plain 401 therefore read the same on screen, which
        is right — both mean "sign in", and the user does the same thing.
        """
        with fakes.kyland(login_page=True) as switch:
            self.switch_port(switch.port)
            with self.assertRaises(AuthError) as caught:
                switch_probe.read("127.0.0.1", ("admin", "123"))
            self.assertEqual(str(caught.exception), i18n.t("error.probeAuth"))

    def test_3b_unexpected_json_is_not_accepted_either(self):
        """200 + valid JSON but no switch identity does not verify."""
        with fakes.empty_json_switch() as switch:
            self.switch_port(switch.port)
            with self.assertRaises(VerificationError):
                switch_probe.read("127.0.0.1", ("admin", "123"))

    def test_11_switches_with_the_same_name_are_not_confused(self):
        """Two switches carrying one name still keep separate identities."""
        topology = fakes.device_map([], switch_ip="127.0.0.1",
                                    switch_name="Yatakli_1")
        topology["Switches"].append({
            "Name": "Yatakli_1",              # DELIBERATELY the same name
            "IP": "127.0.0.2", "IsActive": True, "Manufacturer": "KYLAND",
            "TrainSet": 1, "Status": {"NoError": True}, "Devices": [],
        })
        inventory = self.build_map(topology)

        first, second = inventory.switches()
        self.assertEqual(first.name, second.name)
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.ip, second.ip)
        self.assertNotEqual(first.match_key, second.match_key)

        credentials.remember(first.id, first.ip, "admin", "first-password")
        self.assertEqual(credentials.lookup(first.id, first.ip),
                         ("admin", "first-password"))
        # The second has no credential of its own and does NOT inherit one
        self.assertIsNone(credentials.lookup(second.id, second.ip))

        # Separate rows in the view too
        ids = {device.id for device in inventory.devices}
        self.assertEqual(len(ids), len(inventory.devices))

    def test_11b_a_group_credential_spreads_only_when_asked(self):
        topology = fakes.device_map([], switch_ip="127.0.0.1",
                                    switch_name="A")
        topology["Switches"].append({
            "Name": "B", "IP": "127.0.0.2", "IsActive": True,
            "TrainSet": 1, "Status": {}, "Devices": [],
        })
        inventory = self.build_map(topology)
        a, b = inventory.switches()

        credentials.remember(a.id, a.ip, "admin", "p1", group="switch",
                             share_with_group=False)
        self.assertIsNone(credentials.lookup(b.id, b.ip, group="switch"))

        credentials.remember(a.id, a.ip, "admin", "p1", group="switch",
                             share_with_group=True)
        self.assertEqual(credentials.lookup(b.id, b.ip, group="switch"),
                         ("admin", "p1"))

    def test_the_probe_layer_turns_a_switch_result_green(self):
        topology = fakes.device_map([], switch_ip="127.0.0.1")
        inventory = self.build_map(topology)
        switch_device = inventory.switches()[0]
        with fakes.kyland() as switch:
            self.switch_port(switch.port)
            result = reader.read_device(switch_device,
                                        credentials=("admin", "123"))
            self.assertEqual(result.state, status.OK)
            self.assertEqual(result.fields["version"], "F6014")

            wrong = reader.read_device(switch_device,
                                       credentials=("admin", "yok"))
            self.assertEqual(wrong.state, status.AUTH)
            self.assertEqual(wrong.verification, status.AUTH_REQUIRED)


class ProtectedPorts(PanelTest):
    """Ports the run must not touch are found from the MAC tables.

    Neither the computer's location nor the inter-switch link is asked for: as
    long as it was typed in, a wrong answer did damage twice — a port that
    needed protecting was not protected, and a port that did not need it was
    dropped from the run. In the field some switches are not up, so the user
    does not know the answer to "which one are you on?" either.
    """

    ACCOUNT = ("admin", "123")

    def _inventory(self, switch_count=1):
        topology = fakes.device_map([], switch_ip="127.0.0.1")
        for i in range(switch_count - 1):
            topology["Switches"].append({
                "Name": f"Kapali_SW_{i + 2}", "IP": "127.0.0.2",
                "Type": "Switch", "IsActive": True, "Devices": [],
            })
        return self.build_map(topology)

    def _credentials(self, _device):
        return self.ACCOUNT

    def _local_macs(self):
        macs = [entry["mac"] for entry in interfaces.list_interfaces()]
        if not macs:
            self.skipTest("this machine has no readable network interface")
        return macs

    def test_the_local_mac_is_found_in_the_switch_table(self):
        inventory = self._inventory()
        macs = self._local_macs()
        # As if one of the machine's real MACs sat on port 17.
        table = {macs[0]: 17, "aa:bb:cc:dd:ee:01": 3}
        with fakes.kyland(mac_table=table) as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        computer = found["computer"]
        self.assertEqual(computer["port"], 17)
        self.assertEqual(computer["source"], "mac")
        self.assertEqual(computer["mac"], macs[0])
        self.assertEqual(computer["switchId"], inventory.switches()[0].id)
        self.assertIn({"switchId": computer["switchId"],
                       "switchName": computer["switchName"],
                       "port": 17, "kind": "computer",
                       "reason": "the computer is on this port"}, found["ports"])

    def test_a_switch_that_is_down_does_not_end_the_search(self):
        """If one switch is off, the others are still looked at.

        In the field switch 1 may not be installed yet; that is the whole
        point of not asking the user which one they are connected to.
        """
        inventory = self._inventory(switch_count=2)
        macs = self._local_macs()
        # The reachable switch is the SECOND in the list; the first is silent.
        switches = inventory.switches()
        switches[0].ip, switches[1].ip = "127.0.0.2", "127.0.0.1"
        with fakes.kyland(mac_table={macs[0]: 5}) as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        self.assertEqual(found["computer"]["port"], 5)
        self.assertEqual(found["computer"]["switchId"], switches[1].id)

    def _two_switches(self, tables, own_macs):
        """Replaces the switch probe with fixed answers per IP.

        Two fake switches would listen on separate TCP ports, but switch_api
        uses one global `SWITCH_PORT`; there is no way to talk to both over
        real HTTP. The interest here is not HTTP anyway, but how
        `protected_ports` reads the two tables.
        """
        from panel.ip_assign import ports as ports_module

        inventory = self._inventory(switch_count=2)
        a, b = inventory.switches()
        a.ip, b.ip = "10.0.0.1", "10.0.0.2"
        by_ip = dict(zip((a.ip, b.ip), tables))
        macs = dict(zip((a.ip, b.ip), own_macs))
        patches = [
            mock.patch.object(ports_module.switch_probe, "mac_table",
                              lambda ip, c=None, timeout=None: by_ip[ip]),
            mock.patch.object(ports_module.switch_probe, "read",
                              lambda ip, c=None, timeout=None: {
                                  "mac": macs[ip]}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return inventory, a, b

    def test_an_uplink_port_is_not_mistaken_for_the_computer_port(self):
        """The computer's MAC shows up in the neighbour's table TOO.

        The neighbour learns it on its own uplink. Going by list order would
        pick the wrong switch; what tells them apart is the number of MACs
        learned on the port — an access port has one device, an uplink has
        everything behind that switch.
        """
        pc = self._local_macs()[0]
        # a (first in the list): PC on uplink port 25, with many MACs beside.
        # b: PC directly on p7, no other MAC on that port.
        inventory, a, b = self._two_switches(
            [{pc: 25, "aa:bb:cc:00:00:01": 25, "aa:bb:cc:00:00:02": 25},
             {pc: 7, "aa:bb:cc:00:00:09": 11}],
            ["00:11:22:33:44:01", "00:11:22:33:44:02"])

        found = ip_assign.protected_ports(inventory, self._credentials)

        self.assertEqual(found["computer"]["switchId"], b.id)
        self.assertEqual(found["computer"]["port"], 7)
        # a's uplink is protected too — the run passes through it — but as a
        # "link", not as the "computer port".
        kinds = {(p["switchId"], p["port"]): p["kind"] for p in found["ports"]}
        self.assertEqual(kinds[(b.id, 7)], "computer")
        self.assertEqual(kinds[(a.id, 25)], "link")

    def test_the_inter_switch_link_is_found_from_the_neighbours_mac(self):
        """Wherever the neighbour's OWN MAC sits in our table, that is the
        uplink.

        Switch-to-switch links off the computer's path are only found so.
        """
        pc = self._local_macs()[0]
        a_mac, b_mac = "00:11:22:33:44:01", "00:11:22:33:44:02"
        # PC directly on a (p3). a and b are linked 26 ↔ 27; b's table has no
        # PC entry at all (never learned it).
        inventory, a, b = self._two_switches(
            [{pc: 3, b_mac: 26}, {a_mac: 27}],
            [a_mac, b_mac])

        found = ip_assign.protected_ports(inventory, self._credentials)

        self.assertEqual(found["computer"]["switchId"], a.id)
        self.assertEqual(found["computer"]["port"], 3)
        kinds = {(p["switchId"], p["port"]): p["kind"] for p in found["ports"]}
        self.assertEqual(kinds[(a.id, 3)], "computer")
        self.assertEqual(kinds[(a.id, 26)], "link")
        self.assertEqual(kinds[(b.id, 27)], "link")

    def test_a_link_is_not_invented_when_the_neighbour_is_silent(self):
        inventory = self._inventory(switch_count=2)
        macs = self._local_macs()
        inventory.switches()[1].ip = "127.0.0.2"     # the second is down
        with fakes.kyland(mac_table={macs[0]: 3, "aa:bb:cc:dd:ee:77": 26},
                          mac="00:11:22:33:44:55") as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        # The neighbour is down and cannot give its own MAC: p26 MAY be a
        # link, but we do not know that — it is not guessed.
        self.assertEqual([p["port"] for p in found["ports"]], [3])
        self.assertEqual(found["ports"][0]["kind"], "computer")

    def test_a_port_is_not_invented_when_absent_from_the_mac_table(self):
        inventory = self._inventory()
        with fakes.kyland(mac_table={"aa:bb:cc:dd:ee:01": 3}) as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        self.assertIsNone(found["computer"]["port"])
        self.assertEqual(found["ports"], [])
        self.assertTrue(found["computer"]["note"])

    def test_a_switch_without_a_table_is_not_found_rather_than_an_error(self):
        """A switch with no MAC endpoints must not lock the screen."""
        inventory = self._inventory()
        with fakes.kyland() as switch:            # no mac_table -> 404
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        self.assertIsNone(found["computer"]["port"])
        self.assertEqual(found["ports"], [])

    def test_a_switch_without_credentials_says_why(self):
        inventory = self._inventory()
        with fakes.kyland(mac_table={"aa:bb:cc:dd:ee:01": 3}) as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, lambda d: None)
        self.assertIsNone(found["computer"]["port"])
        # The state is a stable CODE; the note is that code rendered in
        # the current language (see ip_assign.ports.switch_state_label).
        self.assertEqual([entry["state"] for entry in found["tried"]],
                         ["auth"])
        self.assertIn(i18n.t("ip.switchStateAuth"), found["note"])

    def test_mac_normalisation_is_format_independent(self):
        """A switch may use upper case and dashes; matching must still hold."""
        inventory = self._inventory()
        macs = self._local_macs()
        reformatted = macs[0].replace(":", "-").upper()
        with fakes.kyland(mac_table={reformatted: 9}) as switch:
            self.switch_port(switch.port)
            found = ip_assign.protected_ports(inventory, self._credentials)
        self.assertEqual(found["computer"]["port"], 9)


class LocalNetwork(unittest.TestCase):
    """Interface dump parsing — by pattern, not by label."""

    WINDOWS = (
        "Windows IP Yapilandirmasi\n"
        "\n"
        "Ethernet adapter Ethernet:\n"
        "   Fiziksel Adres. . . . . . . . . : 00-11-22-33-44-55\n"
        "   IPv4 Adresi . . . . . . . . . . : 10.1.1.50(Tercih Edilen)\n"
        "\n"
        "Kablosuz LAN adapter Wi-Fi:\n"
        "   Fiziksel Adres. . . . . . . . . : AA-BB-CC-DD-EE-FF\n"
        "   IPv4 Adresi . . . . . . . . . . : 192.168.1.5(Tercih Edilen)\n"
    )
    MACOS = (
        "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n"
        "\tinet 127.0.0.1 netmask 0xff000000\n"
        "en0: flags=8863<UP,BROADCAST> mtu 1500\n"
        "\tether 3c:22:fb:11:22:33\n"
        "\tinet 10.1.1.50 netmask 0xffff0000\n"
        "en5: flags=8863<UP,BROADCAST> mtu 1500\n"
        "\tether 3c:22:fb:44:55:66\n"
        "\tinet 10.1.1.5 netmask 0xffff0000\n"
    )

    def test_windows_parses_with_turkish_labels_too(self):
        blocks = interfaces._blocks(self.WINDOWS)
        macs = [interfaces._block_mac(b) for b in blocks]
        self.assertIn("00:11:22:33:44:55", macs)
        self.assertIn("aa:bb:cc:dd:ee:ff", macs)

    def test_ip_matching_does_not_trip_over_a_longer_address(self):
        """Searching 10.1.1.5 must not pick 10.1.1.50's interface."""
        blocks = interfaces._blocks(self.MACOS)
        found = [{"mac": interfaces._block_mac(b),
                  "addresses": interfaces._IPV4_PATTERN.findall(b)}
                 for b in blocks]
        matching = [e for e in found if "10.1.1.5" in e["addresses"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["mac"], "3c:22:fb:44:55:66")

    def test_normalize_mac_unifies_the_formats(self):
        for raw in ("5c-1-3b-8A-76-43", "5c01.3b8a.7643", "5C:01:3B:8A:76:43"):
            self.assertEqual(interfaces.normalize_mac(raw),
                             "5c:01:3b:8a:76:43")
        self.assertEqual(interfaces.normalize_mac("none"), "")
        self.assertEqual(interfaces.normalize_mac(None), "")


# `ipconfig /all` output on Turkish Windows — WITH TURKISH LETTERS.
# The WINDOWS sample above was simplified to ASCII ("Yapilandirmasi") and the
# real fault hid exactly there: the console writes this text in the OEM code
# page (cp857), Python with `text=True` uses the ANSI code page (cp1254), and
# the byte for "ı" is undefined in cp1254.
IPCONFIG_TR = (
    "Windows IP Yapılandırması\n"
    "\n"
    "   Ana Bilgisayar Adı . . . . . . . : DEVREYE-PC\n"
    "\n"
    "Ethernet bağdaştırıcısı Ethernet:\n"
    "\n"
    "   Bağlantıya özgü DNS Soneki . . . :\n"
    "   Açıklama. . . . . . . . . . . . . : Intel(R) I219-LM\n"
    "   Fiziksel Adres. . . . . . . . . . : 5C-01-3B-8A-76-43\n"
    "   DHCP Etkin. . . . . . . . . . . . : Hayır\n"
    "   IPv4 Adresi . . . . . . . . . . . : 10.1.1.50(Tercih Edilen)\n"
    "   Alt Ağ Maskesi  . . . . . . . . . : 255.255.0.0\n"
    "   Varsayılan Ağ Geçidi. . . . . . . : 10.1.1.101\n"
)


class FakeCommand:
    """Stands in for subprocess.run; returns ready-made BYTE output."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        return subprocess.CompletedProcess(argv, 0, self.raw, b"")


class WindowsCodePage(unittest.TestCase):
    """Console output arrives in the OEM code page, not ANSI.

    Seen in the field: on Windows the computer's switch port was never found
    and the protected port list stayed empty. macOS had no problem — there
    both the output and the preferred code page are UTF-8.
    """

    def test_text_true_would_break_on_turkish_output(self):
        """The fault itself: cp857 bytes cannot be decoded as cp1254.

        This is what `text=True` does on Turkish Windows, and the
        UnicodeDecodeError it raises is neither OSError nor SubprocessError —
        the old `except` missed it and the exception escaped to the API.
        """
        raw = IPCONFIG_TR.encode("cp857")
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("cp1254")
        self.assertNotIsInstance(
            UnicodeDecodeError("cp1254", b"", 0, 1, ""),
            (OSError, subprocess.SubprocessError))

    def test_oem_output_is_decoded_and_the_mac_is_found(self):
        command = FakeCommand(IPCONFIG_TR.encode("cp857"))
        with mock.patch.object(interfaces.sys, "platform", "win32"), \
                mock.patch.object(interfaces, "_CODE_PAGE", "cp857"), \
                mock.patch.object(interfaces.subprocess, "run", command):
            found = interfaces.list_interfaces()
        macs = [entry["mac"] for entry in found]
        self.assertIn("5c:01:3b:8a:76:43", macs)
        addresses = [a for entry in found for a in entry["addresses"]]
        self.assertIn("10.1.1.50", addresses)

    def test_no_code_page_raises(self):
        """Whatever the code page, the decode step must not blow up.

        An undecodable byte becomes a "wrong letter"; everything looked for
        (MAC, IPv4) is ASCII, so parsing is unaffected.
        """
        for code in ("cp1254", "utf-8", "latin-1", "cp857"):
            with mock.patch.object(interfaces, "_CODE_PAGE", code):
                text = interfaces.decode(IPCONFIG_TR.encode("cp857"))
            self.assertIn("5C-01-3B-8A-76-43", text, code)

    def test_an_unknown_code_page_falls_back_to_latin1(self):
        with mock.patch.object(interfaces, "_CODE_PAGE", "no-such-code-page"):
            text = interfaces.decode(IPCONFIG_TR.encode("cp857"))
        self.assertIn("5C-01-3B-8A-76-43", text)

    def test_no_console_window_opens_on_windows(self):
        """In a console-less build every command flashed a window."""
        command = FakeCommand(b"")
        with mock.patch.object(interfaces, "_NO_WINDOW",
                               {"creationflags": 0x08000000}), \
                mock.patch.object(interfaces.subprocess, "run", command):
            interfaces._run(["ipconfig", "/all"])
        self.assertEqual(command.calls[0]["creationflags"], 0x08000000)
        # `text=True` must never be used again: leaving the decode to Python
        # was the fault itself.
        self.assertNotIn("text", command.calls[0])


class WindowsArp(unittest.TestCase):
    """The IP assignment run's ARP step never worked on Windows.

    Because every device arrives with the same factory address, the run has to
    refresh the ARP entry on each port change; failing that, the probe goes to
    the old MAC and the device counts as "not found".
    """

    def setUp(self):
        self.module = script_loader.intercom_ip_assign()

    def _windows(self, admin: bool):
        return (mock.patch.object(self.module, "WINDOWS", True),
                mock.patch.object(self.module, "is_admin", lambda: admin))

    def test_windows_is_not_unconditionally_treated_as_unprivileged(self):
        """The fault: `os.geteuid` does not exist on Windows, the
        AttributeError was caught and read as "no privilege". Started as
        administrator, the ARP cache was still never flushed."""
        p1, p2 = self._windows(admin=True)
        with p1, p2:
            self.assertTrue(self.module.can_flush_arp())

    def test_without_administrator_on_windows_there_is_no_privilege(self):
        p1, p2 = self._windows(admin=False)
        with p1, p2:
            self.assertFalse(self.module.can_flush_arp())

    def test_the_windows_hint_does_not_suggest_sudo(self):
        """There is no `sudo` on Windows; the advice must be actionable."""
        with mock.patch.object(self.module, "WINDOWS", True):
            hint = self.module.arp_permission_hint()
        self.assertIn("administrator", hint)
        self.assertNotIn("sudo", hint)

    def test_the_posix_hint_is_unchanged(self):
        with mock.patch.object(self.module, "WINDOWS", False):
            self.assertIn("sudo -v", self.module.arp_permission_hint())

    def test_windows_delete_commands_use_neither_sudo_nor_ip_neigh(self):
        with mock.patch.object(self.module, "WINDOWS", True):
            commands = self.module._arp_delete_commands("10.1.1.12")
        flat = [" ".join(c) for c in commands]
        self.assertIn("arp -d 10.1.1.12", flat)
        self.assertTrue(any("netsh" in c for c in flat), flat)
        # `sudo` and `ip neigh` do not exist on Windows. ("neigh" alone is not
        # searched for: the netsh command itself says "neighbors".)
        self.assertFalse(any(c.startswith("sudo") or c.startswith("ip neigh")
                             for c in flat), flat)

    def test_host_mac_reads_the_windows_dash_format(self):
        """Windows `arp -a` writes the MAC with dashes and has no `-n`
        option. Neither was handled, so MAC-based port verification silently
        never ran on Windows."""
        output = (
            "Arabirim: 10.1.1.50 --- 0xb\n"
            "  Internet Adresi       Fiziksel Adres        Tür\n"
            "  10.1.1.12             5c-01-3b-53-a4-73     dinamik\n"
        ).encode("cp857")
        command = FakeCommand(output)
        with mock.patch.object(self.module, "WINDOWS", True), \
                mock.patch.object(self.module, "_CODE_PAGE", "cp857"), \
                mock.patch.object(self.module.subprocess, "run", command):
            mac = self.module.host_mac("10.1.1.12")
        self.assertEqual(mac, "5c:01:3b:53:a4:73")
        self.assertEqual(command.calls[0]["argv"],
                         ["arp", "-a", "10.1.1.12"])

    def test_the_posix_host_mac_format_is_unbroken(self):
        output = (b"? (10.1.1.12) at 5c:01:3b:53:a4:73 on en6 ifscope "
                  b"[ethernet]\n")
        command = FakeCommand(output)
        with mock.patch.object(self.module, "WINDOWS", False), \
                mock.patch.object(self.module.subprocess, "run", command):
            mac = self.module.host_mac("10.1.1.12")
        self.assertEqual(mac, "5c:01:3b:53:a4:73")
        self.assertEqual(command.calls[0]["argv"],
                         ["arp", "-n", "10.1.1.12"])

    def test_command_output_never_raises_on_any_byte(self):
        """An undecodable byte must produce a wrong letter, not an exception."""
        command = FakeCommand(bytes(range(256)))
        for code in ("cp1254", "utf-8", "oem", "no-such-code-page"):
            with mock.patch.object(self.module, "_CODE_PAGE", code), \
                    mock.patch.object(self.module.subprocess, "run", command):
                status_code, text = self.module.command_output(["arp", "-a"])
            self.assertEqual(status_code, 0, code)
            self.assertIsInstance(text, str)

    def test_an_unrunnable_command_returns_none(self):
        def explode(*a, **k):
            raise FileNotFoundError("netsh yok")

        with mock.patch.object(self.module.subprocess, "run", explode):
            self.assertEqual(self.module.command_output(["netsh"]), (None, ""))


if __name__ == "__main__":
    unittest.main()
