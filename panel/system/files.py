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
        types = ""
        if extensions:
            listed = ", ".join(f'"{e}"' for e in extensions)
            types = f" of type {{{listed}}}"
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


def pick_file(title: str = "",
              extensions: tuple[str, ...] = ()) -> str | None:
    """Open the OS file picker.

    Returns the full path, or None if the user cancelled. Raises RuntimeError
    when no picker can be opened at all.
    """
    command = _picker_command(title, extensions)
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
