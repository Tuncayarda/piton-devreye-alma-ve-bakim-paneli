#!/usr/bin/env python3
"""Wiping a USB stick and laying down a filesystem every machine can read.

WHY THE PANEL DOES THIS AT ALL. A service key is minted rarely and handed to
a person, and the stick it goes on should carry that and nothing else — not
last year's firmware images, not a colleague's photos. Doing it from the
panel means the engineer cannot forget the step, and the result is the same
every time.

WHAT IT COSTS. This is the one place in the application that destroys data
outside the panel's own files, and it runs elevated like everything else. So
the rules are strict and they are here rather than in the caller:

  · Only drives the operating system itself calls REMOVABLE/EXTERNAL are
    listed. An internal disk is never a candidate, whatever it is asked for.
  · The boot disk is excluded explicitly as well, not only implicitly.
  · `prepare()` re-reads the list and refuses an id that is not on it. The
    id the UI sends is never trusted — it was true when the screen drew, and
    a drive can be unplugged and another plugged in between then and the
    click.

FAT32, and an MBR partition table. Not because the payload needs it — the
key file is three hundred bytes — but because "works on every system" is the
whole requirement: Windows, macOS and Linux all mount FAT32 with nothing
installed, and so do the ten-year-old machines that turn up in a depot.
exFAT would be the modern answer and is NOT used: it needs a driver on older
Linux, and a key that cannot be read is worse than a key that wastes space.
"""
from __future__ import annotations

import json
import platform
import plistlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..system.spawn import NO_CONSOLE

# FAT32 volume labels are 11 characters, upper case. The operator's own note
# for the key does NOT go here — it goes inside the key file, where it has
# room (see keyfile.write). This name is fixed so a prepared stick is
# recognisable as one at a glance.
VOLUME_LABEL = "DABP-KEY"
# Long enough for the slowest stick to be erased and formatted.
TIMEOUT = 180.0


class MediaError(RuntimeError):
    """Something the operator has to be told, in words they can act on."""


@dataclass(frozen=True)
class Drive:
    """One whole removable drive, as the operating system names it."""

    id: str          # what the erase command takes: /dev/disk4, "2", /dev/sdb
    name: str        # model or product name, for the confirmation
    size: int        # bytes — the other half of "is this the right one?"
    bus: str         # USB, SD … shown so an oddity is visible


# ── what may be erased ───────────────────────────────────────────────────
def drives(system: str | None = None) -> list[Drive]:
    """Every removable drive on this machine, and nothing else."""
    system = system or platform.system()
    try:
        if system == "Darwin":
            return _macos_drives()
        if system == "Windows":
            return _windows_drives()
        return _linux_drives()
    except (OSError, ValueError, subprocess.SubprocessError):
        # Listing is a screen, not an operation: an unreadable disk tool
        # leaves the list empty and the screen says so.
        return []


def find(drive_id: str, system: str | None = None) -> Drive | None:
    wanted = str(drive_id or "")
    return next((d for d in drives(system) if d.id == wanted), None)


def prepare(drive_id: str, system: str | None = None) -> Path:
    """Erase the drive, make one FAT32 partition, and return where it is
    mounted. EVERYTHING ON IT IS LOST."""
    system = system or platform.system()
    drive = find(drive_id, system)
    if drive is None:
        # Not "unknown id": the honest reading is that it is not something
        # this may erase — either gone, or never eligible.
        raise MediaError("not-removable")
    if system == "Darwin":
        return _macos_prepare(drive)
    if system == "Windows":
        return _windows_prepare(drive)
    return _linux_prepare(drive)


# ── running the tools ────────────────────────────────────────────────────
def _run(command: list[str], timeout: float = TIMEOUT) -> str:
    """Run a disk tool with an argument list — never through a shell."""
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, check=False, **NO_CONSOLE)
    except FileNotFoundError as exc:
        raise MediaError(f"missing tool: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"timed out: {command[0]}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise MediaError(detail[-1] if detail else f"{command[0]} failed")
    return done.stdout


def _powershell(script: str) -> str:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 script])


# ── macOS ────────────────────────────────────────────────────────────────
def _macos_drives() -> list[Drive]:
    # "external physical" already excludes internal disks and disk images;
    # every disk is then read individually, because that listing does not
    # say whether the system booted from it.
    listing = plistlib.loads(_run(
        ["diskutil", "list", "-plist", "external", "physical"],
        timeout=30.0).encode("utf-8"))
    found = []
    for identifier in listing.get("WholeDisks", []):
        info = plistlib.loads(_run(
            ["diskutil", "info", "-plist", f"/dev/{identifier}"],
            timeout=30.0).encode("utf-8"))
        if not _macos_eligible(info):
            continue
        found.append(Drive(
            id=f"/dev/{identifier}",
            name=str(info.get("MediaName") or identifier),
            size=int(info.get("TotalSize") or info.get("Size") or 0),
            bus=str(info.get("BusProtocol") or "")))
    return found


def _macos_eligible(info: dict) -> bool:
    """The filter, apart from the command that produced the data, so the
    tests can drive it with a recorded `diskutil info` reply."""
    return (info.get("Internal") is False
            and info.get("SystemImage") is not True
            and info.get("VirtualOrPhysical") != "Virtual"
            and bool(info.get("Ejectable") or info.get("RemovableMedia")))


def _macos_prepare(drive: Drive) -> Path:
    # MBRFormat rather than GPT: an MBR/FAT32 stick is the one combination
    # nothing refuses to mount.
    _run(["diskutil", "eraseDisk", "FAT32", VOLUME_LABEL, "MBRFormat",
          drive.id])
    # diskutil mounts what it just made; asking where beats assuming
    # /Volumes/<label>, which is only true until a volume of that name is
    # already there and the second one becomes "DABP-KEY 1".
    info = plistlib.loads(_run(
        ["diskutil", "info", "-plist", f"{drive.id}s1"],
        timeout=30.0).encode("utf-8"))
    mounted = info.get("MountPoint")
    if not mounted:
        raise MediaError("not-mounted")
    return Path(mounted)


# ── Windows ──────────────────────────────────────────────────────────────
def _windows_drives() -> list[Drive]:
    # BusType is the strong guard here: a disk reached over USB is not the
    # one Windows booted from. IsBoot/IsSystem are checked as well because
    # a machine CAN boot from USB, and then it is not a spare stick.
    raw = _powershell(
        "Get-Disk | Select-Object Number,FriendlyName,Size,BusType,"
        "IsBoot,IsSystem | ConvertTo-Json -Compress")
    return [Drive(id=str(disk["Number"]),
                  name=str(disk.get("FriendlyName") or ""),
                  size=int(disk.get("Size") or 0),
                  bus=str(disk.get("BusType") or ""))
            for disk in _as_list(raw) if _windows_eligible(disk)]


def _windows_eligible(disk: dict) -> bool:
    return (str(disk.get("BusType") or "").upper() in ("USB", "SD", "MMC")
            and disk.get("IsBoot") is not True
            and disk.get("IsSystem") is not True)


def _windows_prepare(drive: Drive) -> Path:
    letter = _powershell(f"""
        $ErrorActionPreference = 'Stop'
        Clear-Disk -Number {drive.id} -RemoveData -RemoveOEM -Confirm:$false
        Initialize-Disk -Number {drive.id} -PartitionStyle MBR
        $part = New-Partition -DiskNumber {drive.id} -UseMaximumSize `
                  -AssignDriveLetter
        Format-Volume -DriveLetter $part.DriveLetter -FileSystem FAT32 `
          -NewFileSystemLabel '{VOLUME_LABEL}' -Confirm:$false | Out-Null
        $part.DriveLetter
    """).strip()
    if not re.fullmatch(r"[A-Za-z]", letter):
        raise MediaError("not-mounted")
    return Path(f"{letter.upper()}:\\")


# ── Linux ────────────────────────────────────────────────────────────────
def _linux_drives() -> list[Drive]:
    raw = _run(["lsblk", "-J", "-b", "-o",
                "NAME,PATH,SIZE,MODEL,RM,HOTPLUG,TYPE,MOUNTPOINTS"],
               timeout=30.0)
    return [Drive(id=str(disk.get("path") or f"/dev/{disk.get('name')}"),
                  name=str(disk.get("model") or disk.get("name") or ""),
                  size=int(disk.get("size") or 0),
                  bus="USB" if disk.get("hotplug") else "")
            for disk in json.loads(raw).get("blockdevices", [])
            if _linux_eligible(disk)]


def _linux_eligible(disk: dict) -> bool:
    if disk.get("type") != "disk":
        return False
    if not (disk.get("rm") or disk.get("hotplug")):
        return False
    # A hot-pluggable disk the system is RUNNING FROM is still the system's.
    # Every mount point on it and on its partitions is checked, because "/"
    # sits on a child, not on the disk itself.
    for mount in _linux_mounts(disk):
        if mount in ("/", "/boot", "/boot/efi") or mount.startswith("/usr"):
            return False
    return True


def _linux_mounts(node: dict) -> list[str]:
    found = [m for m in (node.get("mountpoints") or []) if m]
    for child in node.get("children") or []:
        found.extend(_linux_mounts(child))
    return found


def _linux_prepare(drive: Drive) -> Path:
    _run(["wipefs", "-a", drive.id])
    # One partition filling the disk, type 'c' = W95 FAT32 (LBA): the entry
    # Windows expects to see before it will mount the thing.
    _sfdisk(drive.id, "label: dos\n,,c\n")
    partition = f"{drive.id}1" if drive.id[-1].isdigit() is False \
        else f"{drive.id}p1"
    _run(["mkfs.vfat", "-F", "32", "-n", VOLUME_LABEL, partition])
    mount = Path(tempfile.mkdtemp(prefix="dabp-key-"))
    _run(["mount", "-t", "vfat", partition, str(mount)])
    return mount


def _sfdisk(device: str, layout: str) -> None:
    try:
        done = subprocess.run(["sfdisk", device], input=layout, text=True,
                              capture_output=True, timeout=TIMEOUT,
                              check=False)
    except FileNotFoundError as exc:
        raise MediaError("missing tool: sfdisk") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("timed out: sfdisk") from exc
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise MediaError(detail[-1] if detail else "sfdisk failed")


def _as_list(raw: str) -> list:
    """PowerShell's ConvertTo-Json gives an object, not a list, for one row."""
    try:
        data = json.loads(raw or "null")
    except ValueError:
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []
