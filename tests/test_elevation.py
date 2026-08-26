#!/usr/bin/env python3
r"""The elevated-privilege flow (panel.elevation).

The app does not open unprivileged; that is right but was not enough on its
own: a user who double-clicked saw nothing and could not find out why. Now a
window appears and the app can be restarted as administrator from there.

These tests OPEN NO window; they pin down the pure functions that make the
real decision: which command elevates on which platform, and how the user's
answer ends the flow. A wrongly built command line means the user types a
password and watches nothing open.

PATH COMPARISON: the tests build POSIX plans on Windows too (in production a
plan is always built on its own system, but the check must run everywhere).
Path absolutisation follows the rules of the system RUNNING the test — on
Windows `/panel/app.py` → `D:\panel\app.py`. Expected values are therefore
derived from the same function (`os.path.abspath`) rather than written as
literals; in text that has been through shell and AppleScript escaping the
file name is searched for instead of the path. Windows CI caught this once.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from .support.base import ROOT  # noqa: F401  (sys.path setup)

from panel.adminkey import handoff
from panel.elevation import flow, privileges, prompt


_PLAN = {"kind": "osascript", "executable": "", "argv": [], "directory": "",
         "command": ["osascript", "-e", "..."]}


class FakeProcess:
    """A stand-in for `subprocess.Popen`.

    The default is a process that NEVER finishes (`poll()` → None): that is
    exactly how the elevation channel behaves in the field, not returning
    until the panel it started closes. The code must not wait for it.
    """

    def __init__(self, code=None, error=""):
        self._code = code
        self._error = error
        self.waited = False

    def poll(self):
        return self._code

    def wait(self, timeout=None):
        self.waited = True
        return self._code

    def communicate(self, timeout=None):
        self.waited = True
        return "", self._error

    def kill(self):
        self._code = -9


class ElevationPlan(unittest.TestCase):

    def test_windows_elevates_with_runas(self):
        plan = privileges.elevation_plan(
            "Windows", executable=r"C:\Python\python.exe",
            argv=[r"C:\panel\app.py", "--browser"], frozen=False,
            working_dir=r"C:\panel")

        self.assertEqual(plan["kind"], "runas")
        self.assertEqual(plan["executable"], r"C:\Python\python.exe")
        self.assertEqual(plan["argv"][-1], "--browser")
        self.assertTrue(plan["argv"][0].endswith("app.py"))
        self.assertEqual(plan["directory"], r"C:\panel")

    def test_a_packaged_app_does_not_repeat_argv0(self):
        """In a packaged app argv[0] is the application itself.

        Handed over a second time, the elevated process would take itself for
        an argument.
        """
        plan = privileges.elevation_plan(
            "Windows", executable=r"C:\panel\Panel.exe",
            argv=[r"C:\panel\Panel.exe", "--admin-password", "x"],
            frozen=True)

        self.assertEqual(plan["argv"], ["--admin-password", "x"])

    def test_script_mode_passes_an_absolute_path(self):
        """The elevated process may open in a different directory."""
        plan = privileges.elevation_plan("Darwin", executable="/usr/bin/py",
                                         argv=["app.py"], frozen=False,
                                         terminal=False)

        # The expected value is derived from the same function; "absolute"
        # is defined by the system running the test (see the module header).
        self.assertEqual(plan["argv"], [os.path.abspath("app.py")])

    def test_the_only_route_is_the_system_dialog(self):
        """No handing over to a terminal: elevation goes through the dialog.

        The user grants permission in the dialog; the app has no business with
        a terminal and no password ever passes through the app.
        """
        for system, expected in (("Darwin", "osascript"),
                                 ("Windows", "runas")):
            plan = privileges.elevation_plan(
                system, executable="/usr/bin/py",
                argv=["/panel/app.py"], frozen=False)
            self.assertEqual(plan["kind"], expected)
            self.assertNotIn("sudo", " ".join(plan["command"]))

    def test_the_secret_travels_as_a_path_and_never_as_a_value(self):
        """A COMMAND LINE IS PUBLIC — `ps` shows it to every account on the
        machine — and the build secret is the one value that must never be
        on one. What the elevation carries is the PATH of a file only this
        user can read, which the new process reads and deletes (see
        panel.adminkey.handoff)."""
        with mock.patch.dict(os.environ, {handoff.FILE_VAR: "/tmp/k.txt",
                                          handoff.SECRET_VAR: "s3cr3t"}):
            for system in ("Darwin", "Linux"):
                with self.subTest(system):
                    with mock.patch.object(privileges.shutil, "which",
                                           return_value="/usr/bin/pkexec"):
                        plan = privileges.elevation_plan(
                            system, executable="/usr/bin/py",
                            argv=["/panel/app.py"], frozen=False)
                    printed = " ".join(plan["command"])
                    self.assertIn(f"{handoff.FILE_VAR}=/tmp/k.txt", printed)
                    self.assertNotIn("s3cr3t", printed)

    def test_nothing_is_carried_when_there_is_nothing_to_carry(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(handoff.FILE_VAR, None)
            plan = privileges.elevation_plan("Darwin", executable="/usr/bin/py",
                                             argv=["/panel/app.py"],
                                             frozen=False)
        self.assertNotIn(handoff.FILE_VAR, " ".join(plan["command"]))

    def test_macos_elevates_with_the_system_dialog(self):
        plan = privileges.elevation_plan("Darwin", executable="/usr/bin/py",
                                         argv=["/panel/app.py"], frozen=False,
                                         working_dir="/panel")

        self.assertEqual(plan["kind"], "osascript")
        # The path is absolutised by the running system's rules (on Windows
        # "D:\panel\app.py"), so what is verified is that it entered the plan,
        # not the path itself. The comparison text has been through shell and
        # AppleScript escaping, so the raw string is not searched for (see the
        # module header).
        self.assertEqual(plan["argv"], [os.path.abspath("/panel/app.py")])
        script = plan["command"][-1]
        self.assertIn("with administrator privileges", script)
        # Without detaching, osascript waits until the app closes.
        self.assertIn("&", script)
        # If the new process dies at startup, this log is the only place left.
        self.assertIn(os.path.basename(privileges.log_path()), script)
        self.assertIn(os.path.basename(privileges.pid_path()), script)

    def test_the_macos_command_does_not_use_nohup(self):
        """`do shell script` runs without a terminal.

        Measured in the field: macOS's nohup fails there with "can't detach
        from console: Inappropriate ioctl for device" and the panel never
        started. `&` is enough to detach.
        """
        plan = privileges.elevation_plan("Darwin", executable="/usr/bin/py",
                                         argv=["/panel/app.py"], frozen=False,
                                         terminal=False)

        self.assertNotIn("nohup", plan["command"][-1])
        self.assertIn("< /dev/null", plan["command"][-1])

    def test_no_automatic_elevation_on_linux_without_pkexec(self):
        with mock.patch.object(privileges.shutil, "which", return_value=None):
            plan = privileges.elevation_plan("Linux",
                                             executable="/usr/bin/py",
                                             argv=["/panel/app.py"],
                                             frozen=False, terminal=False)
        self.assertEqual(plan["kind"], "")

        with mock.patch.object(privileges.shutil, "which",
                               return_value="/usr/bin/pkexec"):
            plan = privileges.elevation_plan("Linux",
                                             executable="/usr/bin/py",
                                             argv=["/panel/app.py"],
                                             frozen=False, terminal=False)
        self.assertEqual(plan["kind"], "pkexec")
        self.assertIn(os.path.abspath("/panel/app.py"), plan["command"])

    def test_applescript_quotes_are_escaped(self):
        """A path containing a quote must not break the command."""
        self.assertEqual(privileges.applescript_string('a"b\\c'),
                         '"a\\"b\\\\c"')


class ProtectedFolder(unittest.TestCase):
    """On macOS protected folders are known BEFORE the attempt.

    In the field a password was typed twice and "Operation not permitted" came
    back twice: the elevated process cannot read its own files on the Desktop.
    Saying so in advance means not asking for a password for nothing.
    """

    def test_the_desktop_is_protected(self):
        home = os.path.expanduser("~")
        for name in ("Desktop", "Documents", "Downloads"):
            self.assertEqual(
                privileges.protected_folder(os.path.join(home, name, "dap"),
                                            "Darwin"),
                name)

    def test_an_unprotected_folder_returns_empty(self):
        home = os.path.expanduser("~")
        self.assertEqual(
            privileges.protected_folder(os.path.join(home, "Projeler", "dap"),
                                        "Darwin"), "")

    def test_macos_only(self):
        path = os.path.join(os.path.expanduser("~"), "Desktop", "dap")
        for system in ("Windows", "Linux"):
            self.assertEqual(privileges.protected_folder(path, system), "")

    def test_the_flow_warns_in_a_protected_folder(self):
        """The elevated process cannot read the app there, so it is said.

        The warning reaches the failure window, which is the only window on
        this path now — there is no dialog before the attempt any more.
        """
        with (mock.patch.object(flow, "protected_folder",
                                return_value="Desktop"),
              mock.patch.object(flow, "elevation_plan",
                                return_value={"kind": "osascript"}),
              mock.patch.object(flow, "elevate",
                                return_value=(False, "denied")),
              mock.patch.object(flow, "show_failure") as shown):
            flow.require_elevation(lambda *_: None)

        hint = shown.call_args.kwargs.get("hint", "")
        self.assertIn("Desktop", hint)
        self.assertIn("move it out of that folder", hint)


class ElevationResult(unittest.TestCase):

    def test_manual_start_is_explained_on_a_system_without_a_route(self):
        ok, message = privileges.elevate({"kind": "", "executable": "",
                                          "argv": [], "command": [],
                                          "directory": ""})
        self.assertFalse(ok)
        self.assertIn("no automatic elevation", message)

    def test_a_refused_permission_is_reported(self):
        with (mock.patch.object(privileges.subprocess, "Popen",
                                return_value=FakeProcess(
                                    code=1, error="execution error: User "
                                                  "canceled. (-128)")),
              mock.patch.object(privileges, "_read_pid", return_value=0)):
            ok, message = privileges.elevate(_PLAN)

        self.assertFalse(ok)
        self.assertEqual(message, "Administrator permission was not granted")

    def test_a_successful_elevation(self):
        with (mock.patch.object(privileges.subprocess, "Popen",
                                return_value=FakeProcess()),
              mock.patch.object(privileges, "_read_pid", return_value=4242),
              mock.patch.object(privileges, "new_process_status",
                                return_value=(True, "")) as state):
            self.assertEqual(privileges.elevate(_PLAN), (True, ""))

        state.assert_called_once_with(pid=4242)

    def test_the_elevation_channel_is_not_waited_on(self):
        """The channel waits for the process it started; we do not.

        Waiting kept the old process alive until the new panel closed: it sat
        in the Dock as a second app and, when the panel closed, found the PID
        dead and wrongly opened a "died at startup" window.
        """
        process = FakeProcess()            # a channel that never ends
        with (mock.patch.object(privileges.subprocess, "Popen",
                                return_value=process) as popen,
              mock.patch.object(privileges, "_read_pid", return_value=4242),
              mock.patch.object(privileges, "new_process_status",
                                return_value=(True, ""))):
            self.assertEqual(privileges.elevate(_PLAN), (True, ""))

        self.assertFalse(process.waited, "the pipe must not be waited on")
        # In its own session: the new process must survive our exit.
        self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_a_process_that_is_not_up_is_a_failure(self):
        """A PID was written but the process died at startup — not a success."""
        with (mock.patch.object(privileges.subprocess, "Popen",
                                return_value=FakeProcess()),
              mock.patch.object(privileges, "_read_pid", return_value=4242),
              mock.patch.object(privileges, "new_process_status",
                                return_value=(False, "crashed"))):
            self.assertEqual(privileges.elevate(_PLAN), (False, "crashed"))


class _FakeKernel32:
    """Just enough of kernel32 to drive _windows_process_alive off Windows."""

    def __init__(self, handle: int, state: int):
        self.OpenProcess = mock.Mock(return_value=handle)
        self.WaitForSingleObject = mock.Mock(return_value=state)
        self.CloseHandle = mock.Mock(return_value=1)


class ProcessProbe(unittest.TestCase):
    """Asking whether a PID is up, without disturbing it.

    `os.kill(pid, 0)` is a POSIX idiom that does NOT carry over: on Windows
    signal 0 is signal.CTRL_C_EVENT, so the "question" is a Ctrl+C down the
    console — it tore the whole Windows CI run down mid-suite with a
    KeyboardInterrupt. Any other signal number is worse: os.kill() then calls
    TerminateProcess and kills the process it was asked about.
    """

    def _probe(self, handle: int, state: int = 0, last_error: int = 0):
        import ctypes

        kernel32 = _FakeKernel32(handle, state)
        with (mock.patch.object(ctypes, "WinDLL", return_value=kernel32,
                                create=True),
              mock.patch.object(ctypes, "get_last_error",
                                return_value=last_error, create=True)):
            alive = privileges._windows_process_alive(4242)
        return alive, kernel32

    def test_on_windows_no_signal_is_sent(self):
        with (mock.patch.object(privileges.platform, "system",
                                return_value="Windows"),
              mock.patch.object(privileges.os, "kill") as kill,
              mock.patch.object(privileges, "_windows_process_alive",
                                return_value=False) as probe):
            self.assertFalse(privileges.process_alive(4194303))

        kill.assert_not_called()
        self.assertEqual(probe.call_args.args, (4194303,))

    def test_a_running_process_does_not_signal_its_handle(self):
        alive, kernel32 = self._probe(handle=7, state=0x102)   # WAIT_TIMEOUT
        self.assertTrue(alive)
        kernel32.CloseHandle.assert_called_once_with(7)

    def test_a_signalled_handle_means_the_process_ended(self):
        alive, kernel32 = self._probe(handle=7, state=0)       # WAIT_OBJECT_0
        self.assertFalse(alive)
        kernel32.CloseHandle.assert_called_once_with(7)

    def test_an_unopenable_pid_is_gone(self):
        alive, _ = self._probe(handle=0, last_error=87)  # ERROR_INVALID_PARAM
        self.assertFalse(alive)

    def test_a_process_closed_to_us_counts_as_alive(self):
        """The whole point is checking an ELEVATED process from a plain one."""
        alive, _ = self._probe(handle=0, last_error=5)   # ERROR_ACCESS_DENIED
        self.assertTrue(alive)

    def test_a_missing_pid_is_never_probed(self):
        """0 and negatives address a process GROUP on POSIX, not a process."""
        with mock.patch.object(privileges.os, "kill") as kill:
            self.assertFalse(privileges.process_alive(0))
            self.assertFalse(privileges.process_alive(-1))
        kill.assert_not_called()


class NewProcessStatus(unittest.TestCase):

    def _files(self, pid: str, log: str):
        import tempfile

        directory = tempfile.mkdtemp(prefix="panel-elevation-")
        pid_file = os.path.join(directory, "p.pid")
        log_file = os.path.join(directory, "p.log")
        if pid is not None:
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write(pid)
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(log)
        return (mock.patch.object(privileges, "pid_path", lambda: pid_file),
                mock.patch.object(privileges, "log_path", lambda: log_file))

    def test_a_living_process_is_a_success(self):
        p, g = self._files(str(os.getpid()), "")
        with p, g:
            self.assertEqual(privileges.new_process_status(wait=0), (True, ""))

    def test_for_a_dead_process_the_last_log_line_is_the_reason(self):
        # Above 2**22: outside the PID range, definitely not alive.
        p, g = self._files("4194303", "something\nnohup: can't detach\n")
        with p, g:
            ok, message = privileges.new_process_status(wait=0)

        self.assertFalse(ok)
        self.assertIn("crashed at startup", message)
        self.assertIn("can't detach", message)

    def test_the_macos_privacy_protection_is_explained(self):
        """"Operation not permitted" gets confused with a file permission."""
        p, g = self._files("4194303",
                           "can't open file '/Users/x/Desktop/dap/app.py': "
                           "[Errno 1] Operation not permitted\n")
        with p, g, mock.patch.object(privileges.platform, "system",
                                     return_value="Darwin"):
            _ok, message = privileges.new_process_status(wait=0)

        self.assertIn("privacy protection", message)
        self.assertIn("sudo python3 app.py", message)

    def test_an_unreadable_pid_is_not_blamed(self):
        p, g = self._files(None, "")
        with p, g:
            self.assertEqual(privileges.new_process_status(wait=0), (True, ""))


class Flow(unittest.TestCase):
    """The startup path when the process is not elevated.

    One rule holds every test here together: no route ends with the panel
    open. The system's password box is the only question asked, and every
    answer except "granted" ends the process.
    """

    def test_the_system_box_is_asked_directly(self):
        """No window of ours comes first.

        It used to: a dialog asking whether to restart elevated, answered by
        the same person who then answered the system's box. Two dialogs, one
        decision, and the first one could not grant anything.
        """
        with (mock.patch.object(flow, "elevate",
                                return_value=(True, "")) as elevate,
              mock.patch.object(flow, "hide_dock_icon"),
              mock.patch.object(flow, "show_failure") as shown):
            self.assertEqual(flow.require_elevation(lambda *_: None), 0)

        elevate.assert_called_once()
        shown.assert_not_called()

    def test_a_refused_permission_does_not_open_the_application(self):
        with (mock.patch.object(flow, "elevate",
                                return_value=(False, "denied")),
              mock.patch.object(flow, "show_failure")):
            self.assertEqual(flow.require_elevation(lambda *_: None), 1)

    def test_the_dock_icon_is_removed_after_approval(self):
        """The old process lives through the verification but must not show.

        Visible, it looks like a second app next to the new panel.
        """
        with (mock.patch.object(flow, "hide_dock_icon") as hide,
              mock.patch.object(flow, "elevate", return_value=(True, ""))):
            self.assertEqual(flow.require_elevation(lambda *_: None), 0)

        hide.assert_called_once()

    def test_the_dock_icon_stays_while_the_password_box_is_up(self):
        """A system prompt from an invisible app looks like it came from
        nowhere — and after a failure the window explaining why has to be
        able to come to the front."""
        order = []
        with (mock.patch.object(flow, "hide_dock_icon",
                                side_effect=lambda: order.append("hide")),
              mock.patch.object(
                  flow, "elevate",
                  side_effect=lambda *_: (order.append("elevate"),
                                          (True, ""))[1])):
            flow.require_elevation(lambda *_: None)

        self.assertEqual(order, ["elevate", "hide"])

    def test_the_dock_icon_is_untouched_when_elevation_fails(self):
        with (mock.patch.object(flow, "elevate",
                                return_value=(False, "denied")),
              mock.patch.object(flow, "show_failure"),
              mock.patch.object(flow, "hide_dock_icon") as hide):
            flow.require_elevation(lambda *_: None)

        hide.assert_not_called()

    def test_no_handover_to_a_terminal(self):
        """Even a failed elevation does not divert to another route.

        The rule: privilege is asked for through the system dialog only, and
        it is asked once.
        """
        with (mock.patch.object(flow, "show_failure"),
              mock.patch.object(flow, "elevate",
                                return_value=(False, "crashed")) as elevate):
            self.assertEqual(flow.require_elevation(lambda *_: None), 1)

        self.assertEqual(elevate.call_count, 1)

    def test_a_failed_elevation_shows_the_reason(self):
        seen = []
        with (mock.patch.object(flow, "show_failure") as shown,
              mock.patch.object(
                  flow, "elevate",
                  return_value=(False,
                                "Administrator permission was not granted"))):
            code = flow.require_elevation(seen.append)

        self.assertEqual(code, 1)
        # The reason goes to the console AND to the window: an app that closes
        # silently after a refused prompt was the bug this replaced.
        self.assertIn("Administrator permission was not granted", " ".join(seen))
        self.assertIn("Administrator permission was not granted",
                      shown.call_args.args[0])

    def test_an_unattended_run_never_reaches_the_password_box(self):
        """PANEL_ELEVATION_PROMPT=0 → CI does not hang on a password prompt.

        This guard mattered less when a window came first and could refuse on
        its own. Now the next thing after this check IS the system box, so it
        has to stop the run before that.
        """
        with (mock.patch.dict(os.environ, {"PANEL_ELEVATION_PROMPT": "0"}),
              mock.patch.object(flow, "elevate") as elevate,
              mock.patch.object(flow, "show_failure") as shown):
            self.assertEqual(flow.require_elevation(lambda *_: None), 1)

        elevate.assert_not_called()
        shown.assert_not_called()

    def test_no_window_opens_in_an_unattended_environment(self):
        with mock.patch.dict(os.environ, {"PANEL_ELEVATION_PROMPT": "0"}):
            self.assertIsNone(prompt.show_failure())


if __name__ == "__main__":
    unittest.main()
