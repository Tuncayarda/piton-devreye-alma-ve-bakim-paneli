#!/usr/bin/env python3
"""Build checks for the HTTP-free single-file desktop artefact."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from panel.desktop import bundle
from tools import build_desktop_bundle


ROOT = Path(__file__).resolve().parent.parent


class DesktopBundle(unittest.TestCase):

    def _html(self):
        return build_desktop_bundle.OUTPUT.read_text(encoding="utf-8")

    def _rejected(self, html, pattern=None):
        context = (self.assertRaisesRegex(bundle.BundleError, pattern)
                   if pattern else self.assertRaises(bundle.BundleError))
        with context:
            bundle.validate_bundle_html(html)

    def test_artefact_is_single_file_and_restricted(self):
        self.assertTrue(build_desktop_bundle.OUTPUT.is_file(),
                        "static/desktop.html yok")
        html = self._html()
        bundle.validate_bundle_html(html)
        self.assertIn('<meta name="dap-transport" content="bridge">', html)
        self.assertIn(
            '<meta name="dap-capability" content="__DAP_CAPABILITY__">', html)
        self.assertNotIn('<script type="module"', html)
        bootstrap = bundle.BRIDGE_BOOTSTRAP
        self.assertEqual(html.count(bootstrap), 1)
        for event in ('"dragenter"', '"dragover"', '"drop"'):
            self.assertIn(event, bootstrap)
        bootstrap_end = html.index(bootstrap) + len(bootstrap)
        self.assertGreater(html.index("(() => {", bootstrap_end), bootstrap_end)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("'unsafe-eval'", html)
        for local in (
            'href="/css/',
            'src="/js/',
            'src="/piton-',
            'href="/piton-',
        ):
            self.assertNotIn(local, html)

    def test_a_clear_error_when_deno_is_missing(self):
        with mock.patch.object(build_desktop_bundle.shutil, "which",
                               return_value=None):
            with self.assertRaisesRegex(bundle.BundleError,
                                        r"Deno 2\.9\.4 not found"):
                build_desktop_bundle.find_deno()

    def test_the_deno_version_must_match_exactly(self):
        def result(version):
            return subprocess.CompletedProcess(
                ["/fake/deno", "--version"], 0,
                f"deno {version} (stable, release)\n", "")

        with mock.patch.object(build_desktop_bundle.shutil, "which",
                               return_value="/fake/deno"):
            with mock.patch.object(build_desktop_bundle, "_run",
                                   return_value=result("2.9.4")):
                self.assertEqual(build_desktop_bundle.find_deno(), "/fake/deno")
            for version in ("2.9.3", "2.9.5", "3.0.0"):
                with self.subTest(version=version), \
                        mock.patch.object(build_desktop_bundle, "_run",
                                          return_value=result(version)):
                    with self.assertRaisesRegex(
                            bundle.BundleError, r"needs Deno 2\.9\.4"):
                        build_desktop_bundle.find_deno()

    def test_svg_crlf_and_lf_checkouts_produce_the_same_artefact(self):
        content = '<svg xmlns="http://www.w3.org/2000/svg">\n<path/>\n</svg>\n'
        with tempfile.TemporaryDirectory() as directory:
            lf = Path(directory) / "lf.svg"
            crlf = Path(directory) / "crlf.svg"
            lf.write_bytes(content.encode("utf-8"))
            crlf.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(
                bundle.data_uri(lf, "image/svg+xml"),
                bundle.data_uri(crlf, "image/svg+xml"),
            )

    def test_check_rejects_a_crlf_artefact_at_the_byte_level(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "desktop.html"
            output.write_bytes(b"line\r\n")
            stderr = StringIO()
            with (mock.patch.object(build_desktop_bundle, "OUTPUT", output),
                  mock.patch.object(build_desktop_bundle, "ROOT",
                                    Path(directory)),
                  mock.patch.object(build_desktop_bundle, "build_artefact",
                                    return_value="line\n"),
                  redirect_stderr(stderr)):
                self.assertEqual(build_desktop_bundle.main(["--check"]), 1)
            self.assertIn("is out of date", stderr.getvalue())

    def test_the_csp_directive_and_token_set_is_complete(self):
        html = self._html()
        corruptions = (
            ("connect-src 'none'", "connect-src 'none' https:"),
            ("connect-src 'none'", "connect-src 'none' 'none'"),
            ("connect-src 'none'", "connect-src 'none'; connect-src 'none'"),
            ("font-src 'none'", "worker-src 'none'; font-src 'none'"),
            (" 'unsafe-eval'", ""),
        )
        for old, new in corruptions:
            with self.subTest(new=new):
                self._rejected(html.replace(old, new, 1), r"CSP")

    def test_the_capability_placeholder_and_token_contract(self):
        html = self._html()
        with_token = html.replace(bundle.CAPABILITY_PLACEHOLDER,
                                  "A" * 42 + "_", 1)
        bundle.validate_bundle_html(with_token)

        for invalid in ("A" * 42, "A" * 42 + "="):
            with self.subTest(value=invalid[-3:]):
                self._rejected(
                    html.replace(bundle.CAPABILITY_PLACEHOLDER, invalid, 1),
                    r"dap-capability",
                )
        self._rejected(
            html.replace(
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">\n',
                "", 1),
            r"dap-capability",
        )
        self._rejected(
            html.replace(
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">',
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">\n'
                '<meta name="dap-capability" content="__DAP_CAPABILITY__">',
                1),
            r"dap-capability",
        )

    def test_the_loading_surface_stays_narrow(self):
        html = self._html()
        additions = (
            '<meta http-equiv="refresh" content="0; url=https://example.com">',
            '<img srcset="https://example.com/a.png 1x">',
            '<a ping="https://example.com/ping">x</a>',
            '<object data="https://example.com/data"></object>',
            '<img src="data:text/plain;base64,QQ==">',
        )
        for addition in additions:
            with self.subTest(addition=addition.split()[0]):
                self._rejected(html.replace("<body>", "<body>\n" + addition, 1))

        broken_favicon = re.sub(
            r'(<link rel="icon" type="image/png" href=")data:[^"]+',
            r'\1data:image/png;base64,QQ==',
            html,
            count=1,
        )
        self._rejected(broken_favicon, r"favicon")

    def test_raw_text_terminators_are_rejected(self):
        for terminator in ("</script x>", "</script/>"):
            with self.subTest(terminator=terminator), self.assertRaisesRegex(
                    bundle.BundleError, r"JavaScript bundle cannot be embedded"):
                build_desktop_bundle.build_html(
                    f'console.log("{terminator}");')
        self.assertTrue(
            bundle.has_raw_text_terminator("a</style x>b", "style"))
        self.assertTrue(
            bundle.has_raw_text_terminator("a</style/>b", "style"))
        self.assertFalse(
            bundle.has_raw_text_terminator("a</scriptx>b", "script"))

    def test_the_artefact_is_current_and_the_build_deterministic(self):
        if not shutil.which("deno"):
            self.skipTest("Deno is not installed; the build comparison was skipped")
        first = build_desktop_bundle.build_artefact()
        second = build_desktop_bundle.build_artefact()
        self.assertEqual(first, second)
        self.assertEqual(
            build_desktop_bundle.OUTPUT.read_bytes(),
            first.encode("utf-8"),
            "static/desktop.html is out of date",
        )

        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_desktop_bundle.py"),
             "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            # The subprocess writes UTF-8 (reconfigure inside main). Without
            # an explicit encoding Python assumes the ANSI code page on
            # Windows (cp1252/cp1254) and mangles the Turkish characters.
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("is up to date and verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
