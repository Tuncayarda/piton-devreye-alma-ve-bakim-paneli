#!/usr/bin/env python3
"""The other customers' projects: shipped sealed, opened only in admin mode.

Two claims are under test here, and the second one is the whole point:

  1. a package can OPEN a sealed project when it holds the key — the service
     key in the machine, or the build secret on a source run;
  2. a package holds NOTHING that opens one without it. What ships is
     sha256(K); what unseals is K; and there is no way from the first to the
     second.

The second claim is the one worth spending a test on, because it is the one
that would fail silently. A sealing bug that leaves the bytes readable does
not break a screen, does not fail a build and does not show up in use: the
panel would simply work, and every customer's package would carry every
other customer's inventory in the clear.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from .support.base import PanelTest

from panel import editions, settings
from panel.adminkey import sealed, secret, vault
from panel.editions import catalogue


SECRET = b"a-build-secret-for-the-tests"


def key_for(value: bytes = SECRET) -> bytes:
    """K for a secret. The value a service key carries."""
    return secret.derive(value)


class TheCipher(unittest.TestCase):
    """`vault`, on its own. No edition, no files, no key material."""

    def test_a_sealed_file_comes_back_byte_for_byte(self):
        key = key_for()
        for body in (b"", b"x", b'{"devices": []}', os.urandom(9000)):
            self.assertEqual(vault.unseal(key, vault.seal(key, body)), body)

    def test_the_wrong_key_opens_nothing(self):
        blob = vault.seal(key_for(), b"another customer's device list")
        self.assertIsNone(vault.unseal(key_for(b"a-different-secret"), blob))

    def test_the_digest_that_ships_does_not_open_it(self):
        """THE CLAIM THE WHOLE ARRANGEMENT RESTS ON.

        A customer package is built with D = sha256(K) and nothing else. If
        D opened a sealed file, every package would carry the means to read
        every other customer's inventory and the separation would be a
        decoration.
        """
        key = key_for()
        blob = vault.seal(key, b"another customer's device list")
        digest = secret.digest(key)
        self.assertIsNone(vault.unseal(bytes.fromhex(digest), blob))
        self.assertIsNone(vault.unseal(digest.encode("ascii"), blob))

    def test_a_tampered_file_is_refused_rather_than_decrypted(self):
        key = key_for()
        blob = bytearray(vault.seal(key, b'{"devices": []}'))
        for index in (0, len(vault.MAGIC) + 1, len(blob) - 1):
            broken = bytearray(blob)
            broken[index] ^= 0x01
            self.assertIsNone(vault.unseal(key, bytes(broken)),
                              f"byte {index} was accepted")

    def test_two_seals_of_the_same_file_differ(self):
        """The nonce is per seal, so one keystream is never used twice."""
        key, body = key_for(), b'{"devices": []}'
        self.assertNotEqual(vault.seal(key, body), vault.seal(key, body))

    def test_rubbish_is_a_refusal_and_never_an_exception(self):
        key = key_for()
        for blob in (b"", b"nope", b"DAPSEAL1", None, 5, object()):
            self.assertIsNone(vault.unseal(key, blob))
        for bad_key in (b"", b"short", None, "text"):
            self.assertIsNone(vault.unseal(bad_key, vault.seal(key, b"x")))


class SealedProjects(PanelTest):
    """`sealed`, against a tree where the plaintext map is NOT there."""

    def setUp(self):
        super().setUp()
        self.bundle = Path(tempfile.mkdtemp(prefix="panel-bundle-"))
        self._old_resource = settings.resource_dir
        settings.resource_dir = lambda: self.bundle
        self.addCleanup(setattr, settings, "resource_dir", self._old_resource)
        # The catalogue rows for a project this edition does not own. Its
        # real map IS in the checkout, so `_resolve` would use it directly
        # and never reach the sealed path — point the source elsewhere.
        self.project = next(p for p in catalogue.ALL_PROJECTS
                            if p.key == "gaziray")
        self.body = json.dumps({"switches": [], "sealed": True}).encode()

    def seal_into_bundle(self, key=None, name=None):
        blob = vault.seal(key or key_for(), self.body)
        (self.bundle / (name or f"{self.project.map_name}.sealed")
         ).write_bytes(blob)

    def foreign_without_plaintext(self):
        """`foreign_projects`, with the checkout's own maps hidden.

        The suite runs from a source tree that holds every map, which is the
        one arrangement where the sealed path is never taken. Redirecting
        `source_path` at a folder that does not exist is what a customer's
        package looks like: the map is not there, only the sealed blob is.
        """
        import dataclasses
        return (dataclasses.replace(
            self.project,
            source_path=("no-such-folder", self.project.map_name),
            checklist_source=("no-such-folder",
                              self.project.checklist_name)),)

    def test_the_map_is_opened_when_the_key_is_in_hand(self):
        self.seal_into_bundle()
        with unittest.mock.patch.object(sealed, "foreign_projects",
                                        self.foreign_without_plaintext):
            opened = sealed._resolve(self.foreign_without_plaintext()[0],
                                     key_for())
        self.assertIsNotNone(opened)
        self.assertEqual(Path(opened.path).read_bytes(), self.body)
        # The row keeps everything that makes it that project — the broker
        # and the width are not decoration, a run reads them.
        self.assertEqual(opened.broker, self.project.broker)
        self.assertEqual(opened.prefix, self.project.prefix)

    def test_without_a_key_the_project_is_simply_not_offered(self):
        """A CUSTOMER'S PACKAGE, which is the case that matters.

        The suite itself runs holding the build secret (see
        tests/support/base.py), so "no key" has to be built rather than
        assumed — otherwise this passes by opening the file, which is the
        opposite of what it claims.
        """
        self.seal_into_bundle()
        with unittest.mock.patch.object(secret, "content_key",
                                        return_value=None):
            self.assertIsNone(
                sealed._resolve(self.foreign_without_plaintext()[0], b""))

    def test_the_wrong_key_does_not_open_it(self):
        self.seal_into_bundle()
        self.assertIsNone(sealed._resolve(
            self.foreign_without_plaintext()[0], key_for(b"someone-else")))

    def test_a_project_with_no_sealed_file_is_not_offered(self):
        """A package built without the secret ships no sealed files at all."""
        self.assertIsNone(
            sealed._resolve(self.foreign_without_plaintext()[0], key_for()))

    def test_the_checklist_travels_with_the_map(self):
        self.seal_into_bundle()
        sheet = b"PK\x03\x04 not really a workbook, but bytes are bytes"
        (self.bundle / f"{self.project.checklist_name}.sealed").write_bytes(
            vault.seal(key_for(), sheet))
        opened = sealed._resolve(self.foreign_without_plaintext()[0],
                                 key_for())
        self.assertEqual(Path(opened.checklist_file).read_bytes(), sheet)
        self.assertEqual(editions.checklist_path(opened),
                         Path(opened.checklist_file))

    def test_a_map_whose_checklist_will_not_open_still_opens(self):
        """The workbook falls back to the shared template, the map is kept.

        Losing the report is an inconvenience; losing the project because of
        it would be the wrong trade.
        """
        self.seal_into_bundle()
        (self.bundle / f"{self.project.checklist_name}.sealed").write_bytes(
            b"not a sealed file at all")
        opened = sealed._resolve(self.foreign_without_plaintext()[0],
                                 key_for())
        self.assertIsNotNone(opened)
        self.assertEqual(opened.checklist_file, "")
        self.assertEqual(editions.checklist_path(opened),
                         Path(settings.EXCEL_TEMPLATE))


class TheProjectMenu(PanelTest):
    """What `editions.projects()` offers, in each mode."""

    def test_a_customer_sees_only_their_own(self):
        editions.set_admin(False)
        offered = {project.key for project in editions.projects()}
        self.assertEqual(offered, {"yatakli", "vip"})

    def test_admin_mode_offers_the_others(self):
        editions.set_admin(True)
        offered = {project.key for project in editions.projects()}
        self.assertIn("gaziray", offered)
        self.assertIn("gdm", offered)

    def test_leaving_admin_mode_takes_them_away_again(self):
        editions.set_admin(True)
        self.assertIn("gaziray",
                      {p.key for p in editions.projects()})
        editions.set_admin(False)
        self.assertNotIn("gaziray",
                         {p.key for p in editions.projects()})

    def test_a_foreign_project_counts_as_an_extra(self):
        """So that leaving admin mode puts the customer's own map back.

        `lifecycle.leave_admin` falls back only when the open project is an
        extra. A foreign project that did not count as one would stay on
        screen with the mode gone — the exact leak this all exists to stop.
        """
        editions.set_admin(True)
        gaziray = editions.find_project("gaziray")
        self.assertIsNotNone(gaziray)
        self.assertTrue(editions.is_extra(gaziray))


if __name__ == "__main__":
    unittest.main()
