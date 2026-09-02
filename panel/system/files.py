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
from .spawn import NO_CONSOLE as _NO_CONSOLE


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
                       timeout=10, **_NO_CONSOLE)
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

# Two lines here are load-bearing on Windows. `[Console]::OutputEncoding`:
# a redirected PowerShell writes in the OEM code page (cp857 on a Turkish
# machine) while Python reads back in the ANSI one (cp1254) — any Turkish
# character in the chosen path (OneDrive's localised Desktop folder is the
# common carrier) comes back mangled and the file is then "unreadable". The
# TopMost owner form: an unowned dialog
# opened by a windowless helper process may come up BEHIND the panel window,
# which reads as "the button does nothing".
_WINDOWS_SCRIPT = '''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = "{title}"
$d.Filter = "{filter}"
$d.Multiselect = $false
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.WriteLine($d.FileName)
}}
'''


# ── the desktop window, when there is one ───────────────────────────────
# `app.py` hands its window over at start-up. It is used for ONE thing: the
# file picker on Linux (see `_window_pick`). Kept as a module global rather
# than passed down through every caller because a file picker is a leaf
# operation — the four screens that open one have no business knowing which
# window engine is underneath.
#
# None in `--browser` mode and in the tests, and every use below treats that
# as "fall back to the command", not as an error.
_WINDOW = None
# Told apart from "the user cancelled", which is also nothing at all.
_NO_WINDOW = object()


def use_window(window) -> None:
    """Register the desktop window. Called once, from `app.py`."""
    global _WINDOW
    _WINDOW = window


def _window_pick(title: str, extensions: tuple[str, ...]):
    """The window engine's own file dialog.

    ONLY ON LINUX, and that is the whole point of it. macOS and Windows have
    a native dialog this panel already opens well — the macOS one needs the
    UTI workaround below and the Windows one a localised filter, both of them
    tuned. Linux had neither: the picker there shells out to `zenity` or
    `kdialog`, and on a machine carrying neither the operator simply could not
    choose a firmware file or an APK. The window is already a GTK or Qt one,
    so the dialog is there for the asking and needs nothing installed.

    Returns `_NO_WINDOW` when there is no window to ask (browser mode, tests),
    a path when one was chosen, or None when the operator cancelled.
    """
    window = _WINDOW
    if window is None or platform.system() not in ("Linux", "FreeBSD"):
        return _NO_WINDOW
    try:
        import webview                                   # noqa: PLC0415

        types = ()
        if extensions:
            pattern = ";".join(f"*.{e}" for e in extensions)
            firmware = i18n.t("file.firmwareFilter", pattern=pattern)
            every = i18n.t("file.allFiles")
            types = (f"{firmware} ({pattern})", f"{every} (*.*)")
        chosen = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False, file_types=types)
    except Exception:
        # A window engine that cannot open a dialog is not a reason to give
        # up: the command path below may still work.
        return _NO_WINDOW
    if not chosen:
        return None                       # cancelled
    return str(chosen[0]) if isinstance(chosen, (list, tuple)) else str(chosen)


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
                              timeout=5, check=False).stdout.strip()
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
    chosen = _window_pick(title, extensions)
    if chosen is not _NO_WINDOW:
        return chosen
    command = as_console_user(_picker_command(title, extensions))
    try:
        # UTF-8 on purpose, not the locale default: the Windows script above
        # switches its output to UTF-8, and macOS/Linux pickers already write
        # it. `errors="replace"` because a mangled error line must not become
        # a second exception on top of the first.
        result = subprocess.run(command, capture_output=True,
                                encoding="utf-8", errors="replace",
                                timeout=PICKER_TIMEOUT, check=False,
                                **_NO_CONSOLE)
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


# ─────────────────────────────────────────────────── the save dialog ──
# The mirror of `pick_file`, and it exists for the same reason: a path typed
# into the browser and posted here would make the endpoint behind it "write a
# file anywhere on this machine". The operator chooses the folder in their own
# OS dialog, and only what that dialog returned is ever written.
#
# The three platform paths are the ones `_picker_command` already uses, in
# their saving form — `choose file name`, SaveFileDialog, `--save`. The
# overwrite question is left to each dialog: every one of them asks, and
# asking again in the panel would be a second confirmation for a file the
# operator has just named.
_MACOS_SAVE_SCRIPT = '''
tell me to activate
set chosen to choose file name with prompt "{title}" default name "{name}"
POSIX path of chosen
'''

# The same UTF-8 and TopMost lines as `_WINDOWS_SCRIPT`, for the same two
# Windows faults.
_WINDOWS_SAVE_SCRIPT = '''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$d = New-Object System.Windows.Forms.SaveFileDialog
$d.Title = "{title}"
$d.Filter = "{filter}"
$d.FileName = "{name}"
$d.OverwritePrompt = $true
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.WriteLine($d.FileName)
}}
'''


def _save_filter(extensions: tuple[str, ...]) -> tuple[str, str]:
    """(pattern, human name) for the file type being written."""
    pattern = ";".join(f"*.{e}" for e in extensions) or "*.*"
    return pattern, i18n.t("file.jsonFilter", pattern=pattern)


def _window_save(title: str, name: str):
    """The window engine's own save dialog. Linux only, as with `_window_pick`.

    Returns `_NO_WINDOW` when there is no window to ask, a path when one was
    named, or None when the operator cancelled.
    """
    window = _WINDOW
    if window is None or platform.system() not in ("Linux", "FreeBSD"):
        return _NO_WINDOW
    try:
        import webview                                   # noqa: PLC0415

        chosen = window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=name)
    except Exception:
        return _NO_WINDOW                 # the command path may still work
    if not chosen:
        return None                       # cancelled
    return str(chosen[0]) if isinstance(chosen, (list, tuple)) else str(chosen)


def _save_command(title: str, name: str,
                  extensions: tuple[str, ...]) -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return ["osascript", "-e",
                _MACOS_SAVE_SCRIPT.format(title=title, name=name)]
    if system == "Windows":
        pattern, human = _save_filter(extensions)
        every = i18n.t("file.allFiles")
        file_filter = f"{human}|{pattern}|{every} (*.*)|*.*"
        return ["powershell", "-NoProfile", "-STA", "-Command",
                _WINDOWS_SAVE_SCRIPT.format(title=title, name=name,
                                            filter=file_filter)]
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--save",
                "--confirm-overwrite", f"--title={title}",
                f"--filename={name}"]
    if shutil.which("kdialog"):
        pattern, _human = _save_filter(extensions)
        return ["kdialog", "--getsavefilename", name,
                pattern.replace(";", " "), "--title", title]
    raise RuntimeError(i18n.t("error.noFilePicker"))


def pick_save_path(title: str = "", name: str = "",
                   extensions: tuple[str, ...] = ()) -> str | None:
    """Ask the operator where to write a file. Returns the path, or None.

    None means they cancelled — not an error, and the caller writes nothing.
    RuntimeError means no dialog could be opened at all.

    The suffix is put back on when the dialog returns one without it: the
    macOS `choose file name` panel lets a name be typed with no extension,
    and a JSON list saved as `benches` is one the import filter will not
    even show the operator next time.
    """
    chosen = _window_save(title, name)
    if chosen is _NO_WINDOW:
        command = as_console_user(_save_command(title, name, extensions))
        try:
            # UTF-8 for the same reason as `pick_file` above.
            result = subprocess.run(command, capture_output=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=PICKER_TIMEOUT, check=False,
                                    **_NO_CONSOLE)
        except FileNotFoundError as exc:
            raise RuntimeError(i18n.t("error.pickerNotOpened")) from exc
        except subprocess.TimeoutExpired:
            return None                    # dialog left open: treat as cancel
        chosen = (result.stdout or "").strip()
        if not chosen:
            error = (result.stderr or "").strip()
            cancelled = not error or "-128" in error or "cancel" in error.lower()
            if result.returncode != 0 and not cancelled:
                raise RuntimeError(i18n.t("error.noFileSelected",
                                          detail=error.splitlines()[0][:120]))
            return None
    if not chosen:
        return None
    target = Path(chosen)
    if extensions and target.suffix.lower().lstrip(".") not in extensions:
        target = target.with_name(f"{target.name}.{extensions[0]}")
    return str(target)
