"""Test suite for the Commissioning and Maintenance Panel.

All of it runs with one command:

    python3 -m unittest discover -s tests -t .

THE ENVIRONMENT IS PINNED HERE, NOT IN tests/support/base.py — and the split
is the point. Every test module is imported as ``tests.<name>``, so this
package module runs before any of them, under discovery and under a
single-module run (``python3 -m unittest tests.test_adb``) alike. base.py is
imported by CHOICE, and a test module that imports ``panel`` before
``from .support.base import ...`` (tests/test_adb.py does) executed the
panel's import-time reads first: panel/network/aliases.py reads
PANEL_NETWORK_WRITES exactly once, at import, and that ordering hole once
left four real IP aliases on a developer's network interface.

Only what must precede ``import panel`` lives here. Everything that needs
the package imported — the language pin, the edition activation, the test
base classes — stays in tests/support/base.py.
"""
import os
import sys
import tempfile
from pathlib import Path

# `import panel` has to resolve wherever the run was started from.
# tests/support/base.py re-exports ROOT for the modules that read files
# out of the checkout.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The panel's persistent data (configuration defaults) is written to a temp
# directory in tests: they neither read nor damage the user's real settings.
os.environ["PANEL_DATA_DIR"] = tempfile.mkdtemp(prefix="panel-data-")
# And the digests a service key written from source is remembered by: those
# live in the CHECKOUT (panel.adminkey.secret), so without this a test that
# writes a key would leave a file in the working tree and teach the
# developer's own panel to accept a key made up by the suite.
os.environ["DAP_ADMIN_KEY_STORE"] = tempfile.mkdtemp(
    prefix="panel-adminkey-")

# THE SUITE MUST NOT RECONFIGURE THIS COMPUTER. Scans and IP runs are
# exercised end to end against fake devices, and those jobs prepare the
# network before they start (see panel.api.tasks.network_prepare) — which ran
# `ifconfig alias` for real and left four addresses on a developer's live
# interface. Set before `panel` is imported, because the flag is read once at
# import. tests/test_network.py turns it back on around a faked subprocess.
os.environ["PANEL_NETWORK_WRITES"] = "0"

# Which package is under test. Every edition is a customer's now, so the
# suite runs as one of them; `setdefault`, so a run can be pointed at another
# on purpose (see tests/test_editions.py).
os.environ.setdefault("DAP_EDITION", "vip-yatakli")

# ...AND IT RUNS IN ADMIN MODE, which is what the secret below is for. The
# suite exercises every screen, and the admin screens exist only in admin
# mode; without the secret it would test the field half of the product and
# never the other. The secret is the bootstrap standing in for the first USB
# key, which cannot exist before it is written (see
# panel.editions.opens_as_admin). tests/test_adminkey.py takes it away again
# where the absence is the thing under test.
os.environ.setdefault("DAP_ADMIN_KEY_SECRET",
                      "a-build-secret-for-the-tests")
