#!/usr/bin/env python3
"""The one window this path still has: why the panel could not open.

There used to be another one first, asking whether to restart elevated. It
was a question we had no power to answer — only the operating system can
grant the privilege — so the user answered the same thing twice: once in our
window and once in the system's password box. The system prompt IS the
question now, and this window only appears when it could not be asked or the
answer was no.
"""
from __future__ import annotations

import os
import platform
import subprocess

from .. import i18n
from .privileges import (applescript_string, explanation,
                         manual_instructions, reasons, title)


def _html_page(message: str, manual: str, hint: str = "") -> str:
    import html as html_module

    reason_items = "".join(f"<li>{html_module.escape(reason)}</li>"
                           for reason in reasons())
    return f"""<!doctype html><html lang="{i18n.current()}"><head><meta charset="utf-8">
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:28px 30px; background:#101820; color:#e6edf3;
         font:15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size:17px; margin:0 0 14px; color:#ffd479; }}
  p {{ margin:0 0 12px; white-space:pre-wrap; }}
  ul {{ margin:0 0 14px; padding-left:20px; color:#c5d2de; }}
  li {{ margin:0 0 5px; }}
  .next {{ color:#c5d2de; }}
  .hint {{ color:#8fd3a6; font-size:13px; }}
  .manual {{ color:#9fb0c0; font-size:13px; }}
  .row {{ display:flex; gap:10px; margin-top:22px; }}
  button {{ font:inherit; padding:9px 16px; border-radius:8px; cursor:pointer;
           border:1px solid #33455a; background:#1b2735; color:#e6edf3; }}
  button:hover {{ border-color:#4d6a8c; }}
  .primary {{ background:#2f6feb; border-color:#2f6feb; color:#fff; }}
</style></head><body>
  <h1>{html_module.escape(title())}</h1>
  <p>{html_module.escape(message)}</p>
  <p class="next">{html_module.escape(i18n.t('elevate.neededFor'))}</p>
  <ul>{reason_items}</ul>
  {f'<p class="hint">{html_module.escape(hint)}</p>' if hint else ''}
  <p class="manual">{html_module.escape(manual)}</p>
  <div class="row">
    <button onclick="decide('quit')">{html_module.escape(i18n.t('elevate.quit'))}</button>
  </div>
<script>
  function decide() {{
    document.querySelectorAll('button').forEach(b => b.disabled = true);
    window.pywebview.api.decide('quit');
  }}
</script></body></html>"""


def _native_dialog(message: str, hint: str = "") -> None:
    """The operating system's own dialog when pywebview is unavailable."""
    system = platform.system()
    listed = "\n".join(f"  - {reason}" for reason in reasons())
    text = (f"{message}\n\n{i18n.t('elevate.neededFor')}\n{listed}\n\n"
            + (f"{hint}\n\n" if hint else "")
            + manual_instructions(system))
    try:
        if system == "Windows":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title(), 0x10)
            return

        if system == "Darwin":
            script = (f"display dialog {applescript_string(text)} "
                      f"with title {applescript_string(title())} "
                      "buttons {"
                      f"{applescript_string(i18n.t('elevate.quit'))}"
                      "} default button 1 with icon stop")
            subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=300)
    except Exception:                              # noqa: BLE001
        pass


def show_failure(message: str = "", hint: str = "") -> None:
    """Say why the panel could not open, and close.

    There is no choice to make here: the privilege was refused or could not be
    asked for, and without it the panel does not run. The window exists so
    that somebody who started the app by double-clicking it is not left with
    an icon that bounced once and did nothing.

    `PANEL_ELEVATION_PROMPT=0` opens no window at all: in an unattended run
    (CI, automated verification) a waiting dialog would hang the job forever.
    """
    if os.environ.get("PANEL_ELEVATION_PROMPT") == "0":
        return
    message = message or explanation()
    try:
        import webview
    except Exception:                              # noqa: BLE001
        _native_dialog(message, hint)
        return

    try:
        window = webview.create_window(
            title(), html=_html_page(message, manual_instructions(), hint),
            width=620, height=360, resizable=False,
            background_color="#101820")

        def decide(_value=None):
            window.destroy()

        window.expose(decide)
        webview.start()
    except Exception:                              # noqa: BLE001
        _native_dialog(message, hint)


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
