"""The service key: the only way into admin mode on a customer package.

There is no role screen and no admin password any more. A package built for
a customer opens as that customer's package and shows that customer's
screens; raising it to admin mode takes a USB stick carrying a file this
build recognises. The `admin` package needs no stick — it is admin from the
moment it opens, and it is the only build that can write one.

    secret    the build's key material, and the one-way step between the
              value only we hold and the value a customer package can check
    keyfile   the file on the stick: read defensively, written atomically
    volumes   where a stick shows up on Windows, macOS and Linux
    handoff   getting the build secret past the password box, for the one
              run that has one
    handback  reading a volume root is not allowed to read, through the
              session of the person who plugged it in
    pack      extra project device lists carried on the same stick
    watcher   the poll that keeps an answer ready, and the one place that
              decides admin mode has ended

Nothing here grants anything on its own. `panel.editions` records the mode
and `panel.api.guard` enforces it.
"""

from . import handback, handoff, media, pack
from .keyfile import (FILENAME, PACK_DIR, KeyFile, read,
                      write)
from .secret import accepted_digests, can_write, mint, usable, verify
from .volumes import removable
from .watcher import WATCH, KeyWatch

__all__ = [
                      "FILENAME",
                      "PACK_DIR",
                      "WATCH",
                      "KeyFile",
                      "KeyWatch",
                      "accepted_digests",
                      "can_write",
                      "handback",
                      "handoff",
                      "media",
                      "mint",
                      "pack",
                      "read",
                      "removable",
                      "usable",
                      "verify",
                      "write",
]
