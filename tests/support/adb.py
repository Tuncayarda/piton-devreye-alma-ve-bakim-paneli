#!/usr/bin/env python3
"""THE fake ADB, shared by every suite that talks to the one transport.

`panel.adb.client` is the only place the panel executes ``adb``, so the tests
need exactly one stand-in for ``subprocess.run`` — this one. It grew out of
the ADB screen's fake, which was the richest of the three that existed (a
device with a package list and a file system), and it is installed the same
way everywhere::

    from unittest import mock
    from panel.adb import client as adb_client

    adb = FakeAdb({"10.1.1.40": {"packages": ["com.example.gebze"]}})
    with mock.patch.object(adb_client.subprocess, "run", side_effect=adb):
        ...

What the fake can prove is exactly what tends to go wrong in that code and
cannot be seen by reading it: which commands are sent, IN WHICH ORDER, and
what is left behind when one of them fails half way.

EXTENSION POINTS, for a suite that needs behaviour this model does not carry
(tests/test_lcd_ip.py keeps a commissioning-specific fake today and could
subclass this one instead):

* `__call__` dispatches on the adb verb (connect/disconnect/devices/
  kill-server/start-server/``-s <serial> <action>``) and answers anything it
  does not know with ``returncode=1`` — a command nobody wrote a case for
  must surface as a broken test, never as a silent pass. Override it and
  fall back to ``super().__call__`` to intercept whole commands.
* `_shell` answers ``adb -s <serial> shell <words...>``; `_script` answers a
  quoted ``sh -c`` script and `_su` the device's `su`. Override and fall
  back for device behaviour (an image missing a tool, an extra command).
* `_install` answers ``adb -s <serial> install ...`` — see below.
* `dumpsys_answers`, when given, replaces the model's `dumpsys package`
  reply with a scripted sequence — how the firmware suite plays "version
  0.0.5 before the install, 0.0.6 after".
"""
from __future__ import annotations

import re
import shlex

from panel import settings


class Result:
    """The shape `subprocess.run` returns, reduced to what the panel reads."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeAdb:
    """An ADB server holding a few Android devices with a file system.

    Only the commands the panel actually sends are answered. Anything else
    comes back as a failure rather than as an empty success — a command
    nobody wrote a case for should show up as a broken test, not as a silent
    pass.
    """

    LAUNCHER = "com.example.gebze/.MainActivity"

    def __init__(self, devices=None, *, system_writable=True,
                 push_to_system=True, start_fails=False, unlisted=(),
                 no_launcher=(), monkey_fails=(),
                 uninstall_fails=False, refuse=(), magisk_su=False,
                 reboot_refused=False, reboot_downtime=3,
                 drops_content=False, adb_root_allowed=True,
                 overlay_allowed=True, wedged=False,
                 install_output=None, install_stderr="",
                 install_returncode=0, dumpsys_answers=None):
        # ip -> {"packages": [...], "files": {path: text},
        #        "modes": {path: mode}}
        self.live = {ip: {"packages": list(record.get("packages", [])),
                          "files": dict(record.get("files", {})),
                          "modes": {}}
                     for ip, record in (devices or {}).items()}
        self.connected: set[str] = set()
        # The daemon on this computer, as opposed to any display. `wedged`
        # clears itself on the first restart, which is what lets a test say
        # "it was broken and the panel fixed it" rather than only one of the two.
        self.wedged = wedged
        self.server_restarts = 0
        self.calls: list[list[str]] = []
        self.timeline: list[str] = []
        # Which of the three write routes this device allows.
        self.system_writable = system_writable
        self.push_to_system = push_to_system
        self.start_fails = start_fails
        # Addresses that connect but never show up in `adb devices`.
        self.unlisted = set(unlisted)
        # Packages with no resolvable launcher activity — the case the
        # `monkey` fallback exists for.
        self.no_launcher = set(no_launcher)
        # ...and the ones monkey cannot start either.
        self.monkey_fails = set(monkey_fails)
        self.uninstall_fails = uninstall_fails
        # Paths the device ACCEPTS AND THEN DOES NOT KEEP: the command
        # reports success and the file is not there afterwards. That is the
        # failure the read-back exists to catch.
        self.refuse = set(refuse)
        # Does this image carry a Magisk-style `su` that takes `-c`? The
        # Compartment LCDs do; the AOSP displays do not. Off by default so
        # the harder of the two is what the suite exercises.
        self.magisk_su = magisk_su
        self.staged: dict[str, str] = {}
        # Rebooting, as the ADB server actually experiences it: the address
        # stops answering for a while and then answers again. `down` counts
        # the remaining refusals per address, so a test can say "comes back
        # after three knocks" or "never comes back" with one number.
        # What the autostart diagnosis asks the device about. Defaults
        # describe a display that booted an hour ago with nothing installed.
        # THE FAULT THE FIELD REPORTED. On a display whose /system sits on a
        # verity-backed device-mapper volume, remounting it read-write
        # appears to work and `cp` exits 0 — and the file arrives with the
        # right owner, mode and label and ZERO BYTES. Only an overlay makes
        # a write real. `drops_content` models exactly that.
        self.drops_content = drops_content
        self.adb_root_allowed = adb_root_allowed
        self.overlay_allowed = overlay_allowed
        self.adbd_root = False
        self.overlay = False
        self.props: dict[str, str] = {}
        self.now = 10_000
        self.uptime = 3600
        self.mtimes: dict[str, int] = {}
        self.logcat: list[str] = []
        self.app_running: set[str] = set()
        self.reboot_refused = reboot_refused
        self.reboot_downtime = reboot_downtime
        self.down: dict[str, int] = {}
        # `adb install`, as the firmware screen drives it. Left at their
        # defaults an install simply succeeds; `install_output` (with the
        # stderr/returncode beside it) scripts the device's answer instead,
        # and `install_attempts` counts the tries so the downgrade retry can
        # be told apart from the first go. `dumpsys_answers` is consumed one
        # reply per `dumpsys package` call — the before/after of a version
        # check — and when exhausted the model's own answer takes over.
        self.install_output = install_output
        self.install_stderr = install_stderr
        self.install_returncode = install_returncode
        self.install_attempts = 0
        self.dumpsys_answers = (None if dumpsys_answers is None
                                else list(dumpsys_answers))

    # ── plumbing ────────────────────────────────────────────────────────
    @staticmethod
    def ip_of(target: str) -> str:
        return target.rsplit(":", 1)[0]

    def command(self, name: str) -> list[str] | None:
        """The first recorded call containing `name`, for assertions."""
        return next((call for call in self.calls if name in call), None)

    def __call__(self, args, **_kwargs):
        args = list(args)
        self.calls.append(args)
        verb = args[1]
        if verb == "disconnect":
            self.connected.discard(self.ip_of(args[2]))
            return Result("disconnected\n")
        if verb == "connect":
            ip = self.ip_of(args[2])
            # A wedged server refuses everything, whatever is on the bench.
            # That is the shape the panel reads as "restart the server, not
            # the displays" (panel/adb/runner._should_recover).
            if self.wedged:
                return Result("", "cannot connect to daemon\n", 1)
            pending = self.down.get(ip, 0)
            if pending:
                self.down[ip] = pending - 1
                return Result(f"failed to connect to {args[2]}\n",
                              returncode=1)
            if ip in self.live:
                self.connected.add(ip)
                return Result(f"connected to {args[2]}\n")
            return Result(f"failed to connect to {args[2]}\n", returncode=1)
        if verb in ("kill-server", "start-server"):
            # A restart drops every transport, which is the whole point of it
            # — and it is what makes a wedged server usable again.
            if verb == "kill-server":
                self.connected.clear()
            self.wedged = False
            # Counted on the second half only: one restart is kill+start.
            if verb == 'start-server':
                self.server_restarts += 1
            return Result("")
        if verb == "devices":
            if self.wedged:
                return Result("", "cannot connect to daemon\n", 1)
            # The real listing: a header line, then "<serial>\t<state>".
            # `unlisted` is the case worth having — a display that answers
            # the handshake and still does not appear here.
            rows = "".join(
                f"{ip}:{settings.ADB_PORT}\tdevice\n"
                for ip in sorted(self.connected) if ip not in self.unlisted)
            return Result("List of devices attached\n" + rows)

        assert verb == "-s", args
        ip = self.ip_of(args[2])
        if ip not in self.connected or ip not in self.live:
            return Result("", "device offline\n", 1)
        action = args[3]
        if action == "get-state":
            return Result("device\n")
        if action == "push":
            return self._push(ip, args[4], args[5])
        if action == "install":
            return self._install(ip, args[4:])
        if action == "uninstall":
            return self._uninstall(ip, args[4])
        if action == "reboot":
            return self._reboot(ip)
        if action == "root":
            if not self.adb_root_allowed:
                return Result("", "adbd cannot run as root in production "
                                  "builds\n")
            self.adbd_root = True
            return Result("restarting adbd as root\n")
        if action == "remount":
            if not self.overlay_allowed or not self.adbd_root:
                return Result("", "remount failed\n", 1)
            self.overlay = True
            return Result("Using overlayfs for /system\nremount succeeded\n")
        if action == "shell":
            return self._shell(ip, args[4:])
        if action == "logcat":
            return Result("".join(f"I/{line}\n" for line in self.logcat))
        return Result("", f"unexpected command {action}\n", 1)

    # ── the device ──────────────────────────────────────────────────────
    def _push(self, ip, local, remote):
        from pathlib import Path as _Path

        text = _Path(local).read_text(encoding="utf-8")
        # An overlay is exactly what makes a /system push land, so a device
        # that refused one before `adb remount` accepts it afterwards.
        if (remote.startswith("/system/")
                and not (self.push_to_system or self.overlay)):
            return Result("", "adb: error: failed to copy: Read-only file "
                              "system\n", 1)
        self.timeline.append(f"push:{remote}")
        if remote not in self.refuse:
            self.live[ip]["files"][remote] = self._landed(remote, text)
            # A pushed file is not marked runnable; `_write_file` chmods it
            # afterwards, which this fake grants unconditionally.
            self.live[ip]["modes"][remote] = "0755"
        return Result("1 file pushed\n")

    def _install(self, ip, tail):
        """`adb -s <serial> install -r [-d] <path>` — an extension point.

        The default is the healthy device: the command succeeds. A scripted
        answer (`install_output` and friends) plays a device that refuses;
        a subclass overriding this method plays one that answers differently
        per attempt (the downgrade retry is the case that needs it).
        """
        self.install_attempts += 1
        self.timeline.append(f"install:{tail[-1] if tail else ''}")
        if self.install_output is not None:
            return Result(self.install_output, self.install_stderr,
                          self.install_returncode)
        return Result("Success\n")

    def _reboot(self, ip):
        if self.reboot_refused:
            return Result("", "error: closed\n", 1)
        self.timeline.append(f"reboot:{ip}")
        self.connected.discard(ip)
        self.down[ip] = self.reboot_downtime
        return Result("")

    def _uninstall(self, ip, package):
        if self.uninstall_fails:
            return Result("Failure [DELETE_FAILED_INTERNAL_ERROR]\n")
        self.timeline.append(f"uninstall:{package}")
        record = self.live[ip]
        record["packages"] = [name for name in record["packages"]
                              if name != package]
        return Result("Success\n")

    def _dumpsys(self, record, package):
        """`dumpsys package <pkg>`: scripted answers first, then the model."""
        if self.dumpsys_answers:
            return Result(self.dumpsys_answers.pop(0))
        if package in self.no_launcher:
            return Result("")
        return Result(_DUMPSYS if package in record["packages"] else "")

    def _shell(self, ip, command):
        record = self.live[ip]
        joined = " ".join(command)
        # A SCRIPT, not a word list. `adb shell` hands its arguments to the
        # device's shell unquoted, so anything with a space in it arrives
        # here already quoted by the caller (see client.script) — and is
        # taken apart again the same way the device's shell would.
        if command[:2] == ["sh", "-c"]:
            return self._script(record, _unquote(command[2]), root=False)
        if command[0] == "su":
            return self._su(record, command)
        if command[:3] == ["pm", "list", "packages"]:
            return Result("".join(f"package:{name}\n"
                                  for name in record["packages"]))
        if command[:2] == ["am", "force-stop"]:
            self.timeline.append(f"stop:{command[2]}")
            return Result("")
        if command[:3] == ["am", "start", "-n"]:
            if self.start_fails:
                return Result("Starting: Intent\n"
                              "Error: Activity class does not exist.\n")
            self.timeline.append(f"start:{command[3]}")
            return Result(
                f"Starting: Intent {{ cmp={command[3]} }}\n")
        if command[0] == "monkey":
            name = command[2]
            if name in self.monkey_fails or name not in record["packages"]:
                return Result("** No activities found to run, "
                              "monkey aborted.\n")
            self.timeline.append(f"monkey:{name}")
            return Result("Events injected: 1\n")
        if command[:4] == ["cmd", "package", "resolve-activity", "--brief"]:
            if (command[4] in record["packages"]
                    and command[4] not in self.no_launcher):
                return Result(f"priority=0\n{self.LAUNCHER}\n")
            return Result("No activity found\n")
        if command[:2] == ["dumpsys", "package"]:
            return self._dumpsys(record, command[2])
        if command[0] == "chmod":
            return Result("")
        if command == ["id"]:
            # Asked directly on the transport, which is how `restart_as_root`
            # proves adbd really came back as root rather than trusting the
            # command's own cheerful answer.
            return Result("uid=0(root) gid=0(root)\n" if self.adbd_root
                          else "uid=2000(shell) gid=2000(shell)\n")
        if command[0] == "getprop":
            return Result(self.props.get(command[1], "") + "\n")
        if command[:2] == ["cat", "/proc/uptime"]:
            return Result(f"{self.uptime} 0.0\n")
        if command[:2] == ["date", "+%s"]:
            return Result(f"{self.now}\n")
        if command[:2] == ["stat", "-c"]:
            return Result(f"{self.mtimes.get(command[3], 0)}\n")
        if command[0] == "logcat":
            return Result("".join(f"I/{line}\n" for line in self.logcat))
        if command[0] == "pidof":
            return Result("4711\n" if command[1] in self.app_running else "")
        return Result("", f"unexpected shell {joined}\n", 1)

    # ── the `su` this image carries ──────────────────────────────────────
    def _su(self, record, command):
        """Toybox `su`, which is what the field displays actually have.

        Its usage is `su [WHO [COMMAND...]]`, so it reads `-c` as a USER
        NAME and answers "invalid uid/gid". Modelled rather than smoothed
        over: a panel that only knows the Magisk `su -c` form reports a
        perfectly rootable display as unwritable, which is the bug this
        fake now makes impossible to reintroduce unnoticed.
        """
        if len(command) >= 2 and command[1] == "-c":
            if self.magisk_su:
                return self._script(record, _unquote(command[2]), root=True)
            return Result("", "su: invalid uid/gid '-c'\n", 1)
        if command[1:4] in (["0", "sh", "-c"], ["root", "sh", "-c"]):
            return self._script(record, _unquote(command[4]), root=True)
        return Result("", "usage: su [WHO [COMMAND...]]\n", 1)

    # ── the device's shell ───────────────────────────────────────────────
    def _script(self, record, text, *, root):
        parts = shlex.split(text)
        if text == "id":
            return Result("uid=0(root) gid=0(root)\n" if root
                          else "uid=2000(shell) gid=2000(shell)\n")
        if parts[:2] in (["[", "-e"], ["[", "-x"]):
            path = parts[2]
            # `[ -e p ] && echo YES || echo NO` — the branches are whatever
            # the caller chose to print, read off the script rather than
            # written down twice.
            said = [parts[i + 1] for i, word in enumerate(parts)
                    if word == "echo"]
            held = (path in record["files"] if parts[1] == "-e"
                    else record["modes"].get(path) == "0755")
            if held:
                return Result(f"{said[0]}\n")
            return Result(f"{said[1]}\n" if len(said) > 1 else "\n")
        if parts[:2] == ["stat", "-c"]:
            # `stat -c %s p 2>/dev/null || echo -1`. The size is the whole
            # point: this device answers it truthfully even when the write
            # that produced the file silently dropped its contents.
            path = parts[3]
            if path not in record["files"]:
                return Result("-1\n")
            return Result(f"{len(record['files'][path].encode())}\n")
        if parts[0] == "chmod":
            if parts[2] in record["files"]:
                record["modes"][parts[2]] = parts[1]
            return Result("")
        if parts[:2] == ["rm", "-f"]:
            self._unlink(record, parts[2], root=root)
            return Result("")
        if "mount -o rw,remount" in text:
            return self._transaction(record, text, root=root)
        return Result("", f"unexpected script {text}\n", 1)

    def _unlink(self, record, path, *, root):
        if path.startswith("/system/") and not (root and self.system_writable):
            return
        record["files"].pop(path, None)
        record["modes"].pop(path, None)

    def _transaction(self, record, text, *, root):
        r"""The remount-and-copy, run statement by statement.

        Taken apart the way a shell would rather than with one regex over
        the whole string: `rm -f /system/x; sync` matched by `rm -f (\S+)`
        captures `/system/x;`, semicolon included, and the removal then
        silently does nothing. That is a fake that passes while the product
        is broken, which is worse than no fake at all.
        """
        self.timeline.append("su")
        if not root:
            return Result("", "mount: Operation not permitted\n", 1)
        for statement in re.split(r"[;\n]|&&|\|\|", text):
            parts = shlex.split(statement.strip(" ()"))
            if not parts:
                continue
            if parts[0] == "cp" and len(parts) >= 3:
                self._copy(record, parts[1], parts[2])
            elif parts[0] == "chmod" and len(parts) >= 3:
                if parts[2] in record["files"]:
                    record["modes"][parts[2]] = parts[1]
            elif parts[0] == "rm":
                self._unlink(record, parts[-1], root=True)
        return Result("")

    def _copy(self, record, source, target):
        if target.startswith("/system/") and not self.system_writable:
            return
        if target in self.refuse:
            return
        if source not in record["files"]:
            return
        record["files"][target] = self._landed(target,
                                               record["files"][source])
        record["modes"][target] = record["modes"].get(source, "0644")
        self.timeline.append(f"copy:{target}")

    def _landed(self, target: str, text: str) -> str:
        """What the filesystem really keeps of a write to `target`.

        Everything, unless this display drops the contents of a /system
        write that did not go through an overlay — which is the whole fault
        being modelled, and the reason the panel now reads a file's SIZE
        back rather than asking whether it exists.
        """
        if (self.drops_content and target.startswith("/system/")
                and not self.overlay):
            return ""
        return text


def _unquote(token: str) -> str:
    """What the device's shell would make of one quoted argument."""
    parts = shlex.split(token)
    return parts[0] if parts else ""


_DUMPSYS = """
  Activity Resolver Table:
    Non-Data Actions:
      android.intent.action.MAIN:
        com.example.gebze/.MainActivity filter 8f2
          Action: "android.intent.action.MAIN"
          Category: "android.intent.category.LAUNCHER"

    versionCode=3 minSdk=21 targetSdk=35
    versionName=1.2.0
"""
