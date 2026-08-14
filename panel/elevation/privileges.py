#!/usr/bin/env python3
"""Checking for elevation and starting an elevated copy of the app."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time

# Ceiling on waiting for the user to answer the system's password dialog. The
# clock runs for as long as the dialog is on screen.
APPROVAL_TIMEOUT = 180.0

TITLE = "Administrator privileges are required"

EXPLANATION = (
    "The Commissioning and Maintenance Panel must run elevated.\n\n"
    "The panel reads and flushes the network interface and the ARP cache, "
    "writes IPs to devices and manages switch ports; none of that can be "
    "done reliably with ordinary user privileges."
)

# Folders macOS protects with TCC. Elevating an app that lives in one of them
# THROUGH THE SYSTEM DIALOG does not work: the elevated process is born under
# security_authtrampoline and is denied access to those folders. Seen twice in
# the field — first for `app.py`, then for `env/pyvenv.cfg`, both "Operation
# not permitted". Unprivileged processes can read the same folder, which kept
# the cause hidden for a long time.
#
# So this is reported BEFORE the attempt, to save the user typing a password
# for nothing.
PROTECTED_FOLDERS = ("Desktop", "Documents", "Downloads")


def log_path() -> str:
    """Where the elevated process's output is written.

    The new process starts detached in another session; if it dies at startup
    the user would see nothing. Its output lands here.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), "dap-elevation.log")


def pid_path() -> str:
    """The elevated process's PID — to check it really stayed up.

    The process starts in the background as another user and the launcher
    cannot see its exit code. The shell writes the PID here and we look a few
    seconds later to see whether it still exists.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), "dap-elevation.pid")


def manual_instructions(system: str | None = None) -> str:
    """What to do to start it yourself, per platform."""
    system = system or platform.system()
    if system == "Windows":
        return ("You can also right-click the application and choose "
                "\"Run as administrator\".")
    return "You can also start it from a terminal:    sudo python3 app.py"


def is_elevated() -> bool:
    """Is this process running elevated?

    One question is asked ("is this process admin"), and the answer comes from
    a different place per OS: the effective user id on POSIX, the shell's own
    query on Windows. The UI never sees the difference.
    """
    try:
        if hasattr(os, "geteuid"):
            return os.geteuid() == 0
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def applescript_string(value: str) -> str:
    """An AppleScript string — quotes and backslashes escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def protected_folder(directory: str = "",
                     system: str | None = None) -> str:
    """Is the app in a folder macOS protects? Returns the folder name or ""."""
    system = system or platform.system()
    if system != "Darwin":
        return ""
    path = os.path.realpath(
        directory or os.path.dirname(os.path.abspath(__file__)))
    home = os.path.realpath(os.path.expanduser("~"))
    for name in PROTECTED_FOLDERS:
        root = os.path.join(home, name)
        if path == root or path.startswith(root + os.sep):
            return name
    return ""


def elevation_plan(system: str | None = None, executable: str = "",
                   argv: list[str] | None = None,
                   frozen: bool | None = None,
                   working_dir: str = "",
                   terminal: bool | None = None) -> dict:
    """A plan for starting this same app elevated.

    A separate function because the real decision lives here and has to be
    testable: a wrongly built command line means the user types a password and
    watches nothing open.

    Returns: {"kind", "executable", "argv", "command", "directory"} — an empty
    `kind` means this platform has no automatic elevation and the user must
    start it manually.
    """
    system = system or platform.system()
    executable = executable or sys.executable
    argv = list(sys.argv if argv is None else argv)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    directory = working_dir or os.getcwd()

    # In a packaged app argv[0] is the app itself and must not be handed to
    # an interpreter a second time. Running as a script, argv[0] is the
    # script's path and IS required — without it the elevated process would
    # open an empty Python.
    if frozen:
        args = argv[1:]
    else:
        script = argv[0] if argv else ""
        args = ([os.path.abspath(script)] if script else []) + argv[1:]

    if system == "Windows":
        return {"kind": "runas", "executable": executable, "argv": args,
                "command": [], "directory": directory}

    if system == "Darwin":
        import shlex

        command = " ".join(shlex.quote(part) for part in [executable, *args])
        # Detached: without it osascript waits for the command to finish and
        # the dialog would hang for as long as the app stayed open.
        #
        # `nohup` is NOT used. `do shell script` runs without a terminal, and
        # macOS's nohup fails there with "can't detach from console:
        # Inappropriate ioctl for device" — the panel never started and nobody
        # could see why. `&` is enough to detach; input comes from /dev/null
        # and output goes to the log (the only place to look if the process
        # dies at startup).
        command = (f"cd {shlex.quote(directory)} && "
                   f"{command} < /dev/null > {shlex.quote(log_path())} 2>&1 & "
                   f"echo $! > {shlex.quote(pid_path())}")
        return {"kind": "osascript", "executable": executable, "argv": args,
                "directory": directory,
                "command": ["osascript", "-e",
                            f"do shell script {applescript_string(command)} "
                            "with administrator privileges"]}

    if shutil.which("pkexec"):
        # polkit clears the environment; the display variables are carried
        # over explicitly so a window can open.
        environment = [f"{name}={os.environ[name]}"
                       for name in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY")
                       if os.environ.get(name)]
        return {"kind": "pkexec", "executable": executable, "argv": args,
                "directory": directory,
                "command": ["pkexec",
                            *(["env", *environment] if environment else []),
                            executable, *args]}

    return {"kind": "", "executable": executable, "argv": args,
            "command": [], "directory": directory}


# Windows constants — see _windows_process_alive below.
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000            # signalled: the process has ended
_WAIT_TIMEOUT = 0x00000102             # not signalled: still running
_ERROR_ACCESS_DENIED = 5


def _windows_process_alive(pid: int) -> bool:
    """Is the PID up, asked the way Windows wants to be asked.

    `os.kill(pid, 0)` is a POSIX idiom with no counterpart here: on Windows
    signal 0 IS signal.CTRL_C_EVENT, so the call does not ask a question, it
    sends Ctrl+C down the console — which killed the whole test run instead of
    answering. Any other signal number would be worse: os.kill() then calls
    TerminateProcess and shoots the process it was supposed to be checking.

    So the process is opened for waiting only and waited on for zero
    milliseconds. A handle that is already signalled means the process has
    exited. GetExitCodeProcess is deliberately not used: a process that
    genuinely exited with code 259 is indistinguishable from STILL_ACTIVE.
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int,
                                     ctypes.c_uint32)
    # HANDLE is pointer-sized; the default c_int return would truncate it.
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        # An elevated process is there but closed to us — that counts as
        # alive. Anything else (no such PID) means it is gone.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        state = kernel32.WaitForSingleObject(handle, 0)
        if state == _WAIT_OBJECT_0:
            return False
        if state == _WAIT_TIMEOUT:
            return True
        return True                    # WAIT_FAILED: no answer, do not blame
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    """Does the PID still exist? Another user's process counts as alive."""
    # 0 and negatives address a whole process group on POSIX, not a process.
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:            # root's process: closed to us but there
        return True
    except OSError:
        return False
    return True


def _tcc_hint(text: str) -> str:
    """If macOS privacy protection left its signature, say what to do.

    Desktop, Documents and Downloads are protected: a process started from
    there through the system dialog may not be able to open its own file, and
    the error reads "Operation not permitted" — easily mistaken for a file
    permission problem.
    """
    if platform.system() != "Darwin":
        return ""
    if "not permitted" not in text.lower():
        return ""
    return ("\n\nmacOS privacy protection may have blocked it: the Desktop, "
            "Documents and Downloads folders are protected. Start it from a "
            "terminal with \"sudo python3 app.py\", or move the application "
            "out of those folders.")


def log_summary() -> str:
    """The log's last meaningful line — the reason shown to the user."""
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError:
        lines = []
    if not lines:
        return f"Details: {log_path()}"
    last = lines[-1][:200]
    return f"{last}{_tcc_hint(last)}\n\nDetails: {log_path()}"


def _read_pid() -> int:
    """The PID the shell wrote; 0 if not written yet."""
    try:
        with open(pid_path(), encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return 0


def new_process_status(wait: float = 2.0, pid: int = 0) -> tuple[bool, str]:
    """Did the elevated process stay up? Returns (alive, explanation).

    The detached process runs as another user and the launcher cannot see its
    exit code: that is exactly why a password could be typed and no window
    ever appear (on macOS `nohup` was dying in a terminal-less environment and
    nobody saw it). The PID the shell wrote is checked; if the process died at
    startup, the log's last line comes back as the reason.
    """
    time.sleep(max(0.0, wait))
    pid = pid or _read_pid()
    if not pid:
        return True, ""                # blaming it with no PID would be wrong
    if _process_alive(pid):
        return True, ""
    return False, "The elevated process crashed at startup.\n\n" + log_summary()


def elevate(plan: dict | None = None) -> tuple[bool, str]:
    """Start the elevated process. Returns (started, explanation).

    On success the caller MUST exit: two copies of the app must not write to
    the same DeviceMap and the same switch.
    """
    plan = plan or elevation_plan()
    if not plan["kind"]:
        return False, ("This system has no automatic elevation. "
                       + manual_instructions())
    # The previous run's log and PID are removed: this run's outcome will be
    # read from them and a stale file would point at the wrong reason.
    for path in (log_path(), pid_path()):
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        if plan["kind"] == "runas":
            import ctypes

            # list2cmdline: on Windows the process, not a shell, parses the
            # arguments — quoting paths with spaces by hand went wrong exactly
            # here.
            params = subprocess.list2cmdline(plan["argv"])
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", plan["executable"], params, plan["directory"],
                1)
            # ShellExecuteW is an old API: greater than 32 means success.
            if int(result) <= 32:
                # 1223 = the user declined the UAC dialog.
                return False, ("Administrator permission was not granted"
                               if int(result) == 1223 else
                               f"Could not restart (code {int(result)})")
            return True, ""

        # NOT WAITED ON. The elevation channel (security_authtrampoline on
        # macOS) waits for the process it started to FINISH: with
        # `subprocess.run` the old process stayed alive until the new panel
        # closed — a second icon in the Dock, and when the panel closed it
        # found a dead PID and wrongly opened an "it died at startup" dialog.
        # Measured in the field: a plain `do shell script` returns in 0.1 s
        # for a 12-second background process, the elevated one never does.
        #
        # So the process is started and THE PID THE SHELL WROTE is waited for:
        # the moment the PID file appears, the new process has been born.
        process = subprocess.Popen(plan["command"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   # Its own session: unaffected when we exit.
                                   start_new_session=True)
        deadline = time.monotonic() + APPROVAL_TIMEOUT
        while True:
            pid = _read_pid()
            if pid:
                # We saw the birth; now check whether it stayed up.
                return new_process_status(pid=pid)
            code = process.poll()
            if code is not None:
                _output, error_text = process.communicate()
                lines = (error_text or "").strip().splitlines()
                last = lines[-1] if lines else f"code {code}"
                if "-128" in last or "User canceled" in last:
                    return False, "Administrator permission was not granted"
                return False, f"Could not restart: {last}"
            if time.monotonic() >= deadline:
                process.kill()
                return False, "Administrator permission was not granted (no answer)"
            time.sleep(0.2)
    except Exception as exc:                       # noqa: BLE001
        return False, f"Could not restart: {type(exc).__name__}"
