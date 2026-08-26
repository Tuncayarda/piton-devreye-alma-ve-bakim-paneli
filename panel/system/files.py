#!/usr/bin/env python3
"""Opening files with the OS handler and asking the OS to pick one.

`open_path` does not accept a path from the UI: it takes one the panel itself
wrote into a job record. Opening an arbitrary client-supplied path would be an
"open any file on this machine" endpoint even in a local service. `pick_file`
takes no path at all — the user chooses it.

Commands run with an argument list, never through a shell, so spaces and shell
characters in names are harmless.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from .. import settings
from .. import i18n


def log_path(name: str) -> Path:
    """Timestamped file for a long run's raw output.

    The output is too long to keep as queue rows (an IP assignment run writes
    two hundred lines) and too valuable to drop: it answers why a port did not
    complete. The queue shows it as a single openable row.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = settings.OUTPUT_DIR / f"{name}-{stamp}.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _open_command(path: Path, reveal: bool) -> list[str]:
    system = platform.system()
    if system == "Darwin":
        # -R selects the file in Finder.
        return ["open", "-R", str(path)] if reveal else ["open", str(path)]
    if system == "Windows":
        if reveal:
            return ["explorer", f"/select,{path}"]
        return ["cmd", "/c", "start", "", str(path)]
    return ["xdg-open", str(path.parent if reveal else path)]


def open_path(path: Path | str, reveal: bool = False) -> None:
    """Open a file, or reveal it in the file manager.

    Missing files raise: saying "opened" and doing nothing leaves the user
    hunting for the file.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(i18n.t("error.fileNotFound", path=target))
    try:
        # Windows explorer can return 1 after selecting a file; the exit code
        # means nothing here, so it is not checked.
        subprocess.run(_open_command(target, reveal), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10)
    except FileNotFoundError as exc:      # no opener command (some Linux)
        raise RuntimeError(i18n.t("error.noAppForFile")) from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError(i18n.t("error.fileNotOpened")) from exc


# ───────────────────────────────────────────────────────── file picker ──
# The browser sandbox does not reveal the real path of an `<input type=file>`
# selection, and the panel does not copy the file anywhere — it only keeps the
# path. So the picker opens in the OS, not in the page.
#
# The dialog blocks until the user answers; the calling request waits with it
# (the service is threaded, other requests are unaffected).
PICKER_TIMEOUT = 300.0                     # after 5 min treat it as cancelled

# Not written with "tell application System Events": that path asks for
# automation permission (TCC) on first run, and without it the picker never
# opens. This dialog belongs to osascript itself; the app is activated first
# so the window comes forward.
_MACOS_SCRIPT = '''
tell me to activate
set chosen to choose file with prompt "{title}"{types}
POSIX path of chosen
'''

_WINDOWS_SCRIPT = '''
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = "{title}"
$d.Filter = "{filter}"
$d.Multiselect = $false
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.WriteLine($d.FileName)
}}
'''


def _picker_command(title: str, extensions: tuple[str, ...]) -> list[str]:
    system = platform.system()
    if system == "Darwin":
        # ``choose file ... of type {"apk"}`` is not an extension filter on
        # macOS.  It is a UTI filter, and on machines without Android Studio
        # an APK is commonly classified only as dynamic ``public.data``; the
        # requested file is then visible but greyed out.  Let the native
        # dialog choose any file and validate the exact suffix in the API.
        types = ""
        return ["osascript", "-e",
                _MACOS_SCRIPT.format(title=title, types=types)]
    if system == "Windows":
        pattern = ";".join(f"*.{e}" for e in extensions) or "*.*"
        firmware = i18n.t("file.firmwareFilter", pattern=pattern)
        every = i18n.t("file.allFiles")
        file_filter = (f"{firmware}|{pattern}|{every} (*.*)|*.*"
                       if extensions else f"{every} (*.*)|*.*")
        return ["powershell", "-NoProfile", "-STA", "-Command",
                _WINDOWS_SCRIPT.format(title=title, filter=file_filter)]
    # Linux: the desktop environment's picker. With neither installed the
    # caller gets a clear error — returning empty would read as "cancelled".
    if shutil.which("zenity"):
        command = ["zenity", "--file-selection", f"--title={title}"]
        if extensions:
            pattern = " ".join(f"*.{e}" for e in extensions)
            command.append(f"--file-filter=Firmware | {pattern}")
        return command
    if shutil.which("kdialog"):
        pattern = " ".join(f"*.{e}" for e in extensions) or "*"
        return ["kdialog", "--getopenfilename", ".", pattern, "--title", title]
    raise RuntimeError(
        i18n.t("error.noFilePicker"))


# ─────────────────────────────────────────── back down to the user ──
# The panel normally runs elevated: it configures interfaces and drives the
# switches. A dialog opened by root, however, is not the operator's dialog.
# It belongs to root's session, so it starts in /var/root, its sidebar has
# none of the user's places, and macOS denies it the per-user folders it
# protects (Desktop, Documents, Downloads, iCloud Drive). What the operator
# sees is an empty window with nowhere to browse to and no file to pick.
#
# So the picker is pushed back down into the logged-in user's own session
# before it opens. Two steps, and both are needed:
#
#   launchctl asuser <uid>  puts the process in that user's GUI session — a
#                           dialog started outside it never comes forward;
#   sudo -H -u <name>       drops the root identity, so the dialog gets the
#                           user's home folder and their TCC permissions.
#
# Root elevated through the system's password dialog has no SUDO_USER, hence
# the console owner is the primary answer and SUDO_USER only the fallback for
# a panel started from a `sudo` shell.


def _console_user() -> tuple[str, int] | None:
    """(name, uid) of the user at the window server, or None if unknown."""
    name = ""
    try:
        name = subprocess.run(["stat", "-f", "%Su", "/dev/console"],
                              capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    if not name or name == "root":
        name = os.environ.get("SUDO_USER", "")
    if not name or name == "root":
        return None
    try:
        import pwd                       # POSIX only; not imported on Windows

        return name, pwd.getpwnam(name).pw_uid
    except (ImportError, KeyError):
        return None


def as_console_user(command: list[str]) -> list[str]:
    """`command` run in the logged-in user's session when this process is root.

    Returns the command untouched whenever there is nothing to hand it back
    to — not elevated, not macOS, or no one logged in graphically.

    Public because the file picker is no longer the only thing root cannot do
    on the operator's behalf: reading the service key off a USB stick is
    refused for the same reason (see `panel.adminkey.handback`).
    """
    if platform.system() != "Darwin" or os.geteuid() != 0:
        return command
    user = _console_user()
    if not user:
        return command
    name, uid = user
    return ["launchctl", "asuser", str(uid), "sudo", "-H", "-u", name,
            *command]


def pick_file(title: str = "",
              extensions: tuple[str, ...] = ()) -> str | None:
    """Open the OS file picker.

    Returns the full path, or None if the user cancelled. Raises RuntimeError
    when no picker can be opened at all.
    """
    command = as_console_user(_picker_command(title, extensions))
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=PICKER_TIMEOUT)
    except FileNotFoundError as exc:
        raise RuntimeError(i18n.t("error.pickerNotOpened")) from exc
    except subprocess.TimeoutExpired:
        return None                        # dialog left open: treat as cancel
    path = (result.stdout or "").strip()
    if path:
        return path
    # Cancel and real failure differ: zenity/kdialog only return 1, macOS
    # writes "User canceled. (-128)". The message is localised, so match the
    # AppleScript error number rather than the text.
    error = (result.stderr or "").strip()
    cancelled = not error or "-128" in error or "cancel" in error.lower()
    if result.returncode != 0 and not cancelled:
        raise RuntimeError(i18n.t("error.noFileSelected",
                                  detail=error.splitlines()[0][:120]))
    return None
