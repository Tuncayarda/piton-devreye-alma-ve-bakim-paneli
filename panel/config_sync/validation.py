#!/usr/bin/env python3
"""Validating target values before they are stored.

Validation happens here rather than at write time: a bad value sitting in
memory until the write would surface in the job queue instead of on the
screen where it was typed.
"""
from __future__ import annotations

import re

from .. import settings
from .fields import FIELDS, WRITABLE, writable_for_subtype
from .. import i18n


def is_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    return all(part.isdigit() and len(part) <= 3 and 0 <= int(part) <= 255
               for part in parts)


def _short(number) -> str:
    if number is None:
        return "?"
    return (str(int(number)) if float(number).is_integer() else str(number))


def validate(name: str, value, subtype: str | None = None) -> str:
    """Check a value against its field type and return the cleaned form."""
    if name not in WRITABLE:
        raise ValueError(i18n.t("error.fieldNotWritable", name=name))
    if subtype and name not in writable_for_subtype(subtype):
        raise ValueError(
            i18n.t("error.fieldNotOnType",
                   field=i18n.t(FIELDS[name].label), subtype=subtype))

    field = FIELDS[name]
    text = str(value).strip()
    if not text:
        return ""

    if field.kind == "choice":
        if text not in [option for option, _label in field.options]:
            raise ValueError(i18n.t("error.invalidChoice",
                                    field=i18n.t(field.label), value=text))
    elif field.kind in ("integer", "decimal"):
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            raise ValueError(i18n.t("error.mustBeNumber",
                                    field=i18n.t(field.label)))
        if field.kind == "integer" and not number.is_integer():
            raise ValueError(i18n.t("error.mustBeWhole",
                                    field=i18n.t(field.label)))
        if ((field.minimum is not None and number < field.minimum)
                or (field.maximum is not None and number > field.maximum)):
            raise ValueError(
                i18n.t("error.outOfRange", field=i18n.t(field.label),
                       min=_short(field.minimum),
                       max=_short(field.maximum)))
        # No trailing zeros on decimals: a threshold written as 5 in
        # DeviceMap shows as "5", not "5.0", so it reads next to the device's
        # value.
        text = (str(int(number)) if field.kind == "integer"
                else f"{number:g}")
    elif field.kind == "ip":
        if not is_ipv4(text):
            raise ValueError(i18n.t("error.notIpv4",
                                    field=i18n.t(field.label)))
    elif field.kind == "digits":
        if not re.fullmatch(r"[0-9*#]{1,32}", text):
            raise ValueError(i18n.t("error.digitsOnly",
                                    field=i18n.t(field.label)))
    elif len(text) > 64:
        raise ValueError(i18n.t("error.tooLong",
                                field=i18n.t(field.label)))
    return text[:128]


def scope_key(set_no, name: str) -> tuple[int, str]:
    """Turn a set number and a device/group id into a safe store key."""
    try:
        number = int(set_no)
    except (TypeError, ValueError):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    if not (settings.SET_MIN <= number <= settings.SET_MAX):
        raise ValueError(i18n.t("error.invalidSetNumber"))
    identifier = str(name or "").strip()
    if not identifier or len(identifier) > 128:
        raise ValueError(i18n.t("error.invalidTargetId"))
    return number, identifier
