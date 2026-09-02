#!/usr/bin/env python3
"""One rule for console children: they get no console window of their own.

The packaged panel has no console (dabp.spec, console=False), so on Windows
every console child — adb, powershell, cmd, netsh — opens a fresh black
window for the length of the call. The ADB screen made the cost vivid in the
field: thirty displays restarted at once meant a storm of terminals flashing
over the panel, and the reboot's own come-back polling kept them coming
after the run already looked finished, which read as "it is still doing
something and I cannot tell what".

CREATE_NO_WINDOW is the documented answer. It lives HERE, once, because it
was being rediscovered one module at a time (`system.interfaces` had it,
`system.files` grew its own, the ADB client had none) and every copy is a
call site the next one forgets.

Spread as ``**NO_CONSOLE`` — empty off Windows, so no call site grows a
platform branch.
"""
from __future__ import annotations

import subprocess
import sys

NO_CONSOLE = ({"creationflags": subprocess.CREATE_NO_WINDOW}
              if sys.platform == "win32" else {})
