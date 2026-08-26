#!/usr/bin/env python3
"""Read the identity carried by a single Android APK.

An APK is a ZIP whose ``AndroidManifest.xml`` is normally Android's compact
binary XML format.  Depending on ``aapt``/Android Studio at runtime would make
field installs work on a developer laptop and fail in the packaged panel, so
the tiny reader below handles just what installation verification needs: the
root manifest's package name and version name.

This is intentionally *not* an APK installer or a general AXML parser.  The
Android package manager remains the authority on signatures and installability.
"""
from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


_NO_INDEX = 0xFFFFFFFF
_STRING_POOL = 0x0001
_XML_START_ELEMENT = 0x0102
_UTF8_FLAG = 0x00000100
_TYPE_STRING = 0x03
_MANIFEST_LIMIT = 4 * 1024 * 1024
_PACKAGE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


class ApkMetadataError(ValueError):
    """The selected file is not a readable, single-file APK."""


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ApkMetadataError("truncated Android manifest")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ApkMetadataError("truncated Android manifest")
    return struct.unpack_from("<I", data, offset)[0]


def _length8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset] if offset < len(data) else None
    if first is None:
        raise ApkMetadataError("truncated UTF-8 string")
    if first & 0x80:
        if offset + 1 >= len(data):
            raise ApkMetadataError("truncated UTF-8 string")
        return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
    return first, offset + 1


def _length16(data: bytes, offset: int) -> tuple[int, int]:
    first = _u16(data, offset)
    if first & 0x8000:
        return (((first & 0x7FFF) << 16) | _u16(data, offset + 2),
                offset + 4)
    return first, offset + 2


def _string_pool(data: bytes, chunk: int, size: int,
                 header_size: int) -> list[str]:
    if header_size < 28 or chunk + size > len(data):
        raise ApkMetadataError("invalid Android string pool")
    count = _u32(data, chunk + 8)
    flags = _u32(data, chunk + 16)
    strings_start = _u32(data, chunk + 20)
    if count > 100_000 or header_size + count * 4 > size:
        raise ApkMetadataError("invalid Android string count")

    values: list[str] = []
    utf8 = bool(flags & _UTF8_FLAG)
    for index in range(count):
        relative = _u32(data, chunk + header_size + index * 4)
        cursor = chunk + strings_start + relative
        if cursor < chunk or cursor >= chunk + size:
            raise ApkMetadataError("invalid Android string offset")
        if utf8:
            _characters, cursor = _length8(data, cursor)
            length, cursor = _length8(data, cursor)
            end = cursor + length
            if end > chunk + size:
                raise ApkMetadataError("truncated Android string")
            try:
                values.append(data[cursor:end].decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ApkMetadataError("invalid Android UTF-8 string") from exc
        else:
            length, cursor = _length16(data, cursor)
            end = cursor + length * 2
            if end > chunk + size:
                raise ApkMetadataError("truncated Android string")
            try:
                values.append(data[cursor:end].decode("utf-16le"))
            except UnicodeDecodeError as exc:
                raise ApkMetadataError("invalid Android UTF-16 string") from exc
    return values


def _pool_value(pool: list[str], index: int) -> str:
    if index == _NO_INDEX:
        return ""
    if index < 0 or index >= len(pool):
        raise ApkMetadataError("invalid Android string reference")
    return pool[index]


def _binary_manifest(data: bytes) -> dict[str, str]:
    if len(data) < 8 or _u16(data, 0) != 0x0003:
        raise ApkMetadataError("not an Android binary manifest")
    declared = _u32(data, 4)
    if declared > len(data) or declared < 8:
        raise ApkMetadataError("invalid Android manifest size")

    pool: list[str] | None = None
    cursor = _u16(data, 2)
    while cursor + 8 <= declared:
        kind = _u16(data, cursor)
        header_size = _u16(data, cursor + 2)
        size = _u32(data, cursor + 4)
        if header_size < 8 or size < header_size or cursor + size > declared:
            raise ApkMetadataError("invalid Android manifest chunk")
        if kind == _STRING_POOL:
            pool = _string_pool(data, cursor, size, header_size)
        elif kind == _XML_START_ELEMENT and pool is not None:
            # ResXMLTree_node is 16 bytes; attributeStart is relative to the
            # ResXMLTree_attrExt that follows it (offset 16 in the chunk).
            if size < 36:
                raise ApkMetadataError("invalid Android element")
            element = _pool_value(pool, _u32(data, cursor + 20))
            if element != "manifest":
                cursor += size
                continue
            attribute_start = _u16(data, cursor + 24)
            attribute_size = _u16(data, cursor + 26)
            attribute_count = _u16(data, cursor + 28)
            if attribute_size < 20 or attribute_count > 10_000:
                raise ApkMetadataError("invalid Android attributes")
            base = cursor + 16 + attribute_start
            package = ""
            version = ""
            for number in range(attribute_count):
                item = base + number * attribute_size
                if item + 20 > cursor + size:
                    raise ApkMetadataError("truncated Android attribute")
                name = _pool_value(pool, _u32(data, item + 4))
                raw_index = _u32(data, item + 8)
                value = _pool_value(pool, raw_index)
                if not value and data[item + 15] == _TYPE_STRING:
                    value = _pool_value(pool, _u32(data, item + 16))
                if name == "package":
                    package = value
                elif name == "versionName":
                    version = value
            return {"package": package, "version": version}
        cursor += size
    raise ApkMetadataError("manifest root was not found")


def _plain_manifest(data: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ApkMetadataError("invalid Android manifest") from exc
    if root.tag.rsplit("}", 1)[-1] != "manifest":
        raise ApkMetadataError("manifest root was not found")
    version = (root.attrib.get(
        "{http://schemas.android.com/apk/res/android}versionName", "")
        or root.attrib.get("versionName", ""))
    return {"package": root.attrib.get("package", ""), "version": version}


def read_apk_metadata(path: Path | str) -> dict[str, str]:
    """Return ``{"package", "version"}`` from a single APK.

    Only the small manifest entry is read.  Split-package containers
    (``.apks``, ``.apkm``, ``.xapk``) and an APK plus a separate OBB are not a
    single installable APK and deliberately remain outside this operation.
    """
    target = Path(path)
    try:
        with zipfile.ZipFile(target) as archive:
            info = archive.getinfo("AndroidManifest.xml")
            if info.file_size <= 0 or info.file_size > _MANIFEST_LIMIT:
                raise ApkMetadataError("invalid Android manifest size")
            data = archive.read(info)
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ApkMetadataError("not a readable APK") from exc

    metadata = (_plain_manifest(data) if data.lstrip().startswith(b"<")
                else _binary_manifest(data))
    package = metadata["package"].strip()
    if len(package) > 255 or _PACKAGE.fullmatch(package) is None:
        raise ApkMetadataError("invalid Android package name")
    return {"package": package, "version": metadata["version"].strip()[:128]}
