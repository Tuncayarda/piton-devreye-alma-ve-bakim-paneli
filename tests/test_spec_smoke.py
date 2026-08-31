#!/usr/bin/env python3
"""dabp.spec's pure top half, executed rather than merely read.

Every other test that looks at the spec reads it as TEXT (the pins in
tests/test_edition_packaging.py). Text pins hold names in place but prove
nothing about behaviour — and everything above the `Analysis(` call is plain
Python: the standalone catalogue load, the data-file gathering, the build
stamp. So it is compiled and run here, truncated at the `Analysis(` line
where PyInstaller proper begins, with the two PyInstaller touchpoints
stubbed (`SPECPATH`, `collect_all`).

THE REAL TREE IS NEVER WRITTEN TO. The one thing the executed half writes is
the stamp, at ROOT/panel/editions/_stamp.py — so ROOT is pointed at a
throwaway directory that mirrors the checkout through symlinks, where the
one written path is a real directory of the copy's own. A stamp left in the
real tree is harmless to a source run (panel/editions/runtime.py refuses to
read it unfrozen) but it is still a file this suite has no business leaving
behind, or racing another test over.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from . import ROOT
from panel.adminkey import secret
from panel.editions import catalogue

SPEC = ROOT / "dabp.spec"
# Stable by construction: the spec cannot build without calling Analysis,
# and everything below the call needs PyInstaller for real.
MARKER = "Analysis("


def _pure_top() -> str:
    """The spec source up to (excluding) the line that calls Analysis."""
    lines = SPEC.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if MARKER in line:
            return "".join(lines[:index])
    raise AssertionError(f"dabp.spec no longer contains {MARKER!r}")


def _pyinstaller_stub() -> dict:
    """Just enough of PyInstaller for the import and the collect calls.

    `collect_all` answers empty rather than raising, so the
    `collect_package(..., required=True)` calls take their success path —
    what they gather is PyInstaller's business, not this test's.
    """
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda package: ([], [], [])
    utils = types.ModuleType("PyInstaller.utils")
    utils.hooks = hooks
    package = types.ModuleType("PyInstaller")
    package.utils = utils
    return {"PyInstaller": package, "PyInstaller.utils": utils,
            "PyInstaller.utils.hooks": hooks}


class SpecSmoke(unittest.TestCase):

    def fake_root(self) -> Path:
        """A throwaway checkout: reads reach the real tree, writes stay here.

        Only what the executed half touches is mirrored. `panel/` and
        `panel/editions/` are REAL directories — the stamp is written under
        them, and a symlinked directory would carry the write through into
        the checkout.
        """
        root = Path(tempfile.mkdtemp(prefix="dabp-specroot-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for name in ("devicemaps", "field_scripts"):
            (root / name).symlink_to(ROOT / name, target_is_directory=True)
        package = root / "panel"
        package.mkdir()
        (package / "settings.py").symlink_to(ROOT / "panel" / "settings.py")
        (package / "messages").symlink_to(ROOT / "panel" / "messages",
                                          target_is_directory=True)
        editions_dir = package / "editions"
        editions_dir.mkdir()
        (editions_dir / "catalogue.py").symlink_to(
            ROOT / "panel" / "editions" / "catalogue.py")
        return root

    def run_spec(self, root: Path) -> dict:
        """Execute the pure top against the fake root; the namespace is the
        result.

        No key material of any kind: the suite's own bootstrap secret is
        taken away so the run exercises what a fork or a keyless local
        build does — DAP_ALLOW_NO_ADMIN_KEY is what lets that stamp at all.
        DAP_ALLOW_NO_ADB likewise makes the run independent of whether this
        checkout happens to hold the platform-tools download.
        """
        environment = {
            "DAP_EDITION": catalogue.IDS[0],
            "DAP_ALLOW_NO_ADMIN_KEY": "1",
            "DAP_ALLOW_NO_ADB": "1",
            "DAP_ALLOW_ANY_PYTHON": "1",
        }
        namespace = {"SPECPATH": str(root), "__name__": "dabp_spec_smoke"}
        code = compile(_pure_top(), str(SPEC), "exec")
        held = os.getcwd()
        self.addCleanup(os.chdir, held)
        os.chdir(root)
        with mock.patch.dict(os.environ, environment), \
                mock.patch.dict(sys.modules, _pyinstaller_stub()), \
                contextlib.redirect_stdout(io.StringIO()):
            for name in ("DAP_ADMIN_KEY_SECRET", "DAP_ADMIN_KEY_DIGESTS",
                         "DAP_ONEFILE"):
                os.environ.pop(name, None)
            # The spec really is executable configuration; running it is
            # the point of this file.
            exec(code, namespace)  # noqa: S102
        os.chdir(held)
        return namespace

    def test_the_top_half_runs_and_stamps_the_edition(self):
        """The failure this pins: a spec edit that only breaks at build time.

        The spec is exercised by CI on a release, which is exactly the
        wrong moment to learn that the catalogue no longer loads bare or
        that the stamp writer moved a name.
        """
        root = self.fake_root()
        namespace = self.run_spec(root)
        edition_id = catalogue.IDS[0]

        self.assertEqual(namespace["EDITION"].id, edition_id)
        # The write landed in the copy — the reason the copy exists.
        stamp_path = namespace["STAMP"]
        self.assertEqual(stamp_path,
                         root / "panel" / "editions" / "_stamp.py")
        stamp = stamp_path.read_text(encoding="utf-8")
        self.assertIn(f"EDITION = {edition_id!r}", stamp)
        # No package ever carries the secret, least of all one built
        # without any key material.
        self.assertIn("ADMIN_KEY_SECRET = None", stamp)
        self.assertIn("ADMIN_KEY_DIGESTS = ()", stamp)

        # The edition's own delivered device lists are in the bundle...
        bundled = [name for _source, name in namespace["DATA_FILES"]]
        for project in namespace["EDITION"].projects:
            if ROOT.joinpath(*project.source_path).exists():
                self.assertIn(project.map_name, bundled)
        # ...and nobody else's: with no build secret nothing is sealed,
        # and a foreign map in the clear would make the separation of the
        # customer packages cosmetic.
        foreign = {project.map_name for project in catalogue.ALL_PROJECTS
                   } - {project.map_name
                        for project in namespace["EDITION"].projects}
        for name in bundled:
            self.assertNotIn(name, foreign)
            self.assertFalse(name.endswith(".sealed"), name)

    def test_key_lines_derives_one_digest_from_a_secret(self):
        """The stamp a SECRET-HOLDING build writes: digest, never secret.

        `key_lines` is handed the secret only to derive the digest — and the
        digest it derives must be the very one the panel's own key reader
        computes, or a stick minted from source would not open the package
        built from the same secret.
        """
        namespace = self.run_spec(self.fake_root())
        fake_secret = "a-fake-build-secret-of-length"      # what CI exports
        self.assertGreaterEqual(len(fake_secret),
                                namespace["MINIMUM_SECRET"])
        namespace["ADMIN_SECRET"] = fake_secret
        with contextlib.redirect_stdout(io.StringIO()):
            text = namespace["key_lines"]()

        self.assertIn("ADMIN_KEY_SECRET = None", text)
        self.assertNotIn(fake_secret, text)
        digests = re.findall(r"[0-9a-f]{64}", text)
        self.assertEqual(
            digests,
            [secret.digest(secret.derive(fake_secret.encode("utf-8")))])


if __name__ == "__main__":
    unittest.main()
