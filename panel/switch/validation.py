#!/usr/bin/env python3
"""Request-field checks for the switch endpoints.

Everything here raises plain `ValueError`, which `panel.api.service` already
turns into a 400 carrying the message. A dedicated exception class would only
have to be unwrapped again at that boundary.

`boolean` is strict on purpose. Python truthiness would read `"false"`,
`"0"` and `[]` as answers to "should this port be on", and the port would go
the wrong way; JSON has a boolean, and the client sends one.
"""
from __future__ import annotations

from collections.abc import Callable

from .. import i18n


def query_ip(query: dict) -> str:
    value = (query.get("ip") or [""])[0]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(i18n.t("switch.errorIpQueryRequired"))
    return value.strip()


def body_ip(body: dict) -> str:
    value = body.get("ip")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(i18n.t("switch.errorIpRequired"))
    return value.strip()


def integer(body: dict, name: str) -> int:
    value = body.get(name)
    # `True` is an int in Python. It is not a port number.
    if isinstance(value, bool) or value is None:
        raise ValueError(i18n.t("switch.errorFieldRequired", field=name))
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(i18n.t("switch.errorFieldNotInteger", field=name,
                                value=value)) from exc


def port_id(body: dict, name: str = "port") -> int:
    value = integer(body, name)
    if value <= 0:
        raise ValueError(i18n.t("switch.errorFieldNotPositive", field=name))
    return value


def text(body: dict, name: str, default: str | None = None) -> str:
    value = body.get(name, default)
    if value is None:
        raise ValueError(i18n.t("switch.errorFieldRequired", field=name))
    if isinstance(value, (dict, list)):
        raise ValueError(i18n.t("switch.errorFieldNotText", field=name))
    return str(value)


def mapping(body: dict, name: str) -> dict:
    value = body.get(name) or {}
    if not isinstance(value, dict):
        raise ValueError(i18n.t("switch.errorFieldNotObject", field=name))
    return value


def boolean(body: dict, name: str) -> bool:
    value = body.get(name)
    if not isinstance(value, bool):
        raise ValueError(i18n.t("switch.errorFieldNotBoolean", field=name))
    return value


def boolean_value(value) -> bool:
    """The same check for a boolean nested inside another object."""
    if not isinstance(value, bool):
        raise ValueError(i18n.t("switch.errorValueNotBoolean"))
    return value


def port_mapping(body: dict, name: str, convert: Callable) -> dict:
    """A {port number: value} object, with the keys proved to be ports."""
    result = {}
    for key, value in mapping(body, name).items():
        # `value=` and not `key=`: i18n.t's own first parameter is called
        # `key`, and passing a placeholder by that name is a TypeError, not a
        # translation — which turns a 400 into a 500.
        try:
            pid = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(i18n.t("switch.errorKeyNotPort", field=name,
                                    value=key)) from exc
        if pid <= 0:
            raise ValueError(i18n.t("switch.errorKeyNotPort", field=name,
                                    value=key))
        result[pid] = convert(value)
    return result
