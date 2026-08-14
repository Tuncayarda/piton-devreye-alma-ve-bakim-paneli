#!/usr/bin/env python3
"""Asking the user, in a window, whether to restart elevated."""
from __future__ import annotations

import os
import platform
import subprocess

from .privileges import (EXPLANATION, TITLE, applescript_string,
                         elevation_plan, manual_instructions)


def _html_page(message: str, can_elevate: bool, manual: str,
               hint: str = "") -> str:
    import html as html_module

    buttons = (
        '<button class="primary" onclick="decide(\'elevate\')">'
        'Restart as administrator</button>' if can_elevate else "")
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:28px 30px; background:#101820; color:#e6edf3;
         font:15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size:17px; margin:0 0 14px; color:#ffd479; }}
  p {{ margin:0 0 12px; white-space:pre-wrap; }}
  .hint {{ color:#8fd3a6; font-size:13px; }}
  .manual {{ color:#9fb0c0; font-size:13px; }}
  .row {{ display:flex; gap:10px; margin-top:22px; }}
  button {{ font:inherit; padding:9px 16px; border-radius:8px; cursor:pointer;
           border:1px solid #33455a; background:#1b2735; color:#e6edf3; }}
  button:hover {{ border-color:#4d6a8c; }}
  .primary {{ background:#2f6feb; border-color:#2f6feb; color:#fff; }}
</style></head><body>
  <h1>{TITLE}</h1>
  <p>{html_module.escape(message)}</p>
  {f'<p class="hint">{html_module.escape(hint)}</p>' if hint else ''}
  <p class="manual">{html_module.escape(manual)}</p>
  <div class="row">
    {buttons}
    <button onclick="decide('quit')">Quit</button>
  </div>
<script>
  function decide(choice) {{
    document.querySelectorAll('button').forEach(b => b.disabled = true);
    window.pywebview.api.decide(choice);
  }}
</script></body></html>"""


def _native_dialog(message: str, can_elevate: bool, hint: str = "") -> str:
    """The operating system's own dialog when pywebview is unavailable."""
    system = platform.system()
    text = (f"{message}\n\n" + (f"{hint}\n\n" if hint else "")
            + manual_instructions(system))
    try:
        if system == "Windows":
            import ctypes

            if not can_elevate:
                ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)
                return "quit"
            # MB_YESNO | MB_ICONWARNING; 6 = Yes
            answer = ctypes.windll.user32.MessageBoxW(
                None, text + "\n\nRestart as administrator?",
                TITLE, 0x04 | 0x30)
            return "elevate" if int(answer) == 6 else "quit"

        if system == "Darwin" and can_elevate:
            script = (f"display dialog {applescript_string(text)} "
                      f"with title {applescript_string(TITLE)} "
                      'buttons {"Quit", "Restart as administrator"} '
                      'default button 2 with icon caution')
            result = subprocess.run(["osascript", "-e", script],
                                    capture_output=True, text=True,
                                    timeout=300)
            return ("elevate" if "Restart" in (result.stdout or "")
                    else "quit")
    except Exception:                              # noqa: BLE001
        pass
    return "quit"


def ask(message: str = "", can_elevate: bool | None = None,
        hint: str = "") -> str:
    """Ask the user in a window. Returns "elevate" | "quit".

    Closing the window is also "quit": no path leads to an unprivileged start.

    `PANEL_ELEVATION_PROMPT=0` opens no window at all: in an unattended run
    (CI, automated verification) a waiting dialog would hang the job forever.
    """
    if os.environ.get("PANEL_ELEVATION_PROMPT") == "0":
        return "quit"
    message = message or EXPLANATION
    if can_elevate is None:
        can_elevate = bool(elevation_plan()["kind"])
    try:
        import webview
    except Exception:                              # noqa: BLE001
        return _native_dialog(message, can_elevate, hint)

    choice = {"value": "quit"}
    try:
        window = webview.create_window(
            TITLE, html=_html_page(message, can_elevate,
                                   manual_instructions(), hint),
            width=620, height=340, resizable=False,
            background_color="#101820")

        def decide(value):
            choice["value"] = "elevate" if value == "elevate" else "quit"
            window.destroy()

        window.expose(decide)
        webview.start()
    except Exception:                              # noqa: BLE001
        return _native_dialog(message, can_elevate, hint)
    return choice["value"]


def hide_dock_icon() -> None:
    """macOS: remove this process's Dock icon.

    After elevation is approved the old process lives a few seconds longer —
    it is verifying the new process stayed up (see new_process_status), and
    that check is what catches "died at startup" errors, so it must stay. But
    during it TWO icons sat in the Dock and the panel looked like it had
    opened twice. With the window gone there is no reason for the icon.
    """
    if platform.system() != "Darwin":
        return
    try:
        from AppKit import NSApplication

        # 1 = NSApplicationActivationPolicyAccessory: the process lives on but
        # is invisible in the Dock and the app switcher.
        NSApplication.sharedApplication().setActivationPolicy_(1)
    except Exception:                              # noqa: BLE001
        pass
