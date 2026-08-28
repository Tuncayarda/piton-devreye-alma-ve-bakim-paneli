#!/usr/bin/env python3
"""Making an application come up by itself when the display boots.

THIS WRITES TO THE DEVICE'S SYSTEM PARTITION. That is not a detail to be
discovered later: the two files below outlive a factory reset, they are not
removed by uninstalling the application, and on a device whose ``/system`` is
verified they can stop it booting. The screen asks before it happens and
names both files (`confirmWrite`); this module refuses to leave half of them
behind.

WHY THIS METHOD. It is the one the commissioning team already performs by
hand on these displays, and it is being brought into the panel rather than
replaced. An Android app can register for BOOT_COMPLETED itself, but that is
a change to the APK and these APKs are not ours to change; a launcher can be
told to start it, but the displays run several different images. An init
service plus a shell script works on every one of them and is what the field
already knows how to check.

TWO FILES, AND THE ORDER THEY ARE WRITTEN IN MATTERS:

    /system/bin/dabp_autostart_<slug>.sh      waits for boot, then starts
    /system/etc/init/dabp-autostart-<slug>.rc the service that runs it

The script goes first. A device carrying the .rc without the .sh runs a
service that fails on every boot and writes a failure into the log for ever —
the one arrangement that is worse than not installing it at all.

`<slug>` COMES FROM THE PACKAGE NAME, so several applications can be set up
on one display and removing one cannot take another with it. The hand-written
version used a fixed name and could hold exactly one.

THREE WAYS IN, TRIED IN ORDER, AND THE ONE THAT WORKED IS REPORTED:

1. ``adb push`` straight to /system — works on a userdebug/eng image whose
   adbd is running as root, which is what the field displays are.
2. push to /data/local/tmp, then ``su -c`` to remount /system read-write and
   copy it into place. The route for an image whose adbd is not root but
   whose ``su`` works — the same ``su`` the address write already relies on
   (see `panel.ip_assign.lcd_runner`).
3. Neither: NOTHING IS WRITTEN and the device is reported as one whose
   /system cannot be written. Leaving one of the two files behind is the
   failure this module exists to avoid.

Both files are read back with ``ls -lZ`` afterwards — existence, mode and
SELinux label. A file that lands with the wrong label is ignored by init and
looks exactly like a file that was never written.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile
from pathlib import Path

from .. import i18n
from ..errors import VerificationError
from . import apps, client

SCRIPT_DIR = "/system/bin"
SERVICE_DIR = "/system/etc/init"
# The label init needs to run the script as the shell user. Written into the
# .rc as `seclabel` and checked on the file itself after the copy.
SECLABEL = "u:r:shell:s0"
# The groups the boot script runs with, and `readproc` is not optional.
#
# /proc on these displays is mounted `hidepid=2,gid=3009`, so a process
# outside group 3009 (readproc) cannot see any other process at all. The
# script checks whether the application it launched is REALLY running, and
# without this group that check answers "no" every time however well the
# launch went: it retried thirty times against a perfectly healthy app and
# then logged that it had given up. An adb shell has readproc, which is
# exactly why the same command worked by hand and not at boot.
SERVICE_GROUPS = "shell log readproc"
FILE_CONTEXT = "u:object_r:system_file:s0"
STAGING_DIR = "/data/local/tmp"

# How the generated script waits. Thirty attempts two seconds apart is a
# minute — long enough for a display that is still mounting storage, short
# enough that a device which is never going to start the app stops trying.
BOOT_ATTEMPTS = 30
BOOT_INTERVAL = 2
# How long the script waits AFTER the system says it has booted, before the
# first launch. `sys.boot_completed=1` is not the end of starting up: the
# launcher is still coming to the foreground behind it, and an activity
# started into that gap is replaced by the home screen a moment later. This
# was the difference between "am start reported success" and an application
# that was actually on the display.
BOOT_SETTLE = 8
# How long a launched application is given to be alive before it counts.
LAUNCH_SETTLE = 4


def slug(package: str) -> str:
    """A file-name-safe stem for this package.

    Dots become underscores and nothing else survives: the string ends up in
    an init service name, and init's parser is not forgiving.
    """
    name = re.sub(r"[^A-Za-z0-9]+", "_", str(package or "")).strip("_")
    if not name:
        raise ValueError(i18n.t("error.adbPackageInvalid"))
    return name.lower()[:60]


def script_path(package: str) -> str:
    return f"{SCRIPT_DIR}/dabp_autostart_{slug(package)}.sh"


def service_path(package: str) -> str:
    # init reads every .rc in this folder; the hyphen is the convention the
    # platform's own files use.
    return f"{SERVICE_DIR}/dabp-autostart-{slug(package)}.rc"


def service_name(package: str) -> str:
    """The name init knows the service by. SHORT, and not the package name.

    Init turns this into the property `init.svc.<name>`, and on Android 7 and
    earlier a property NAME had to fit in 32 characters. "init.svc." spends
    nine of them, so anything past 23 was refused — and
    `dabp_autostart_com_example_gebze_osb` is 36. Init then rejects the whole
    service definition, which looks from the outside exactly like what was
    reported here: both files sit on the device, the check says "installed",
    and nothing runs at boot.

    So the name is a fixed prefix plus a digest of the package, which is 16
    characters whatever the bundle is called. THE FILE NAMES STAY READABLE —
    they have no such limit, and the confirmation dialog shows them to a
    person who has to recognise what is about to be written.
    """
    digest = hashlib.sha1(slug(package).encode("utf-8")).hexdigest()[:8]
    return f"dabp_as_{digest}"


def files(package: str) -> tuple[str, str]:
    """(script, service) — what the confirmation dialog lists."""
    return script_path(package), service_path(package)


# ── what gets written ───────────────────────────────────────────────────
def script_text(package: str, component: str) -> str:
    """The boot script.

    Two waits in here were each paid for by a display that did nothing at
    boot, and neither is padding.

    **It waits for `sys.boot_completed`, and then some.** An `am start`
    issued before the activity manager is up is accepted and silently
    dropped. But the property going to 1 is not the end of starting up
    either — the launcher is still coming to the foreground behind it, and
    an activity started into that gap is replaced by the home screen a
    moment later. That is a launch which reports success and leaves nothing
    on the display.

    **`am start` exiting 0 is not proof.** It reports success for a launch
    that never lands, which is the same trap the rest of this panel refuses
    everywhere else. So the script asks whether the process is REALLY there
    afterwards, and retries when it is not.
    """
    name = service_name(package)
    return f"""#!/system/bin/sh
# Written by the commissioning panel. Removing this file and
# {service_path(package)} undoes the autostart completely.
PACKAGE="{package}"
COMPONENT="{component}"
TAG="{name}"

i=0
while [ "$i" -lt {BOOT_ATTEMPTS} ]; do
    if [ "$(getprop sys.boot_completed)" = "1" ]; then
        break
    fi
    sleep {BOOT_INTERVAL}
    i=$((i + 1))
done

# The launcher is still arriving; starting into that gap loses the activity.
sleep {BOOT_SETTLE}

i=0
while [ "$i" -lt {BOOT_ATTEMPTS} ]; do
    am start -n "$COMPONENT" >/dev/null 2>&1
    sleep {LAUNCH_SETTLE}
    if pidof "$PACKAGE" >/dev/null 2>&1; then
        log -t "$TAG" "started $COMPONENT"
        exit 0
    fi
    log -t "$TAG" "attempt $i did not stay up"
    sleep {BOOT_INTERVAL}
    i=$((i + 1))
done

log -t "$TAG" "gave up starting $COMPONENT"
exit 1
"""


def service_text(package: str) -> str:
    """The init service.

    `oneshot` + `disabled` + a property trigger, rather than a service init
    starts by itself: the script is a one-off launch, and a plain service
    that exits is one init restarts in a loop.
    """
    name = service_name(package)
    return f"""# Written by the commissioning panel.
service {name} {script_path(package)}
    class late_start
    user shell
    group {SERVICE_GROUPS}
    seclabel {SECLABEL}
    oneshot
    disabled

on property:sys.boot_completed=1
    start {name}
"""


# ── writing them ────────────────────────────────────────────────────────
# Tokens, not prose. A file's presence used to be decided by looking for its
# path in `ls -lZ` output — and toybox `ls` reports a MISSING file as
# `ls: /system/bin/x: Invalid argument`, a line that contains the path. So
# every missing file read as present, the write "succeeded", and the failure
# only surfaced two steps later against the wrong file name. A token the
# device either prints or does not cannot be misread.
_PRESENT = "DABP_PRESENT"
_ABSENT = "DABP_ABSENT"
_EXECUTABLE = "DABP_EXEC"


class _Root:
    """The `su` form this device accepts, worked out once per operation.

    Lazily: a display whose adbd is already root never needs `su` at all,
    and probing three forms on it would be three commands spent proving
    something nothing is going to ask.
    """

    def __init__(self, ip: str):
        self.ip = ip
        self._form: tuple[str, ...] | None = None

    def run(self, transaction: str):
        if self._form is None:
            self._form = client.root_form(self.ip)
        return client.root_script(self.ip, transaction, form=self._form)


def _push(ip: str, text: str, remote: str) -> bool:
    """Push this text to `remote`. True when adb reports success."""
    handle, local = tempfile.mkstemp(prefix="dabp-autostart-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        result = client.run("-s", client.target(ip), "push", local, remote)
        answer = client.output(result)
        return (getattr(result, "returncode", 0) == 0
                and "error" not in answer.lower()
                and "failed" not in answer.lower())
    finally:
        try:
            Path(local).unlink()
        except OSError:
            pass


def _present(ip: str, remote: str) -> bool:
    answer = client.output(client.script(
        ip, f"[ -e {shlex.quote(remote)} ] && echo {_PRESENT} "
            f"|| echo {_ABSENT}"))
    return _PRESENT in answer


def _written(ip: str, remote: str, text: str) -> bool:
    """Did the file land WITH ITS CONTENTS?

    THE FAILURE THIS EXISTS FOR, and it was reported from the field as
    "installed but nothing runs at boot". On a display whose /system sits on
    a verity-backed device-mapper volume, remounting it read-write appears
    to work, `cp` exits 0, and the file arrives with the right owner, the
    right mode and the right SELinux label — and ZERO BYTES. The data is
    dropped; only the metadata survives. An empty .rc declares no service,
    so init has nothing to start and the panel had just told the operator it
    was installed.

    Checked by SIZE rather than by reading the file back: it is exact, it is
    one cheap command, and it is immune to the newline translation a `cat`
    over adb can do.
    """
    expected = len(text.encode("utf-8"))
    answer = client.output(client.script(
        ip, f"stat -c %s {shlex.quote(remote)} 2>/dev/null || echo -1"))
    try:
        return int(answer.split()[0]) == expected
    except (ValueError, IndexError):
        return False


def _executable(ip: str, remote: str) -> bool:
    answer = client.output(client.script(
        ip, f"[ -x {shlex.quote(remote)} ] && echo {_EXECUTABLE}"))
    return _EXECUTABLE in answer


def _remount_and_copy(ip: str, root: _Root, text: str, remote: str,
                      mode: str) -> bool:
    """The `su` route: stage in /data/local/tmp, then copy into /system.

    The staging push is unprivileged and always allowed; only the copy needs
    root. Both remount targets are attempted because which one is right
    depends on whether the image still has a separate /system partition —
    the Raspberry Pi displays have one root ext4 filesystem and answer to
    `remount /`, and asking first is more code than trying both.
    """
    staged = f"{STAGING_DIR}/{Path(remote).name}"
    if not _push(ip, text, staged):
        return False
    quoted, staged_quoted = shlex.quote(remote), shlex.quote(staged)
    transaction = (
        "mount -o rw,remount /system 2>/dev/null; "
        "mount -o rw,remount / 2>/dev/null; "
        f"mkdir -p {shlex.quote(str(Path(remote).parent))}; "
        f"cp {staged_quoted} {quoted} && chmod {mode} {quoted} && "
        f"chown root:root {quoted}; "
        f"(restorecon {quoted} || chcon {FILE_CONTEXT} {quoted}) "
        "2>/dev/null; "
        f"rm -f {staged_quoted}; "
        "sync"
    )
    root.run(transaction)
    return _written(ip, remote, text)


def _overlay_push(ip: str, text: str, remote: str, mode: str) -> bool:
    """The route the field displays actually need.

    `adb root` then `adb remount`, which on Android 10 and later mounts an
    overlayfs over /system with its upper layer on /mnt/scratch. That is the
    only arrangement in which a write to /system on a verity-backed image
    really lands — remounting the read-only volume by hand and copying into
    it produces a file with the right name and no contents (see `_written`).
    """
    if not client.restart_as_root(ip):
        return False
    if not client.overlay_remount(ip):
        return False
    if not _push(ip, text, remote):
        return False
    client.script(ip, f"chmod {mode} {shlex.quote(remote)}")
    return _written(ip, remote, text)


def _write_file(ip: str, root: _Root, text: str, remote: str,
                mode: str) -> str:
    """Get one file into place. Returns which route worked, or raises.

    EVERY ROUTE IS JUDGED BY READING THE FILE BACK, and by its size rather
    than its presence. The route that made this necessary reports success at
    every step and leaves an empty file behind; taking any of these
    functions' word for it is how a display got reported as set up while
    init had nothing to parse.
    """
    if _push(ip, text, remote):
        client.shell_result(ip, "chmod", mode, remote)
        if _written(ip, remote, text):
            return "push"
    if _overlay_push(ip, text, remote, mode):
        return "overlay"
    if _remount_and_copy(ip, root, text, remote, mode):
        return "su"
    # EVERY ROUTE FAILED, AND SOME OF THEM LEFT SOMETHING. The verity
    # display creates the file and drops its contents, so giving up here
    # without clearing it leaves an empty file that the next check would
    # find and that init would parse as nothing. The caller's rollback only
    # covers the file written BEFORE the one that failed; this covers the
    # failure's own leavings.
    _remove_file(ip, root, remote)
    raise VerificationError(
        i18n.t("error.adbSystemNotWritable", path=remote))


def _remove_file(ip: str, root: _Root, remote: str) -> None:
    """Best effort removal, by both routes. Never raises."""
    quoted = shlex.quote(remote)
    try:
        client.script(ip, f"rm -f {quoted}")
        if _present(ip, remote):
            root.run("mount -o rw,remount /system 2>/dev/null; "
                     "mount -o rw,remount / 2>/dev/null; "
                     f"rm -f {quoted}; sync")
    except Exception:
        # Removal runs as cleanup after a failure that is already being
        # reported; a second error on top of it helps nobody.
        pass


def install(ip: str, package: str, activity: str = "") -> dict:
    """Set this application to start when the display boots.

    The script is written FIRST and the service second — see the module
    docstring — and if either the write or the verification of the second
    fails, the first is taken back off the device. A display carrying a
    service whose script is missing runs a failing service on every boot.
    """
    name = apps.clean_package(package)
    if not client.connect(ip, attempts=2):
        raise VerificationError(i18n.t("error.adbNoConnection"))
    component = str(activity or "").strip() or apps.launcher_activity(ip, name)

    root = _Root(ip)
    script, service = files(name)
    route = _write_file(ip, root, script_text(name, component), script, "0755")
    try:
        _write_file(ip, root, service_text(name), service, "0644")
        _verify(ip, script, service)
    except Exception:
        # Nothing half-installed. The script alone is inert; the service
        # alone is not.
        _remove_file(ip, root, service)
        _remove_file(ip, root, script)
        raise
    return {"package": name, "action": "autostart_install",
            "activity": component, "route": route,
            "files": [script, service]}


def _verify(ip: str, script: str, service: str) -> None:
    """Both files really there, and the script really runnable.

    Asked file by file so the message names the one that is actually
    missing. It used to report the whole listing against the first path,
    which sent somebody looking at a script that was on the device.
    """
    for path in (script, service):
        if not _present(ip, path):
            raise VerificationError(
                i18n.t("error.adbAutostartNotWritten", path=path))
    if not _executable(ip, script):
        # Without the execute bit init runs nothing and says nothing.
        raise VerificationError(
            i18n.t("error.adbAutostartNotExecutable", path=script))


def remove(ip: str, package: str) -> dict:
    """Take the autostart back off the device.

    The service goes first this time, for the same reason the script went
    first on the way in: it is the file that makes a boot fail.
    """
    name = apps.clean_package(package)
    if not client.connect(ip, attempts=2):
        raise VerificationError(i18n.t("error.adbNoConnection"))
    root = _Root(ip)
    script, service = files(name)
    _remove_file(ip, root, service)
    _remove_file(ip, root, script)
    remaining = [path for path in (service, script) if _present(ip, path)]
    if remaining:
        raise VerificationError(
            i18n.t("error.adbAutostartNotRemoved",
                   path=", ".join(remaining)))
    return {"package": name, "action": "autostart_remove",
            "files": [script, service]}


def _getprop(ip: str, name: str) -> str:
    return client.output(client.shell_result(ip, "getprop", name)).strip()


def _boot_epoch(ip: str) -> float:
    """When this device last booted, in its own clock's seconds.

    Read as now-minus-uptime rather than from a boot property: the property
    is not on every image, and /proc/uptime is.
    """
    uptime = client.output(client.shell_result(ip, "cat", "/proc/uptime"))
    now = client.output(client.shell_result(ip, "date", "+%s"))
    try:
        return float(now.split()[0]) - float(uptime.split()[0])
    except (ValueError, IndexError):
        return 0.0


def _mtime(ip: str, path: str) -> float:
    raw = client.output(client.shell_result(ip, "stat", "-c", "%Y", path))
    try:
        return float(raw.splitlines()[0].strip())
    except (ValueError, IndexError):
        return 0.0


def _log(ip: str, package: str, limit: int = 12) -> list[str]:
    """What the generated script itself said, newest last."""
    tag = service_name(package)
    raw = client.output(client.shell_result(
        ip, "logcat", "-d", "-s", f"{tag}:*", "*:S"))
    lines = [line.strip() for line in raw.splitlines()
             if tag in line and "---" not in line]
    return lines[-limit:]


def state(ip: str, package: str) -> dict:
    """Is the autostart WORKING on this device — not just present.

    THE OLD ANSWER WAS THE TWO FILES, AND IT WAS NOT AN ANSWER. Both files
    can sit exactly where they were written while nothing at all happens at
    boot, and that is not a rare case; it is the one that gets reported.
    Three different faults produce it and they need three different fixes:

    * **The write did not survive the reboot.** A device with verified boot
      or a read-only overlay accepts the copy, reads it back correctly for
      the rest of that session, and comes up without it. The files are gone
      when you look again — so their ABSENCE after a reboot is a finding,
      not a "not installed yet".
    * **Init never accepted the service.** The files are there and
      `init.svc.<name>` does not exist, which means the .rc was not parsed —
      a name init refuses, a label it will not run, or a partition it does
      not read. This is the one the file check reported as "installed".
    * **It ran and the launch failed.** `init.svc.<name>` is `stopped` and
      the script's own log says it gave up. The autostart is fine; the
      activity is the problem.

    So all three are asked about, and the answer names which. `pendingReboot`
    is separated out first, because immediately after installing there has
    been no boot for any of this to have happened at and blaming init then
    would be a lie the operator would act on.
    """
    name = apps.clean_package(package)
    if not client.connect(ip, attempts=2):
        raise VerificationError(i18n.t("error.adbNoConnection"))
    script, service = files(name)
    has_script = _present(ip, script)
    has_service = _present(ip, service)

    if has_script and has_service:
        installed = "installed"
    elif has_script or has_service:
        installed = "partial"
    else:
        installed = "absent"

    init_state = _getprop(ip, f"init.svc.{service_name(name)}")
    booted = _boot_epoch(ip)
    written = _mtime(ip, service) if has_service else 0.0
    # Written after the last boot: nothing has had the chance to run yet.
    pending = bool(has_script and has_service and booted and written > booted)
    log = _log(ip, name) if has_script else []
    running = bool(client.output(
        client.shell_result(ip, "pidof", name)).strip())

    return {"package": name, "state": installed, "script": has_script,
            "service": has_service, "files": [script, service],
            "serviceName": service_name(name), "initState": init_state,
            "appRunning": running, "log": log,
            "verdict": _verdict(installed, pending, init_state, log)}


def _verdict(installed: str, pending: bool, init_state: str,
             log: list[str]) -> str:
    """One word for what is actually wrong, or that nothing is."""
    if installed != "installed":
        return installed                      # absent / partial
    if init_state:
        # INIT HAS PARSED THE .rc, which only happens at boot — so a boot
        # HAS happened since the file was written, whatever the arithmetic
        # below thinks. That arithmetic compares the file's mtime with
        # now-minus-uptime, and these displays have no battery-backed clock:
        # they boot in 2024, pick the real date up from the network a minute
        # later, and the sum is nonsense in between. The property is the
        # fact; the clock is a guess.
        return _ran_verdict(init_state, log)
    if pending:
        return "pendingReboot"
    if not init_state:
        # The files survived a boot and init still does not know the
        # service. This is the fault the file check used to call "installed".
        return "notParsed"
    return _ran_verdict(init_state, log)


def _ran_verdict(init_state: str, log: list[str]) -> str:
    """What the service did, once it is known that init ran it."""
    if init_state == "running":
        return "running"
    joined = " ".join(log).lower()
    if "gave up" in joined:
        return "gaveUp"
    if "started" in joined:
        return "ranOk"
    return "ranSilently"
