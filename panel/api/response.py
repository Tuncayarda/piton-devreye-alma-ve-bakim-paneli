#!/usr/bin/env python3
"""The transport-independent API result."""
from __future__ import annotations

from dataclasses import dataclass

from .. import i18n


@dataclass(frozen=True)
class ApiResponse:
    """An API result, independent of how it will be delivered."""

    status: int
    body: object


def respond(status: int, body) -> ApiResponse:
    """Build the result, rendering any deferred message it carries.

    This is the single funnel every endpoint goes through, which is why the
    rendering happens here: a `Message` stored minutes ago (a job title, a
    queue row) is turned into text now, in the language selected now.
    """
    return ApiResponse(int(status), i18n.render(body))
