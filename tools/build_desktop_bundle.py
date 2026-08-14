#!/usr/bin/env python3
"""Builds the desktop UI artefact that needs no HTTP.

``static/index.html`` and the modular JavaScript sources stay the source of
truth for browser mode. This tool derives a single HTML file for pywebview
from those same sources:

* Bundles the JavaScript module graph as an IIFE with Deno 2.9.4.
* Embeds the three CSS files, the logo and the favicon into the HTML.
* Marks the bridge transport and adds a CSP that closes off network access.

The output is deterministic; it contains no date, temporary path or
machine-specific data. The artefact must not be edited by hand.

The security contract itself lives in `panel.desktop.bundle` so the runtime
does not depend on this build tool.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel.desktop.bundle import (BRIDGE_BOOTSTRAP,  # noqa: E402
                                  CAPABILITY_PLACEHOLDER, BundleError,
                                  build_csp, data_uri, has_raw_text_terminator,
                                  validate_bundle_html)

STATIC = ROOT / "static"
SOURCE_HTML = STATIC / "index.html"
ENTRY_JS = STATIC / "js" / "app.js"
OUTPUT = STATIC / "desktop.html"
CSS_FILES = (
    STATIC / "css" / "base.css",
    STATIC / "css" / "components.css",
    STATIC / "css" / "views.css",
    STATIC / "css" / "ip.css",
)
LOGO = STATIC / "piton-logo.svg"
FAVICON = STATIC / "piton-favicon.png"
DENO_VERSION = "2.9.4"


def _run(argv: list[str], *, failure: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DENO_NO_UPDATE_CHECK"] = "1"
    environment["NO_COLOR"] = "1"
    try:
        result = subprocess.run(
            argv, cwd=ROOT, env=environment, capture_output=True, text=True,
            encoding="utf-8", timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleError(f"{failure}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise BundleError(f"{failure} (exit {result.returncode}):\n{detail}")
    return result


def find_deno() -> str:
    """Verify the exact Deno version pinned for a deterministic bundle."""
    deno = shutil.which("deno")
    if not deno:
        raise BundleError(
            f"Deno {DENO_VERSION} not found. It is required to build the "
            f"desktop bundle. Install Deno {DENO_VERSION} and check that "
            "`deno --version` works on PATH: "
            "https://docs.deno.com/runtime/getting_started/installation/")
    result = _run([deno, "--version"],
                  failure="Could not read the Deno version")
    match = re.search(r"(?m)^deno\s+(\d+\.\d+\.\d+)(?=\s|$)", result.stdout)
    if not match:
        raise BundleError(
            f"Could not parse the Deno version: {result.stdout.strip()!r}")
    version = match.group(1)
    if version != DENO_VERSION:
        raise BundleError(
            f"A deterministic desktop bundle needs Deno {DENO_VERSION}; the "
            f"version on PATH is Deno {version}. Run "
            f"`deno upgrade --version {DENO_VERSION}`.")
    return deno


def bundle_javascript(deno: str) -> str:
    """Type-check the entry graph and return a dependency-free IIFE."""
    shared = ["--no-config", "--no-lock", "--no-remote"]
    # WindowsPath.__str__ produces backslashes. Keep the module path comments
    # inside the bundle identical across operating systems.
    entry = ENTRY_JS.relative_to(ROOT).as_posix()
    _run([deno, "check", *shared, entry],
         failure="The JavaScript type/syntax check failed")
    result = _run(
        [deno, "bundle", "--platform", "browser", "--format", "iife",
         *shared, entry],
        failure="The JavaScript bundle could not be produced")
    bundle = result.stdout.replace("\r\n", "\n").rstrip() + "\n"
    if not bundle.strip():
        raise BundleError("Deno produced an empty JavaScript bundle.")
    return bundle


def _replace_once(text: str, old: str, new: str, *, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise BundleError(
            f"The {SOURCE_HTML.relative_to(ROOT)} template is not in the "
            f"expected shape: "
            f"{old!r} was found {found} time(s) instead of {count}.")
    return text.replace(old, new)


def _merge_css() -> str:
    parts = []
    for path in CSS_FILES:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
        if has_raw_text_terminator(text, "style"):
            raise BundleError(
                f"{path.relative_to(ROOT)} cannot be embedded safely.")
        parts.append(f"/* {path.relative_to(ROOT).as_posix()} */\n{text}")
    return "\n\n".join(parts) + "\n"


def build_html(javascript: str) -> str:
    """Turn the source HTML into desktop HTML with everything embedded."""
    html = SOURCE_HTML.read_text(encoding="utf-8").replace("\r\n", "\n")
    css = _merge_css()
    if has_raw_text_terminator(javascript, "script"):
        raise BundleError(
            "The JavaScript bundle cannot be embedded safely into the HTML.")

    bootstrap_content = "\n" + BRIDGE_BOOTSTRAP + "\n"
    script_content = "\n" + javascript.rstrip() + "\n"
    scripts = [bootstrap_content, script_content]
    # Pywebview uses a controlled eval when passing an exposed Python call's
    # result into the page context. Inline code is still limited to the two
    # hashes; connect-src keeps all network access closed.
    csp = build_csp(scripts)
    meta = (
        '<meta name="dap-transport" content="bridge">\n'
        f'<meta name="dap-capability" content="{CAPABILITY_PLACEHOLDER}">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        "<script>" + bootstrap_content + "</script>"
    )
    html = _replace_once(html, '<meta charset="utf-8">',
                         '<meta charset="utf-8">\n' + meta)
    html = _replace_once(
        html,
        '<link rel="icon" type="image/png" href="/piton-favicon.png">',
        '<link rel="icon" type="image/png" href="'
        + data_uri(FAVICON, "image/png") + '">')
    css_links = "\n".join(
        f'<link rel="stylesheet" href="/css/{path.name}">'
        for path in CSS_FILES)
    html = _replace_once(html, css_links, "<style>\n" + css + "</style>")
    html = _replace_once(html, 'src="/piton-logo.svg"',
                         'src="' + data_uri(LOGO, "image/svg+xml") + '"',
                         count=2)
    html = _replace_once(
        html, '<script type="module" src="/js/app.js"></script>',
        "<script>" + script_content + "</script>")
    html = _replace_once(
        html, "<!DOCTYPE html>",
        "<!DOCTYPE html>\n<!-- generated by "
        "tools/build_desktop_bundle.py; do not edit by hand. -->")
    return html.rstrip() + "\n"


def build_artefact() -> str:
    deno = find_deno()
    html = build_html(bundle_javascript(deno))
    validate_bundle_html(html)
    return html


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_name = temporary.name
        # NamedTemporaryFile creates 0600 on Unix. A tracked build artefact
        # should be readable by everyone, like the source files.
        Path(temporary_name).chmod(0o644)
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="Builds the HTTP-free pywebview UI as a single HTML "
                    "file.")
    parser.add_argument(
        "--check", action="store_true",
        help="check that the static/desktop.html artefact is up to date "
             "without writing any file")
    options = parser.parse_args(argv)
    try:
        expected = build_artefact()
        if options.check:
            if not OUTPUT.is_file():
                raise BundleError(
                    f"{OUTPUT.relative_to(ROOT)} is missing; run "
                    "`python3 tools/build_desktop_bundle.py` first.")
            if OUTPUT.read_bytes() != expected.encode("utf-8"):
                raise BundleError(
                    f"{OUTPUT.relative_to(ROOT)} is out of date; rebuild it "
                    "with `python3 tools/build_desktop_bundle.py`.")
            print(f"[OK] {OUTPUT.relative_to(ROOT)} is up to date and "
                  "verified.")
            return 0

        _write_atomically(OUTPUT, expected)
        print(f"[OK] {OUTPUT.relative_to(ROOT)} built "
              f"({len(expected.encode('utf-8'))} bytes).")
        return 0
    except BundleError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
