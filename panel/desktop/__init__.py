"""The socketless desktop surface: the single-file HTML and the bridge."""

from . import editmenu
from .bridge import PanelBridge
from .bundle import BundleError, validate_bundle_html
from .document import BRIDGE_MARKER, CAPABILITY_SLOT, load_html

__all__ = [
           "BRIDGE_MARKER",
           "CAPABILITY_SLOT",
           "BundleError",
           "PanelBridge",
           "editmenu",
           "load_html",
           "validate_bundle_html",
]
