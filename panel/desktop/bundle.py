#!/usr/bin/env python3
"""The desktop bundle's contract, and the checker that enforces it.

The generated single-file HTML must load nothing from disk or the network.
This module holds the rules; `tools/build_desktop_bundle.py` produces the
artefact and reuses them, so the runtime does not depend on the build tool.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from html.parser import HTMLParser
import re

from .. import settings

CAPABILITY_PLACEHOLDER = "__DAP_CAPABILITY__"
CAPABILITY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")

LOGO = settings.STATIC_DIR / "piton-logo.svg"
FAVICON = settings.STATIC_DIR / "piton-favicon.png"

BRIDGE_BOOTSTRAP = (
    '(() => {\n'
    '  const meta = document.querySelector(\'meta[name="dap-capability"]\');\n'
    '  if (!meta) throw new Error("Desktop bridge key not found");\n'
    '  Object.defineProperties(window, {\n'
    '    __PANEL_TRANSPORT__: '
    '{value: "bridge", writable: false, configurable: false},\n'
    '    __PANEL_CAPABILITY__: '
    '{value: meta.content, writable: false, configurable: false},\n'
    '  });\n'
    '  document.addEventListener("click", (event) => {\n'
    '    const target = event.target;\n'
    '    if (target && target.closest && target.closest("a[href]")) '
    'event.preventDefault();\n'
    '  }, true);\n'
    '  document.addEventListener("submit", (event) => event.preventDefault(), true);\n'
    '  for (const name of ["dragenter", "dragover", "drop"]) {\n'
    '    document.addEventListener(name, (event) => event.preventDefault(), true);\n'
    '  }\n'
    '})();'
)


class BundleError(RuntimeError):
    """Generation or the security check did not complete."""


def asset_bytes(path, mime: str) -> bytes:
    """Turn an embedded text asset into platform-independent bytes."""
    if mime == "image/svg+xml":
        # Git's Windows CRLF checkout does not change the image's meaning but
        # would change its raw Base64 and therefore the whole HTML/CSP
        # comparison. The canonical embedded form is always UTF-8 + LF.
        text = path.read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.encode("utf-8")
    return path.read_bytes()


def data_uri(path, mime: str) -> str:
    encoded = base64.b64encode(asset_bytes(path, mime)).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def has_raw_text_terminator(text: str, tag: str) -> bool:
    """Catch a boundary that could really close an HTML raw-text element."""
    pattern = rf"</{re.escape(tag)}(?=[\t\n\f\r />])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def script_digest(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def expected_csp(scripts: list[str]) -> dict[str, frozenset[str]]:
    hashes = [f"'sha256-{script_digest(content)}'" for content in scripts]
    if len(hashes) != 2 or len(set(hashes)) != 2:
        raise BundleError("Two distinct inline script digests are required for the CSP.")
    return {
        "default-src": frozenset({"'none'"}),
        "script-src": frozenset({"'unsafe-eval'", *hashes}),
        "style-src": frozenset({"'unsafe-inline'"}),
        "img-src": frozenset({"data:"}),
        "connect-src": frozenset({"'none'"}),
        "font-src": frozenset({"'none'"}),
        "object-src": frozenset({"'none'"}),
        "base-uri": frozenset({"'none'"}),
        "form-action": frozenset({"'none'"}),
    }


def build_csp(scripts: list[str]) -> str:
    expected = expected_csp(scripts)
    # Hash order follows document order; the remaining tokens are fixed. The
    # validator compares sets, so semantic ordering differences do not loosen
    # the security contract.
    hashes = [f"'sha256-{script_digest(content)}'" for content in scripts]
    # frozenset iteration can depend on the hash seed. Today's single-token
    # directives may grow later without changing artefact order.
    tokens = {name: tuple(sorted(values)) for name, values in expected.items()}
    tokens["script-src"] = (*hashes, "'unsafe-eval'")
    return "; ".join(f"{name} {' '.join(tokens[name])}" for name in expected)


def parse_csp(csp: str) -> dict[str, tuple[str, ...]]:
    """Parse a CSP without silently swallowing repeated directives/tokens."""
    directives: dict[str, tuple[str, ...]] = {}
    for raw in csp.split(";"):
        parts = raw.split()
        if not parts:
            raise BundleError("The CSP contains an empty directive.")
        name = parts[0].lower()
        tokens = tuple(parts[1:])
        if name in directives:
            raise BundleError(f"Duplicated CSP directive: {name}")
        if not tokens:
            raise BundleError(f"CSP direktifi tokensiz: {name}")
        if len(tokens) != len(set(tokens)):
            raise BundleError(f"Duplicated CSP token: {name}")
        directives[name] = tokens
    return directives


def extract_scripts(html: str) -> list[str]:
    return re.findall(r"<script(?:\s[^>]*)?>(.*?)</script\s*>", html,
                      flags=re.IGNORECASE | re.DOTALL)


def _decode_data_uri(uri: str, mime: str) -> bytes:
    prefix = f"data:{mime};base64,"
    if not uri.startswith(prefix):
        raise BundleError(f"Unexpected data URI type; {mime} is required.")
    try:
        return base64.b64decode(uri[len(prefix):], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BundleError(f"Invalid {mime} data URI.") from exc


class _HtmlInspector(HTMLParser):
    """Collects loading attributes and the CSP text out of the HTML."""

    URL_ATTRIBUTES = frozenset({
        "src", "href", "poster", "action", "formaction", "background",
        "manifest", "xlink:href",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.url_attributes: list[tuple[str, str, str, dict[str, str]]] = []
        self.data_attributes: list[tuple[str, str, str, dict[str, str]]] = []
        self.forbidden_attributes: list[tuple[str, str]] = []
        self.duplicate_attributes: list[tuple[str, str]] = []
        self.script_attributes: list[dict[str, str]] = []
        self.csp: list[str] = []
        self.transport: list[str] = []
        self.capability: list[str] = []
        self.meta_refresh_count = 0
        self.style_count = 0

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        names = [name.lower() for name, _value in attrs]
        for name in sorted(set(names)):
            if names.count(name) > 1:
                self.duplicate_attributes.append((tag, name))
        attributes = {name.lower(): value or "" for name, value in attrs}
        for name, value in attributes.items():
            if name in self.URL_ATTRIBUTES:
                self.url_attributes.append((tag, name, value, attributes))
            if value.strip().lower().startswith("data:"):
                self.data_attributes.append((tag, name, value, attributes))
            if name in {"srcset", "ping"} or (tag == "object" and name == "data"):
                self.forbidden_attributes.append((tag, name))
        if tag == "script":
            self.script_attributes.append(attributes)
        elif tag == "style":
            self.style_count += 1
        elif tag == "meta":
            http_equiv = attributes.get("http-equiv", "").strip().lower()
            if http_equiv == "content-security-policy":
                self.csp.append(attributes.get("content", ""))
            elif http_equiv == "refresh":
                self.meta_refresh_count += 1
            meta_name = attributes.get("name", "").strip().lower()
            if meta_name == "dap-transport":
                self.transport.append(attributes.get("content", ""))
            elif meta_name == "dap-capability":
                self.capability.append(attributes.get("content", ""))


def validate_bundle_html(html: str) -> None:
    """Confirm the artefact needs no file or network loads."""
    inspector = _HtmlInspector()
    try:
        inspector.feed(html)
        inspector.close()
    except Exception as exc:
        raise BundleError(f"The generated HTML could not be parsed: {exc}") from exc

    if inspector.transport != ["bridge"]:
        raise BundleError("The desktop transport marker is missing or duplicated.")
    if len(inspector.capability) != 1:
        raise BundleError("Exactly one dap-capability meta tag is required.")
    capability = inspector.capability[0]
    if (capability != CAPABILITY_PLACEHOLDER
            and not CAPABILITY_PATTERN.fullmatch(capability)):
        raise BundleError(
            "dap-capability must be the placeholder or a 43-character "
            "URL-safe token.")
    if len(inspector.csp) != 1:
        raise BundleError(
            "Exactly one Content-Security-Policy meta tag is required.")
    if inspector.meta_refresh_count:
        raise BundleError("Meta refresh is forbidden in the desktop artefact.")
    if inspector.duplicate_attributes:
        found = ", ".join(f"<{tag}> {name}"
                          for tag, name in inspector.duplicate_attributes)
        raise BundleError("Duplicated HTML attribute found: " + found)
    if inspector.forbidden_attributes:
        found = ", ".join(f"<{tag}> {name}"
                          for tag, name in inspector.forbidden_attributes)
        raise BundleError("Network or embedded-resource attributes are forbidden: " + found)
    if inspector.style_count != 1:
        raise BundleError(
            "Every CSS source must sit in a single inline style.")
    if len(inspector.script_attributes) != 2:
        raise BundleError(
            "There must be two inline scripts: bootstrap and application.")
    for attributes in inspector.script_attributes:
        if (attributes.get("src")
                or attributes.get("type", "").lower() == "module"):
            raise BundleError("Desktop scripts must be inline and classic.")

    invalid_urls = []
    for tag, name, value, _attributes in inspector.url_attributes:
        if not value or value.startswith(("#", "data:")):
            continue
        invalid_urls.append(f"<{tag}> {name}={value!r}")
    if invalid_urls:
        raise BundleError(
            "An external or local file reference is left: "
            + ", ".join(invalid_urls))

    data_attributes = inspector.data_attributes
    favicons = [
        (value, attributes)
        for tag, name, value, attributes in data_attributes
        if tag == "link" and name == "href"
        and attributes.get("rel", "").strip().lower() == "icon"
        and attributes.get("type", "").strip().lower() == "image/png"
    ]
    logos = [value for tag, name, value, _attributes in data_attributes
             if tag == "img" and name == "src"]
    # Exactly one favicon and one logo, and nothing else embedded. The count
    # is spelled out rather than bounded: a data: URI is the one way an asset
    # can reach a page whose CSP forbids every network request, so the set of
    # them is the set of assets, and it should not grow by accident.
    if len(data_attributes) != 2 or len(favicons) != 1 or len(logos) != 1:
        raise BundleError(
            "Only one PNG favicon and one SVG logo data URI are allowed.")
    if _decode_data_uri(favicons[0][0], "image/png") != FAVICON.read_bytes():
        raise BundleError("The embedded favicon does not match the source PNG.")
    for logo in logos:
        if (_decode_data_uri(logo, "image/svg+xml")
                != asset_bytes(LOGO, "image/svg+xml")):
            raise BundleError("The embedded logo does not match the source SVG.")

    scripts = extract_scripts(html)
    if len(scripts) != 2:
        raise BundleError("The bootstrap and the JavaScript bundle could not be parsed.")
    bootstrap, application = scripts
    if bootstrap.strip() != BRIDGE_BOOTSTRAP:
        raise BundleError(
            "The bridge bootstrap was not installed before the app bundle.")
    if ("__PANEL_TRANSPORT__" not in application
            or '"bridge"' not in application
            or "__PANEL_CAPABILITY__" not in application):
        raise BundleError(
            "The app bundle does not use the bridge transport/capability "
            "markers.")
    if any(re.search(r"(?m)^\s*(?:import|export)\s", content)
           for content in scripts):
        raise BundleError("An import/export statement is left in the JavaScript bundle.")
    if any(re.search(r"(?i)\bdata:", content) for content in scripts):
        raise BundleError(
            "An unexpected data URI is left inside the inline JavaScript.")
    # The source graph shared with browser mode also contains the HTTP
    # adapter. The bootstrap picks the bridge branch before the bundle runs,
    # and the CSP's connect-src ban makes any regression fail closed.

    if re.search(r"@import\b", html, flags=re.IGNORECASE):
        raise BundleError("An @import is left inside the inline CSS.")
    for match in re.finditer(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", html,
                             flags=re.IGNORECASE | re.DOTALL):
        target = match.group(2).strip()
        if target:
            raise BundleError(f"The inline CSS uses a resource URI: {target!r}")

    expected = expected_csp(scripts)
    found = parse_csp(inspector.csp[0])
    if set(found) != set(expected):
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        raise BundleError(
            f"Invalid CSP directive set; missing={missing}, extra={extra}.")
    for name, expected_tokens in expected.items():
        if frozenset(found[name]) != expected_tokens:
            raise BundleError(
                f"Invalid CSP {name} token set: {sorted(found[name])}")
