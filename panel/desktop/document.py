#!/usr/bin/env python3
"""Loading the tracked, fully embedded desktop HTML."""
from __future__ import annotations

import re
from pathlib import Path

from .. import settings
from .bundle import BundleError, validate_bundle_html
from .. import i18n

DESKTOP_HTML = settings.STATIC_DIR / "desktop.html"
BRIDGE_MARKER = '<meta name="dap-transport" content="bridge">'
CAPABILITY_SLOT = "__DAP_CAPABILITY__"


def load_html(capability: str | None = None, path: Path | None = None) -> str:
    """Read the single-file desktop HTML.

    The bundle is not built at runtime; Deno and similar tools need not exist
    on a field machine. When sources change the artefact is refreshed with
    ``python3 tools/build_desktop_bundle.py``.
    """
    target = path or DESKTOP_HTML
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            i18n.t("error.bundleMissing")
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            i18n.t("error.bundleUnreadable", detail=exc)) from exc

    try:
        validate_bundle_html(text)
    except BundleError as exc:
        raise RuntimeError(
            i18n.t("error.bundleInvalid", detail=exc)) from exc

    if capability is not None:
        if not isinstance(capability, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{43}", capability):
            raise RuntimeError(i18n.t("error.bridgeKeyInvalid"))
        if text.count(CAPABILITY_SLOT) != 1:
            raise RuntimeError(i18n.t("error.bridgeKeyFieldMissing"))
        text = text.replace(CAPABILITY_SLOT, capability)
        try:
            validate_bundle_html(text)
        except BundleError as exc:
            raise RuntimeError(
                i18n.t("error.bridgeKeyNotPlaced", detail=exc)
            ) from exc
    return text
