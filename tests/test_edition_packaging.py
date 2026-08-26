#!/usr/bin/env python3
"""The build files and the edition table have to agree.

None of this is exercised by running the panel: a spec that names the wrong
file, a workflow whose tag pattern matches no edition, or two editions
sharing one Windows AppId all look fine until a release is cut — and the
AppId one is only noticed when an update to GDM removes Gaziray from an
engineer's laptop.

So the agreement is read back out of the files, as text. These tests know
nothing about YAML or Inno Setup syntax; they check that the few facts which
must line up actually do.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest

from .support.base import ROOT                   # noqa: F401  (sys.path)

from panel import settings                       # noqa: E402
from panel.editions import catalogue             # noqa: E402

SPEC = settings.ROOT / "dabp.spec"
ISS = settings.ROOT / "packaging" / "windows" / "dabp.iss"
CALLER = (settings.ROOT / ".github" / "workflows"
          / "build-commissioning-panel.yml")
BUILD = settings.ROOT / ".github" / "workflows" / "build-app.yml"
CI = settings.ROOT / ".github" / "workflows" / "ci.yml"


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def bash_runs() -> bool:
    """Is there a POSIX shell here that actually works?

    NOT `shutil.which("bash")`. A Windows runner carries `bash.exe` in
    System32 that is only a launcher for WSL: it is found on PATH, it exits
    1 when no distribution is installed, and the two tests below then fail
    for a reason that has nothing to do with what they check. The workflow's
    own `shell: bash` steps use Git's bash and are unaffected — which is why
    the property being proven here still holds where it matters.
    """
    try:
        done = subprocess.run(["bash", "-c", "echo ok"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and done.stdout.strip() == "ok"


BASH = bash_runs()


class ToolOutput(unittest.TestCase):
    """The one Turkish string, on a console that is not."""

    def test_the_product_name_survives_a_cp1252_stdout(self):
        """WHAT BROKE A RELEASE BUILD. Windows hands a Python process a
        cp1252 stdout, which has no room for U+0131 (the dotless i) — and
        the product name is spelled with one. The tool died with a
        UnicodeEncodeError that the build log connected to nothing. The
        encoding is forced now, and this pins it: the value the build reads
        is the name, spelled the way the table spells it.
        """
        tool = settings.ROOT / "tools" / "edition_info.py"
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                done = subprocess.run(
                    [sys.executable, str(tool), "--edition", edition.id,
                     "--field", "display_name"],
                    capture_output=True, text=True, encoding="utf-8",
                    env={**os.environ, "PYTHONIOENCODING": "cp1252",
                         "PYTHONUTF8": "0"})
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.strip(), edition.product_name)


class TagParsing(unittest.TestCase):
    """The one that silently ships the wrong version number."""

    def test_the_longest_match_is_used_everywhere(self):
        """`${TAG#*-v}` strips the SHORTEST prefix ending in "-v". An edition
        id may contain one of its own: "dap-vip-yatakli-v0.9.8" would strip
        only "dap-v" and the build would be named after "ip-yatakli-v0.9.8".
        Every site has to use "##"."""
        for path in (BUILD, CI):
            with self.subTest(path.name):
                text = read(path)
                self.assertNotIn("#*-v}", text.replace("##*-v}", ""))
                self.assertIn("##*-v}", text)

    @unittest.skipUnless(BASH, "no working POSIX shell on this machine")
    def test_the_shell_really_behaves_that_way(self):
        """Proof rather than assertion: run the two forms and compare."""
        script = """
          for TAG in dap-vip-yatakli-v0.9.8 dap-gdm-v0.9.8 dap-v0.9.7; do
            SHORT="${TAG#*-v}"; LONG="${TAG##*-v}"
            echo "$TAG $SHORT $LONG"
          done
        """
        result = subprocess.run(["bash", "-c", script], capture_output=True,
                                text=True, check=True)
        rows = [line.split() for line in result.stdout.split("\n") if line]
        by_tag = {tag: (short, long) for tag, short, long in rows}
        # The bug, still reproducible:
        self.assertEqual(by_tag["dap-vip-yatakli-v0.9.8"][0], "ip-yatakli-v0.9.8")
        # ...and the fix, for every shape of tag:
        for _tag, (_short, long) in by_tag.items():
            self.assertRegex(long, r"^\d+\.\d+\.\d+$")

    @unittest.skipUnless(BASH, "no working POSIX shell on this machine")
    def test_the_edition_can_be_recovered_from_every_tag(self):
        """The caller derives it with ${TAG#dap-} then %-v*."""
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                tag = f"dap-{edition.id}-v0.9.8"
                result = subprocess.run(
                    ["bash", "-c",
                     f'E="${{1#dap-}}"; echo "${{E%-v*}}"', "_", tag],
                    capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.strip(), edition.id)


class Workflows(unittest.TestCase):

    def test_every_edition_has_a_tag_pattern(self):
        """An edition nobody can tag is an edition nobody can release."""
        text = read(CALLER)
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                self.assertIn(f'"dap-{edition.id}-v*"', text)

    def test_every_edition_can_be_started_by_hand(self):
        text = read(CALLER)
        options = re.search(r"options: \[([^\]]+)\]", text)
        self.assertIsNotNone(options)
        listed = [name.strip() for name in options.group(1).split(",")]
        self.assertEqual(listed, list(catalogue.IDS))

    def test_the_build_secret_is_declared_and_passed(self):
        """Reusable workflows do NOT inherit secrets. Miss either half and
        the build quietly produces a package that can never open admin mode;
        nothing says so until somebody plugs a key into it in the field."""
        self.assertIn("DAP_ADMIN_KEY_SECRET:", read(BUILD))
        self.assertIn("secrets: inherit", read(CALLER))
        self.assertIn("DAP_ADMIN_KEY_SECRET: ${{ secrets.DAP_ADMIN_KEY_SECRET }}",
                      read(BUILD))

    def test_the_secret_never_reaches_a_command_line(self):
        """It goes in the environment, never into a `run:` line.

        A command line is readable in a process listing on the runner and
        appears in any `set -x` trace; masking in the log undoes neither. So
        every mention of it must be an `env:` assignment — either handing it
        to a step, or asking the one question that does not need the value
        itself, which is whether there is one at all.
        """
        allowed = (
            "DAP_ADMIN_KEY_SECRET: ${{ secrets.DAP_ADMIN_KEY_SECRET }}",
            "HAS_KEY_SECRET: ${{ secrets.DAP_ADMIN_KEY_SECRET != '' }}",
        )
        for line in read(BUILD).splitlines():
            if "secrets.DAP_ADMIN_KEY_SECRET" in line:
                self.assertIn(line.strip(), allowed, line.strip())

    def test_the_edition_names_are_not_copied_into_yaml(self):
        """They are read from the table by tools/edition_info.py, so adding
        an edition is one edit rather than three."""
        text = read(CALLER)
        for edition in catalogue.EDITIONS:
            self.assertNotIn(edition.product_name, text, edition.id)

    def test_the_helper_the_workflow_calls_actually_works(self):
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                result = subprocess.run(
                    [sys.executable, "tools/edition_info.py",
                     "--edition", edition.id, "--field", "app_name"],
                    cwd=settings.ROOT, capture_output=True, text=True,
                    check=True)
                self.assertEqual(result.stdout.strip(),
                                 f"dabp-{edition.id}")

    def test_an_unknown_edition_stops_the_helper(self):
        result = subprocess.run(
            [sys.executable, "tools/edition_info.py",
             "--edition", "not-a-customer", "--field", "app_name"],
            cwd=settings.ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


class Spec(unittest.TestCase):

    def test_the_spec_demands_an_edition(self):
        text = read(SPEC)
        self.assertIn("DAP_EDITION", text)
        self.assertIn("raise SystemExit", text)

    def test_a_guessable_secret_is_refused(self):
        """The one failure nobody would notice: the build succeeds, the
        package works, and the value protecting every other customer's
        package is short enough to search for."""
        text = read(SPEC)
        self.assertIn("MINIMUM_SECRET", text)
        found = re.search(r"MINIMUM_SECRET = (\d+)", text)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(int(found.group(1)), 24)

    def test_the_spec_accepts_a_recovered_digest(self):
        """Two situations arrive without warning and both need this: a
        rotation, where the old digest has to keep working while the field
        is updated, and a lost secret, where the digest recovered from a
        stick is the only way to keep cutting releases that recognise the
        keys already issued."""
        text = read(SPEC)
        self.assertIn("DAP_ADMIN_KEY_DIGESTS", text)
        self.assertIn("EXTRA_DIGESTS", text)
        # And the recovery tool the procedure names has to exist.
        self.assertTrue(
            (settings.ROOT / "tools" / "key_digest.py").is_file())

    def test_the_spec_never_prints_the_secret(self):
        """The build log is not a private place either."""
        for line in read(SPEC).splitlines():
            if "print(" in line:
                self.assertNotIn("ADMIN_SECRET", line, line.strip())

    def test_the_generated_stamp_is_not_committed(self):
        ignore = read(settings.ROOT / ".gitignore")
        self.assertIn("panel/editions/_stamp.py", ignore)
        tracked = subprocess.run(
            ["git", "ls-files", "panel/editions/_stamp.py"],
            cwd=settings.ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(tracked.stdout.strip(), "")

    def test_the_stamp_is_a_hidden_import(self):
        """It is imported behind a try/except, because it is absent from a
        source tree — so PyInstaller's static analysis cannot find it."""
        self.assertIn('"panel.editions._stamp"', read(SPEC))


class InnoSetup(unittest.TestCase):

    def test_every_name_can_be_passed_in(self):
        text = read(ISS)
        for name in ("MyAppName", "MyAppSlug", "MyAppId", "MyAppVersion",
                     "SourceDir", "OutputDir"):
            with self.subTest(name):
                self.assertIn(f"#ifndef {name}", text)

    def test_the_app_id_is_no_longer_hard_coded(self):
        self.assertIn("AppId={#MyAppId}", read(ISS))

    def test_the_workflow_passes_all_four(self):
        text = read(BUILD)
        for flag in ("/DMyAppSlug=", "/DMyAppName=", "/DMyAppId=",
                     "/DMyAppVersion="):
            with self.subTest(flag):
                self.assertIn(flag, text)

    def test_the_fallback_app_id_belongs_to_an_edition(self):
        """A build run by hand with no /D must not invent a GUID that
        updates over nothing — or worse, over something else."""
        found = re.search(r'#define MyAppId "(\{[^"]+\})"', read(ISS))
        self.assertIsNotNone(found)
        self.assertIn(found.group(1),
                      [e.windows_app_id for e in catalogue.EDITIONS])


if __name__ == "__main__":
    unittest.main()
