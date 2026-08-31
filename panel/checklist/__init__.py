"""The field checklist: the Excel export and its on-screen preview."""

from . import columns as _columns
from .preview import build_preview, clear_cache, template_layout
from .workbook import export

__all__ = ["COLUMN_FOR_FIELD", "MANUAL_COLUMNS", "build_preview",
           "clear_cache", "export", "template_layout"]


def __getattr__(name: str):
    # The column tables now come from the runtime-loaded field script;
    # importing them eagerly here would pull openpyxl in at API startup
    # (see .columns). Resolved on first use instead.
    if name in ("COLUMN_FOR_FIELD", "MANUAL_COLUMNS"):
        return getattr(_columns, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
