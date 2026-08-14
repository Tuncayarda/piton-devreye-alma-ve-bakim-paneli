#!/usr/bin/env python3
"""Small shared helpers for route handlers."""
from __future__ import annotations


def single(query: dict, name: str, default=None):
    """One value out of a parsed query string."""
    value = query.get(name, default)
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def name_list(raw) -> list[str]:
    """Accept a group name as a string or a list, return a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part for part in raw.split(",") if part.strip()]
    return [str(part) for part in raw if str(part).strip()]


def first_switch_id(inventory, requested=None) -> str:
    if requested:
        return str(requested)
    switches = inventory.switches()
    return switches[0].id if switches else ""
