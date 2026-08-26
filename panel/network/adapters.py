#!/usr/bin/env python3
"""Which adapters exist, what they already hold, and which one to use.

`panel.system.interfaces` answers "which MAC is this computer" — enough to
find the computer's switch port. Adding an address needs two things it does
not carry:

  · the ADDRESS WITH ITS PREFIX. "Is the computer already in 10.1.1.0/24" is
    unanswerable from a bare list of addresses, and answering it wrongly means
    either adding an address that is not needed or skipping one that is.
  · the CONFIGURATION HANDLE — what this platform's tool accepts as "that
    adapter". On POSIX it is the device name. On Windows it is the interface
    index, because the name `netsh` wants cannot be read out of `ipconfig`:
    its block header is written in the local language, the word "adapter"
    included, so there is no locale-independent way to cut the connection
    name out of it.

Nothing here writes; see `panel.network.aliases` for that.
"""
from __future__ import annotations

import ipaddress
import platform
import re
from dataclasses import dataclass, field

from ..system import interfaces

# Adapters that exist in software: a VPN tunnel, a hypervisor's host-only
# network, a container bridge, Apple's peer-to-peer radio. None of them is the
# cable that reaches the switch, and an address added to one goes nowhere.
VIRTUAL_PREFIXES = ("lo", "utun", "gif", "stf", "awdl", "llw", "bridge",
                    "vmnet", "vnic", "veth", "virbr", "docker", "tun", "tap",
                    "ppp", "wg", "zt", "ham", "anpi", "ap")
VIRTUAL_WORDS = ("loopback", "virtual", "vmware", "virtualbox", "hyper-v",
                 "vethernet", "tunnel", "tap-", "bluetooth", "wan miniport",
                 "pseudo")

# Wired before wireless. The panel is used with a patch cable into the
# switch's front panel; the laptop's Wi-Fi is usually on some other network
# entirely and is exactly the adapter an address must NOT land on.
WIRED_PREFIXES = ("en", "eth", "enp", "ens", "eno", "enx", "em")
WIRELESS_PREFIXES = ("wl", "wlan", "wifi", "wi-fi", "airport")

_MASK_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


@dataclass
class Adapter:
    """One network adapter, as far as adding an address is concerned."""

    name: str
    handle: str
    mac: str = ""
    # (address, prefix length) — the prefix is what makes the address usable
    # as a network membership answer.
    addresses: list[tuple[str, int]] = field(default_factory=list)
    up: bool | None = None
    virtual: bool = False

    @property
    def networks(self) -> list[ipaddress.IPv4Network]:
        out = []
        for address, prefix in self.addresses:
            try:
                out.append(ipaddress.ip_network(f"{address}/{prefix}",
                                                strict=False))
            except ValueError:
                continue
        return out

    def dto(self) -> dict:
        return {
            "name": self.name,
            "handle": self.handle,
            "mac": self.mac,
            "addresses": [f"{address}/{prefix}"
                          for address, prefix in self.addresses],
            "up": self.up,
            "virtual": self.virtual,
            "wired": self.wired,
        }

    @property
    def wired(self) -> bool:
        lowered = self.name.lower()
        if any(lowered.startswith(word) for word in WIRELESS_PREFIXES):
            return False
        if "wi-fi" in lowered or "wireless" in lowered:
            return False
        return any(lowered.startswith(word) for word in WIRED_PREFIXES)


def _is_ipv4(value) -> bool:
    try:
        return ipaddress.ip_address(str(value)).version == 4
    except ValueError:
        return False


def _is_netmask(value: str) -> bool:
    """Contiguous ones then zeros — 255.255.255.0 yes, 10.1.1.101 no."""
    try:
        bits = int(ipaddress.IPv4Address(value))
    except ValueError:
        return False
    inverted = bits ^ 0xFFFFFFFF
    return ((inverted + 1) & inverted) == 0


def _prefix_of(mask: str) -> int:
    return bin(int(ipaddress.IPv4Address(mask))).count("1")


def is_virtual(name: str) -> bool:
    lowered = str(name or "").lower()
    if any(word in lowered for word in VIRTUAL_WORDS):
        return True
    # Prefix match on the bare device name, digits and unit stripped: "utun4"
    # is a tunnel, "enp3s0" is not.
    bare = re.sub(r"[0-9].*$", "", lowered)
    return bare in VIRTUAL_PREFIXES


# ────────────────────────────────────────────────────────────── POSIX ──────
# macOS writes the mask in hex ("netmask 0xffffff00"), Linux's ifconfig in
# dotted form, an old one as "Mask:255.255.255.0", and `ip` as a suffix
# ("inet 10.0.2.15/24"). All four appear in the field.
_INET_PATTERNS = (
    re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})"),
    re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})\s+netmask\s+0x([0-9a-fA-F]{8})"),
    re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})\s+netmask\s+(\d{1,3}(?:\.\d{1,3}){3})"),
    re.compile(r"\binet\s+addr:\s*(\d{1,3}(?:\.\d{1,3}){3}).*?\bMask:\s*(\d{1,3}(?:\.\d{1,3}){3})"),
)


def parse_posix_addresses(text: str) -> list[tuple[str, int]]:
    """Every "inet …" in one interface block, with its prefix length."""
    found: list[tuple[str, int]] = []
    for pattern in _INET_PATTERNS:
        for address, mask in pattern.findall(text):
            if not _is_ipv4(address):
                continue
            if len(mask) == 8 and not mask.isdigit():        # hex netmask
                prefix = bin(int(mask, 16)).count("1")
            elif "." in mask:
                if not _is_netmask(mask):
                    continue
                prefix = _prefix_of(mask)
            else:
                prefix = int(mask)
            if not 0 <= prefix <= 32:
                continue
            if (address, prefix) not in found:
                found.append((address, prefix))
    return found


def _posix_adapters() -> list[Adapter]:
    text = interfaces.dump()
    found: list[Adapter] = []
    if text.strip():
        for block in interfaces.blocks(text):
            name = block.splitlines()[0].split(":")[0].strip()
            if not name:
                continue
            found.append(Adapter(
                name=name, handle=name, mac=interfaces.block_mac(block),
                addresses=parse_posix_addresses(block),
                up=interfaces.block_up(block), virtual=is_virtual(name)))
    if found:
        return found
    # No ifconfig — current Ubuntu. `interfaces` merges the two `ip` calls
    # already; only the prefixes have to be read again, from the same output.
    _code, addresses = interfaces.run_command(["ip", "-o", "addr"])
    by_name: dict[str, list[tuple[str, int]]] = {}
    for line in addresses.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        by_name.setdefault(parts[1], []).extend(parse_posix_addresses(line))
    for entry in interfaces.ip_interfaces():
        name = entry["name"]
        found.append(Adapter(name=name, handle=name, mac=entry["mac"],
                             addresses=by_name.get(name, []),
                             up=entry.get("up"), virtual=is_virtual(name)))
    return found


# ──────────────────────────────────────────────────────────── Windows ──────
# One PowerShell call for both tables, tab separated. NOT JSON and NOT the
# default table rendering: the column headers are localised and the table is
# truncated to the console width, while `Status` ("Up"/"Disconnected") and the
# numbers are the same in every language. [char]9 rather than a backtick-t so
# nothing depends on how the shell was quoted on the way in.
WINDOWS_QUERY = (
    "$t=[char]9;"
    "Get-NetAdapter | ForEach-Object {"
    " 'A'+$t+$_.InterfaceIndex+$t+$_.MacAddress+$t+$_.Status+$t+$_.Name };"
    "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object {"
    " 'I'+$t+$_.InterfaceIndex+$t+$_.IPAddress+$t+$_.PrefixLength }"
)

WINDOWS_COMMAND = ["powershell", "-NoProfile", "-NonInteractive",
                   "-ExecutionPolicy", "Bypass", "-Command", WINDOWS_QUERY]


def parse_windows_query(text: str) -> list[Adapter]:
    """Turn the two tagged tables above into adapters."""
    by_index: dict[str, Adapter] = {}
    pending: list[tuple[str, str, int]] = []
    for line in text.splitlines():
        parts = line.rstrip().split("\t")
        if len(parts) < 4 or parts[0] not in ("A", "I"):
            continue
        if parts[0] == "A":
            index, mac, status = parts[1], parts[2], parts[3]
            name = parts[4] if len(parts) > 4 else ""
            by_index[index] = Adapter(
                name=name or index, handle=index,
                mac=interfaces.normalize_mac(mac),
                up=(status.strip().lower() == "up"),
                virtual=is_virtual(name))
        else:
            index, address, prefix = parts[1], parts[2], parts[3]
            if _is_ipv4(address) and prefix.strip().isdigit():
                pending.append((index, address, int(prefix)))
    for index, address, prefix in pending:
        adapter = by_index.get(index)
        if adapter is not None and (address, prefix) not in adapter.addresses:
            adapter.addresses.append((address, prefix))
    return list(by_index.values())


def parse_getmac_csv(text: str) -> dict[str, str]:
    """MAC -> connection name, from `getmac /v /fo csv /nh`.

    The fallback when PowerShell is unavailable. Headerless CSV, so the
    columns are read by position and no localised label is involved:
    0 = connection name, 2 = physical address.
    """
    import csv
    import io

    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 3:
            continue
        mac = interfaces.normalize_mac(row[2])
        if mac and row[0].strip():
            out.setdefault(mac, row[0].strip())
    return out


def parse_ipconfig_addresses(block: str) -> list[tuple[str, int]]:
    """Addresses and prefixes out of one `ipconfig /all` block.

    Locale-free by POSITION, not by label: within a block an IPv4 address line
    is immediately followed by its subnet mask line. So the block's IPv4
    tokens are read in order and a token is paired with the next one when that
    next one is a valid netmask. A default gateway is not a netmask, so it
    never gets picked up as an address.
    """
    tokens = _MASK_PATTERN.findall(block)
    found: list[tuple[str, int]] = []
    index = 0
    while index < len(tokens):
        current = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if not _is_netmask(current) and following and _is_netmask(following):
            found.append((current, _prefix_of(following)))
            index += 2
            continue
        index += 1
    return found


def _windows_adapters() -> list[Adapter]:
    code, text = interfaces.run_command(WINDOWS_COMMAND, timeout=15.0)
    if code == 0:
        found = parse_windows_query(text)
        if found:
            return found
    # PowerShell is missing or refused. `ipconfig` still gives MAC, addresses
    # and masks; `getmac` gives the connection name netsh can be pointed at.
    names = parse_getmac_csv(interfaces.run_command(
        ["getmac", "/v", "/fo", "csv", "/nh"])[1])
    found = []
    for block in interfaces.blocks(interfaces.dump()):
        mac = interfaces.block_mac(block)
        if not mac:
            continue
        header = block.splitlines()[0].rstrip(":").strip()
        name = names.get(mac, "")
        found.append(Adapter(
            name=name or header, handle=name, mac=mac,
            addresses=parse_ipconfig_addresses(block),
            # `ipconfig` says "media disconnected" in the local language only;
            # holding an address is the closest locale-free stand-in.
            up=None, virtual=is_virtual(name or header)))
    return found


# ─────────────────────────────────────────────────────────── selection ─────
def list_adapters(system: str | None = None) -> list[Adapter]:
    """Every adapter on this machine. One OS call; hold the result."""
    system = system or platform.system()
    return _windows_adapters() if system == "Windows" else _posix_adapters()


def rank(adapter: Adapter) -> tuple:
    """Sort key for the PICKER — carrier, then wired, then already addressed.

    An ordering, not a decision. It decides which adapter the user sees first
    in the list on the Network screen; it never decides which one gets an
    address (see `choose`).
    """
    return (
        0 if adapter.up else (1 if adapter.up is None else 2),
        0 if adapter.wired else 1,
        0 if adapter.addresses else 1,
        adapter.name,
    )


def usable(adapters: list[Adapter]) -> list[Adapter]:
    """Adapters an address could sensibly be added to, likeliest first."""
    return sorted((adapter for adapter in adapters
                   if adapter.handle and not adapter.virtual), key=rank)


def choose(adapters: list[Adapter], targets=(),
           override: str = "") -> Adapter | None:
    """Which adapter gets the new address — or None, which is a real answer.

    Only two things count, and both are FACTS about this machine:

      1. the user's choice on the Network screen, if that adapter is still
         there;
      2. an adapter that ALREADY holds an address in one of `targets`'
         networks. `targets` is ordered, and the factory network comes first:
         an adapter sitting on 10.1.1.x is the cable into the devices, and
         after the first run it is the panel's own address that puts it there.

    **There is no third answer.** An earlier version fell back to a ranking
    (carrier, wired, addressed) and on a laptop tethered to a phone it picked
    the phone — an adapter with nothing on the far end. The address went
    somewhere useless, the run failed exactly as it had before, and the screen
    said an interface had been chosen. Guessing wrong here is worse than not
    answering: nothing is added, the Network screen asks for an interface, and
    one click settles it for good.

    Note what this is NOT: "which interface would the kernel route through".
    With no matching route the answer to that is the DEFAULT route's
    interface — the phone again.
    """
    candidates = usable(adapters)
    if not candidates:
        return None
    if override:
        for adapter in candidates:
            if override in (adapter.name, adapter.handle, adapter.mac):
                return adapter
    for target in targets:
        if not _is_ipv4(target):
            continue
        address = ipaddress.IPv4Address(str(target))
        for adapter in candidates:
            if any(address in network for network in adapter.networks):
                return adapter
    return None


def local_networks(adapters: list[Adapter]) -> list[ipaddress.IPv4Network]:
    """Every network this computer already has an address in."""
    found: list[ipaddress.IPv4Network] = []
    for adapter in adapters:
        for network in adapter.networks:
            if network not in found:
                found.append(network)
    return found


def local_addresses(adapters: list[Adapter]) -> set[str]:
    return {address for adapter in adapters
            for address, _prefix in adapter.addresses}
