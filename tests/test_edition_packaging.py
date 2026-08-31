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

import importlib.util
import os
import re
import struct
import subprocess
import sys
import unittest

from .support.base import ROOT                   # noqa: F401  (sys.path)

from panel import settings
from panel.editions import catalogue

SPEC = settings.ROOT / "dabp.spec"
ISS = settings.ROOT / "packaging" / "windows" / "dabp.iss"
CALLER = (settings.ROOT / ".github" / "workflows"
          / "build-commissioning-panel.yml")
BUILD = settings.ROOT / ".github" / "workflows" / "build-app.yml"
CI = settings.ROOT / ".github" / "workflows" / "ci.yml"
REPO_CHECKS = settings.ROOT / ".github" / "workflows" / "repo-checks.yml"


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
                              text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and done.stdout.strip() == "ok"


BASH = bash_runs()


class BuildStep(unittest.TestCase):
    """What the packaging step has to hand the spec."""

    def test_the_appimage_takes_the_binary_name_from_the_build(self):
        """Every executable is named after its edition now
        (`catalogue.app_name`), and PyInstaller's onedir output is
        dist/<name>/<name>. A packaging script that writes "dabp" down
        instead of reading it builds an AppDir around a file that is not
        there — which is how the Linux half of a release build died on
        `chmod: cannot access .../usr/bin/dabp`."""
        text = (settings.ROOT / "packaging" / "appimage.sh").read_text(
            encoding="utf-8")
        self.assertIn('APP_BINARY_NAME="$(basename "$DIST_DIR")"', text)
        self.assertNotIn('APP_BINARY_NAME="dabp"', text)

    def test_the_build_step_tells_the_spec_which_edition(self):
        """`dabp.spec` refuses to guess: with no DAP_EDITION it stops and
        names the editions, because "whichever DeviceMap the tree happens to
        hold" is not an answer anybody meant to give. The step that runs
        PyInstaller therefore has to say which package is being built — it
        did not, and every platform of a release build died there on a
        variable nobody had set."""
        text = read(BUILD)
        start = text.index("- name: Clean PyInstaller build")
        step = text[start:].split("\n      - name:")[0]
        self.assertIn("python -m PyInstaller", step)
        self.assertIn("DAP_EDITION:", step)


class Icons(unittest.TestCase):
    """The application's own icon, in the three shapes the platforms want."""

    ICONS = settings.ROOT / "icons"
    APPIMAGE = settings.ROOT / "packaging" / "appimage.sh"

    def test_all_three_icons_are_committed(self):
        """No build machine makes them: `tools/make_icons.py` is run by hand
        where the SVG tools are, and its output is what ships. Missing, the
        packages fall back to no icon at all and nothing fails."""
        for name, magic in (("app.png", b"\x89PNG"),
                            ("app.icns", b"icns"),
                            ("app.ico", b"\x00\x00\x01\x00")):
            with self.subTest(name):
                path = self.ICONS / name
                self.assertTrue(path.is_file(), path)
                self.assertTrue(path.read_bytes().startswith(magic))

    def test_the_ico_carries_every_size_windows_asks_for(self):
        """Windows picks a different entry for the taskbar, for Explorer and
        for the window corner. One 256 pixel image scaled down to 16 is mud,
        which is why the file is written with a list of sizes."""
        data = (self.ICONS / "app.ico").read_bytes()
        count = struct.unpack_from("<H", data, 4)[0]
        # A width byte of 0 means 256 — the format has one byte for it.
        sizes = {data[6 + 16 * index] or 256 for index in range(count)}
        self.assertLessEqual({16, 32, 48, 256}, sizes)

    def test_every_platform_is_pointed_at_its_own(self):
        """Three formats because three platforms disagree, and each is named
        where that platform's package is built."""
        spec = read(SPEC)
        self.assertIn('ICO = ROOT / "icons" / "app.ico"', spec)
        self.assertIn('ICNS = ROOT / "icons" / "app.icns"', spec)
        self.assertIn("SetupIconFile=..\\..\\icons\\app.ico", read(ISS))
        self.assertIn('ICON="$APP_ROOT/icons/app.png"',
                      self.APPIMAGE.read_text(encoding="utf-8"))


class AndroidTools(unittest.TestCase):
    """The adb executable travels INSIDE the package.

    None of this is exercised by running the panel from a source tree, where
    a developer's own adb is on PATH. On the machines these are installed on
    there is no Android tooling at all, and the whole Compartment LCD half of
    the product — reading a display, installing an APK, the ADB screen —
    reports "the adb command was not found" on hardware that is perfectly
    healthy. That was the failure; this is the agreement that fixes it, read
    back out of the build files as text.
    """

    APPIMAGE = settings.ROOT / "packaging" / "appimage.sh"

    def test_the_spec_ships_the_tools_folder(self):
        spec = read(SPEC)
        self.assertIn('PLATFORM_TOOLS = ROOT / "platform-tools"', spec)
        self.assertIn('data.append((str(PLATFORM_TOOLS), "platform-tools"))',
                      spec)

    def test_a_tree_without_the_tools_refuses_to_build(self):
        """FATAL, NOT SKIPPED — and it was the other way round.

        "Printed either way, so a release build that forgot the step says so
        in the log" was the rule, and it did not hold: CI never fetched the
        tools at all, so every package it produced shipped without adb and
        nobody read the line. A note in a build log is not a gate.

        The escape hatch stays for a developer who means it, named the same
        way the admin key's is.
        """
        spec = read(SPEC)
        self.assertIn("if ADB_BINARY.is_file():", spec)
        self.assertIn("DAP_ALLOW_NO_ADB", spec)
        guard = spec.split("ADB_BINARY.is_file()")[1][:2000]
        self.assertIn("raise SystemExit", guard)

    def test_the_bundled_tool_must_match_the_build_target(self):
        """A macOS adb unzipped on a Windows runner looks right and is not.

        `binary.py` would find no `adb.exe`, fall back to PATH and ship a
        package that is quietly missing the tool — the same silent failure,
        arrived at from the other direction.
        """
        spec = read(SPEC)
        self.assertIn('ADB_NAME = "adb.exe" if sys.platform == "win32"', spec)

    def test_the_runtime_looks_in_the_bundle_before_the_path(self):
        """Otherwise shipping the executable changes nothing: a machine with
        no adb on PATH would still find none."""
        source = (settings.ROOT / "panel" / "adb" / "binary.py").read_text(
            encoding="utf-8")
        self.assertLess(source.index("found = bundled()"),
                        source.index('shutil.which("adb")'))

    def test_the_appimage_restores_the_executable_bit(self):
        """PyInstaller copies these in as DATA, and a data file is not
        marked runnable. Without this the AppImage carries an adb it cannot
        start — which on screen is indistinguishable from carrying none."""
        text = self.APPIMAGE.read_text(encoding="utf-8")
        self.assertIn('chmod 0755 "$APPDIR/usr/bin/platform-tools/adb"', text)

    def test_windows_needs_no_line_of_its_own(self):
        """Inno Setup already takes the whole onedir output recursively, and
        Windows has no executable bit. Asserted so that the asymmetry with
        the AppImage script reads as a decision rather than as an omission.
        """
        iss = read(ISS)
        self.assertIn("recursesubdirs createallsubdirs", iss)
        self.assertIn("platform-tools", iss)


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
                         "PYTHONUTF8": "0"}, check=False)
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
        for (_short, long) in by_tag.values():
            self.assertRegex(long, r"^\d+\.\d+\.\d+$")

    @unittest.skipUnless(BASH, "no working POSIX shell on this machine")
    def test_the_edition_can_be_recovered_from_every_tag(self):
        """The caller derives it with ${TAG#dap-} then %-v*."""
        for edition in catalogue.EDITIONS:
            with self.subTest(edition.id):
                tag = f"dap-{edition.id}-v0.9.8"
                result = subprocess.run(
                    ["bash", "-c",
                     'E="${1#dap-}"; echo "${E%-v*}"', "_", tag],
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
            # The escape hatch asks the same yes/no question — is there a
            # secret at all — and the value itself still never leaves the
            # env block.
            ("DAP_ALLOW_NO_ADMIN_KEY: "
             "${{ secrets.DAP_ADMIN_KEY_SECRET != '' && '0' || '1' }}"),
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
            cwd=settings.ROOT, capture_output=True, text=True, check=False)
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

    def test_the_app_id_comes_from_the_table_and_is_escaped(self):
        """Two things at once, and the second one cost a release build.

        The GUID is not hard coded — it comes from the edition table — AND
        the brace in front of it is DOUBLED. "{" opens a constant in Inno
        Setup, so `AppId={#MyAppId}` expands to `{GUID}` and the compiler
        stops with `Unknown constant "1D33CE96-…"`. "{{" is the escape for a
        literal brace and is what the hard-coded line used to have.
        """
        text = read(ISS)
        self.assertIn("AppId={{#MyAppId}", text)
        self.assertNotIn("AppId={#MyAppId}", text)

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


class ReleaseGating(unittest.TestCase):
    """What has to hold before a Release may publish."""

    def test_the_escape_hatch_opens_only_without_a_secret(self):
        """DAP_ALLOW_NO_ADMIN_KEY used to be a constant "1", which silenced
        the spec's only refusal — "this package could never open admin
        mode" — for real releases as well as for forks. The hatch may open
        only when there really is no secret to build with."""
        text = read(BUILD)
        self.assertNotIn('DAP_ALLOW_NO_ADMIN_KEY: "1"', text)
        self.assertIn(
            "DAP_ALLOW_NO_ADMIN_KEY: "
            "${{ secrets.DAP_ADMIN_KEY_SECRET != '' && '0' || '1' }}", text)

    def test_a_tagged_build_demands_the_secret(self):
        """A fork builds artifacts via workflow_dispatch; a TAG is a release,
        and a release cut without the secret is a package no service key can
        open. The gate has to sit before the PyInstaller step."""
        text = read(BUILD)
        gate = text.find("A tagged build must carry the key secret")
        self.assertGreater(gate, -1)
        pyinstaller = text.find("Clean PyInstaller build")
        self.assertGreater(pyinstaller, gate)
        self.assertIn("if: github.ref_type == 'tag'", text[gate:pyinstaller])

    def test_the_release_gates_on_the_repo_checks(self):
        """ci.yml runs in parallel with the build on a tag push, so a check
        living only there can fail while the Release publishes anyway — and
        the credential scan inspects the very DeviceMap the spec compiles
        into the package. The build must `needs:` the same checks."""
        self.assertTrue(REPO_CHECKS.is_file())
        checks = read(REPO_CHECKS)
        # The scan itself lives in the shared file, once.
        self.assertIn("Any credentials in the inventory", checks)
        self.assertIn("workflow_call", checks)
        caller = read(CALLER)
        self.assertIn("uses: ./.github/workflows/repo-checks.yml", caller)
        self.assertIn("needs: [resolve, checks]", caller)
        # And ci.yml calls the same file rather than keeping a second copy.
        ci = read(CI)
        self.assertIn("uses: ./.github/workflows/repo-checks.yml", ci)
        self.assertNotIn("Any credentials in the inventory", ci)

    def test_the_adb_download_is_pinned_and_verified(self):
        """The archive is copied INTO every package (dabp.spec), so
        "-latest-" meant the shipped adb changed on Google's schedule,
        unverified, between two builds of the same tag."""
        text = read(BUILD)
        self.assertNotIn("platform-tools-latest", text)
        self.assertRegex(text, r'PT_VERSION="r\d+\.\d+\.\d+"')
        self.assertIn("platform-tools_${PT_VERSION}-${ARCHIVE}.zip", text)
        # One digest per target operating system, next to its archive name.
        self.assertEqual(len(re.findall(r"SHA256=[0-9a-f]{64}\b", text)), 3)

    def test_the_appimagetool_is_pinned_beside_its_version(self):
        """The version and the digest can only be bumped together, so they
        live together in the script; a copy of the digest in the workflow
        would be the copy that drifts."""
        script = read(settings.ROOT / "packaging" / "appimage.sh")
        self.assertRegex(
            script, r'APPIMAGETOOL_SHA256="\$\{APPIMAGETOOL_SHA256-'
                    r'[0-9a-f]{64}\}"')
        self.assertNotIn("APPIMAGETOOL_SHA256:", read(BUILD))

    def test_the_packaged_selftest_is_verified_on_every_platform(self):
        """The edition and key-material greps ran on Linux alone for a
        while; four packages come out of four separate PyInstaller runs, and
        a wrong stamp in the other three would have shipped unverified. All
        three platform steps write the same output file and one shared,
        unconditional step reads it back."""
        text = read(BUILD)
        # Every platform's packaged self-test step feeds the file the
        # verifier reads — asserted per step, because a global count would
        # be satisfied by the verifier's own mentions of the name.
        for platform in ("Windows", "macOS", "Linux"):
            start = text.find(f"- name: Self-test (packaged) — {platform}")
            self.assertGreater(start, -1, platform)
            step = text[start:text.find("- name:", start + 1)]
            self.assertIn("selftest-output.txt", step, platform)
        verify = text.find("- name: Verify the packaged self-test output")
        self.assertGreater(verify, -1)
        # The verifier itself runs on every platform: no runner condition
        # anywhere in the whole step, not merely above its script.
        body = text[verify:text.find("- name:", verify + 1)]
        self.assertNotIn("if:", body)
        self.assertIn('grep -q "edition: $EDITION "', body)
        self.assertIn("digest only", body)
        self.assertIn(".sealed", body)


class SealingModules(unittest.TestCase):
    """The two files dabp.spec loads bare to seal the other projects.

    The catalogue has carried this contract (and its two tests) for a
    while; secret.py and vault.py carry the same one, and a violation used
    to be SILENT — the spec's broad except turned a broken import into a
    printed line and a green build with no .sealed files in it.
    """

    FILES = (("panel", "adminkey", "secret.py"),
             ("panel", "adminkey", "vault.py"))

    def test_the_sealing_modules_need_nothing_but_the_standard_library(self):
        """Module-LEVEL imports only: secret.py keeps function-local
        `from .. import settings` imports on paths the spec never calls,
        and those do not stop a bare load."""
        for parts in self.FILES:
            path = settings.ROOT.joinpath(*parts)
            with self.subTest(parts[-1]):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.startswith(("import ", "from ")):
                        continue
                    self.assertNotIn("panel", line, line)
                    self.assertFalse(line.startswith("from ."), line)

    def test_the_spec_can_load_them_the_way_the_build_does(self):
        """Loaded standalone and actually used: derive, then a seal/unseal
        round trip, exactly the calls dabp.spec makes at build time."""
        loaded = {}
        for parts in self.FILES:
            path = settings.ROOT.joinpath(*parts)
            name = f"dap_seal_probe_{parts[-1].removesuffix('.py')}"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
            finally:
                sys.modules.pop(spec.name, None)
            loaded[parts[-1]] = module

        key = loaded["secret.py"].derive(b"a-build-secret-for-this-test")
        self.assertEqual(len(key), 32)
        vault = loaded["vault.py"]
        blob = vault.seal(key, b"the other customer's map")
        self.assertEqual(vault.unseal(key, blob),
                         b"the other customer's map")
        self.assertIsNone(vault.unseal(b"\x00" * 32, blob))

    def test_a_secret_holding_build_fails_loudly_when_sealing_breaks(self):
        """The spec may not catch its way past a broken sealing module: a
        build that holds the secret and produces no .sealed files is a
        broken build, not a lean one."""
        text = read(SPEC)
        self.assertNotIn("sealing unavailable", text)
        # The loads run only under `if _S:` — a fork without a secret still
        # builds — and the derivation is no longer conditioned on anything
        # else that could quietly leave SEAL_KEY as None.
        self.assertIn("SEAL_KEY = _secret.derive(_S)", text)


if __name__ == "__main__":
    unittest.main()
