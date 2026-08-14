#!/usr/bin/env python3
"""The message catalogue, shared by the panel and its UI.

Every string a user reads lives in `panel/messages/<language>.json`, keyed by
a stable English identifier. The code is written in English and never carries
a sentence; it carries a key.

ONE CATALOGUE, TWO READERS. Python imports it from here; the browser gets the
same file over `/api/language`. Two catalogues would drift on the first hurried
fix, and half a screen would silently fall back to the other language.

Two ways to use a message:

    t("error.deviceUnreachable")           renders NOW, in the current language
    lazy("job.ipAssign", switch=name)      renders WHEN READ

`lazy` matters for anything stored and shown later — a job title, a queue row's
note, a step. Those are written once and read for minutes afterwards; rendering
them at write time froze them in whatever language was selected then, and a
language switch left the queue half translated. A `Message` renders on every
read, so switching retranslates the queue that is already running.
"""
from __future__ import annotations

import json
import locale
import os
import threading
from pathlib import Path

from . import settings

LANGUAGES = ("en", "tr")
# The language to show when we cannot tell what the user speaks. The panel is
# commissioned on Turkish trains by Turkish operators, so an unknown machine
# is far more likely to be theirs than anyone else's.
DEFAULT_LANGUAGE = "tr"
# The catalogue a MISSING key is read from — a different question, and it has
# a different answer. The code is written in English and every key is coined
# in English, so en.json is the one guaranteed to have an entry. Reading the
# gap from the default instead would drop a Turkish sentence into an English
# screen. tests/test_i18n.py keeps the two catalogues in step, so this should
# never fire; it is the net under that test, not a substitute for it.
FALLBACK_LANGUAGE = "en"

MESSAGES_DIR = settings.data_file("messages", "panel", "messages")

_LOCK = threading.RLock()
_CATALOGUES: dict[str, dict[str, str]] = {}
_LANGUAGE: str | None = None
# Called after every language change — see on_change().
_LISTENERS: list = []


class _Blanks(dict):
    """Formatting must never raise on a placeholder nobody passed.

    A missing value is a translation bug, not a reason to fail the request
    that was carrying it: the placeholder is left visible so it is noticed.
    """

    def __missing__(self, key):
        return "{" + key + "}"


class Message:
    """A key plus its parameters, rendered on every read.

    `str()` renders in the language selected right now, so a Message can be
    handed to anything that expects text.
    """

    __slots__ = ("key", "params")

    def __init__(self, key: str, **params):
        self.key = key
        self.params = params

    def render(self, language: str | None = None) -> str:
        return t(self.key, _language=language, **self.params)

    def __str__(self) -> str:
        return self.render()

    def __repr__(self) -> str:
        return f"Message({self.key!r}, {self.params!r})"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Message) and other.key == self.key
                and other.params == self.params)

    def __hash__(self) -> int:
        return hash((self.key, tuple(sorted(self.params.items()))))


def catalogue(language: str | None = None) -> dict[str, str]:
    """The whole message map for a language, loaded once and cached."""
    code = normalise(language or current())
    with _LOCK:
        loaded = _CATALOGUES.get(code)
        if loaded is not None:
            return loaded
    path = Path(MESSAGES_DIR) / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    with _LOCK:
        _CATALOGUES[code] = data
    return data


def normalise(language) -> str:
    """Map anything the outside world says to a language we actually have."""
    code = str(language or "").strip().lower().replace("_", "-")
    if not code:
        return DEFAULT_LANGUAGE
    if code in LANGUAGES:
        return code
    head = code.split("-")[0]
    return head if head in LANGUAGES else DEFAULT_LANGUAGE


def _recognised(value) -> str | None:
    """The language in `value`, or None if it names one we do not have.

    Separate from normalise(), which answers "what do we SHOW for this" and
    therefore turns anything unknown into the default. Here the difference
    matters: `LANG=C` must not count as a stated preference, while a genuine
    `LANG=tr_TR` must — and once the default is Turkish those two normalise
    to the same string.
    """
    code = str(value or "").strip().lower().replace("_", "-")
    if code in LANGUAGES:
        return code
    head = code.split("-")[0]
    return head if head in LANGUAGES else None


def system_language() -> str:
    """The operating system's language, when we speak it.

    Read from the environment first: on macOS and Linux that is where a user's
    choice actually shows up, and `locale.getlocale()` returns (None, None) in
    a fresh process until setlocale has run.
    """
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            code = _recognised(value.split(":")[0].split(".")[0])
            if code:
                return code
    try:
        code, _encoding = locale.getlocale()
    except (ValueError, TypeError):
        code = None
    if not code:
        try:
            code = locale.getdefaultlocale()[0]     # noqa: DEP-locale
        except Exception:
            code = None
    return normalise(code)


def _stored_language() -> str | None:
    try:
        data = json.loads(
            settings.ui_settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("language") in LANGUAGES:
        return data["language"]
    return None


def current() -> str:
    """The selected language: what the user chose, else the system's.

    The choice is kept on disk rather than in the browser, because browser
    storage is closed to this application by design (see
    tests/test_frontend.py) and because the panel translates its own messages
    server-side.
    """
    global _LANGUAGE
    with _LOCK:
        if _LANGUAGE is not None:
            return _LANGUAGE
    chosen = _stored_language() or system_language()
    with _LOCK:
        if _LANGUAGE is None:
            _LANGUAGE = chosen
        return _LANGUAGE


def on_change(callback) -> None:
    """Run `callback(language)` whenever the language changes.

    Almost everything the user reads is redrawn from the catalogue the switch
    hands back, so almost nothing needs this. The window title does: it is
    painted by the operating system, outside the WebView, and no redraw of
    the UI can reach it.
    """
    with _LOCK:
        _LISTENERS.append(callback)


def use(language: str, *, persist: bool = True) -> str:
    """Select a language. Returns the one actually in effect."""
    global _LANGUAGE
    code = normalise(language)
    with _LOCK:
        _LANGUAGE = code
        listeners = list(_LISTENERS)
    if persist:
        path = settings.ui_settings_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"language": code}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            temporary.replace(path)     # never leave a half-written file
        except OSError:
            pass                        # a read-only home must not break the UI
    for callback in listeners:
        try:
            callback(code)
        except Exception:
            # A follower is decoration. The language HAS changed by now, and
            # failing the request over a title bar would undo a switch the
            # user already sees in the rest of the screen.
            pass
    return code


def reset() -> None:
    """Forget the selection, the cached catalogues and the followers.

    Used by tests: a listener registered by one test must not still be firing
    during the next.
    """
    global _LANGUAGE
    with _LOCK:
        _LANGUAGE = None
        _CATALOGUES.clear()
        _LISTENERS.clear()


def t(key: str, _language: str | None = None, **params) -> str:
    """Render one message.

    An unknown key returns the key itself: a visible, greppable marker beats
    an empty label, and `tests/test_i18n.py` fails the build if one exists.
    """
    text = catalogue(_language).get(key)
    if text is None and normalise(_language or current()) != FALLBACK_LANGUAGE:
        text = catalogue(FALLBACK_LANGUAGE).get(key)
    if text is None:
        return key
    if not params:
        return text
    try:
        return text.format_map(_Blanks(params))
    except (IndexError, ValueError):
        return text


def lazy(key: str, **params) -> Message:
    """A message rendered when it is read, not when it is written."""
    return Message(key, **params)


def render(value):
    """Render every Message inside a JSON-able structure, in place of it.

    Applied once at the API boundary (see panel.api.response.respond) so no
    call site has to remember: a Message may sit anywhere in a body — a queue
    row's note, a step, a probe result's detail — and it must reach the UI as
    text in the language selected at THAT moment, not the one selected when it
    was written.
    """
    if isinstance(value, Message):
        return value.render()
    if isinstance(value, dict):
        return {key: render(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [render(item) for item in value]
    return value


def payload(language: str | None = None) -> dict:
    """What the UI needs to translate itself: the whole catalogue."""
    code = normalise(language or current())
    return {
        "language": code,
        "languages": list(LANGUAGES),
        "messages": catalogue(code),
    }
