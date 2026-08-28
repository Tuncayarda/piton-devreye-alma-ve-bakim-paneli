#!/usr/bin/env python3
"""The service key — the only way into admin mode on a customer package.

Two properties carry the whole arrangement, and both are tested here:

  1. A CUSTOMER PACKAGE CANNOT MINT A KEY. It is built with a digest, not
     with the secret, and there is no route back from one to the other.
  2. READING A STICK NEVER RAISES. It is removable media somebody else wrote
     to; the watcher runs on a background thread, and an exception there
     would leave the panel believing no key had ever been inserted, with
     nothing on screen saying why.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from .support.base import PanelTest

from panel import (adminkey, api, editions, i18n, jobs,
                   settings)
from panel.adminkey import (handback, handoff, keyfile,
                            media, pack, secret, volumes, watcher)

SECRET = "a-build-secret-for-the-tests"


def with_secret():
    """A build that holds the secret — the service package."""
    return mock.patch.dict(os.environ, {"DAP_ADMIN_KEY_SECRET": SECRET})


def bare_build(case):
    """A build that can recognise no key at all.

    Three things have to go, not one: the secret, the digest, AND the place a
    key written from source is remembered — one test writing a key would
    otherwise decide what the next test can recognise. `patch.dict` puts the
    whole environment back.
    """
    import tempfile
    data = case.enterContext(
        tempfile.TemporaryDirectory(prefix="dabp-bare-"))
    case.enterContext(mock.patch.dict(
        os.environ, {"PANEL_DATA_DIR": data, secret.STORE: data}))
    os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
    os.environ.pop("DAP_ADMIN_KEY_DIGESTS", None)


def as_shipped(case):
    """A run carrying the digest and NOT the secret — every package that
    ships, and the state most of these tests are about.

    The suite exports the secret so that the admin screens are exercised at
    all (tests/support/base.py), and holding the secret is what opens admin
    mode now that no edition does. A test about a CUSTOMER's package has
    therefore to put the secret back where the customer has it: nowhere.
    Call it BEFORE `activate`, which is where the opening mode is decided.
    """
    with with_secret():
        digest = secret.digest(secret.derive(SECRET.encode("utf-8")))
    case.enterContext(mock.patch.dict(
        os.environ, {"DAP_ADMIN_KEY_DIGESTS": digest}, clear=False))
    os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
    return digest


def with_digest_only():
    """A build that holds only the digest — a customer package."""
    with with_secret():
        digest = secret.digest(secret.derive(SECRET.encode("utf-8")))
    environment = {"DAP_ADMIN_KEY_DIGESTS": digest}
    return mock.patch.dict(os.environ, environment, clear=False), digest


class KeyMaterial(unittest.TestCase):

    def setUp(self):
        # The suite runs with a secret in the environment, because the
        # service package really does hold one. Here the ABSENCE is the
        # thing under test, so the build is stripped back to nothing.
        bare_build(self)

    def test_a_customer_package_recognises_a_key_but_cannot_make_one(self):
        """THE POINT OF THE WHOLE SCHEME.

        The customer's build holds sha256(K). It can check a stick with that,
        and there is no way back from it to K — so reading the value out of
        the package they were given does not let them write a stick.
        """
        with with_secret():
            proof = secret.mint()
        patcher, digest = with_digest_only()
        with patcher:
            self.assertTrue(secret.usable())
            self.assertTrue(secret.verify(proof))
            self.assertFalse(secret.can_write())
            with self.assertRaises(RuntimeError):
                secret.mint()
            # What the package carries is not what the stick carries.
            self.assertNotIn(base64.b64decode(proof).hex(), digest)

    def test_a_wrong_key_is_refused(self):
        patcher, _digest = with_digest_only()
        with patcher:
            other = base64.b64encode(b"\x00" * 32).decode("ascii")
            self.assertFalse(secret.verify(other))
            self.assertFalse(secret.verify(""))
            self.assertFalse(secret.verify("not base64 at all"))
            self.assertFalse(secret.verify(None))

    def test_a_proof_of_the_wrong_length_is_refused(self):
        patcher, _digest = with_digest_only()
        with patcher:
            short = base64.b64encode(b"\x01" * 16).decode("ascii")
            self.assertFalse(secret.verify(short))

    def test_two_secrets_are_honoured_while_one_is_rotated(self):
        """Withdrawing a stick means changing the secret and rebuilding. The
        field cannot be updated in one afternoon, so the old digest and the
        new one are both accepted for as long as that takes."""
        with with_secret():
            old_proof = secret.mint()
        with mock.patch.dict(os.environ, {"DAP_ADMIN_KEY_SECRET": "the-next-one"}):
            new_proof = secret.mint()
            new_digest = secret.digest(base64.b64decode(new_proof))
        patcher, old_digest = with_digest_only()
        with patcher, mock.patch.dict(
                os.environ,
                {"DAP_ADMIN_KEY_DIGESTS": f"{old_digest},{new_digest}"}):
            self.assertTrue(secret.verify(old_proof))
            self.assertTrue(secret.verify(new_proof))

    def test_the_digest_can_be_recovered_from_a_stick(self):
        """FOR THE DAY THE BUILD SECRET IS LOST.

        The secret cannot be read back out of a CI secret store and nothing
        reproduces it — but it is not what a package needs. A package needs
        the digest, and the digest is of a value every issued stick carries.
        One surviving stick therefore keeps releases coming that recognise
        every key already in the field.
        """
        import importlib.util
        volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-lost-")))
        with with_secret():
            keyfile.write(volume, "Piton service 01")
            from_secret = secret.digest(secret.derive(SECRET.encode("utf-8")))

        spec = importlib.util.spec_from_file_location(
            "dap_key_digest",
            Path(__file__).resolve().parent.parent / "tools" / "key_digest.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        recovered = tool.digest_of(volume / keyfile.FILENAME)
        self.assertEqual(recovered, from_secret)

        # A build stamped with the recovered digest and nothing else still
        # recognises the stick — and still cannot mint another.
        with mock.patch.dict(os.environ,
                             {"DAP_ADMIN_KEY_DIGESTS": recovered}):
            self.assertTrue(keyfile.read(volume).recognised)
            self.assertFalse(secret.can_write())

    def test_the_recovery_tool_refuses_anything_else(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dap_key_digest2",
            Path(__file__).resolve().parent.parent / "tools" / "key_digest.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        other = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-other-")))
        path = other / keyfile.FILENAME
        path.write_text('{"format": "something else"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            tool.digest_of(path)

    def test_a_key_written_from_source_is_recognised_afterwards(self):
        """THE TRAP THIS CLOSES. A source tree carries no stamp, so a source
        run recognises nothing: the stick goes in and the panel sits there
        as if the slot were empty. Exporting the secret every time is a poor
        answer — it has to be remembered, and it does not survive the
        privilege prompt. So writing a key records what was written.
        """
        volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-dev-")))
        store = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-store-")))
        with mock.patch.dict(os.environ, {secret.STORE: str(store)}):
            with with_secret():
                keyfile.write(volume, "Piton service 01")
            # ...and now with no secret anywhere, as a customer edition run
            # from source would be.
            os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
            os.environ.pop("DAP_ADMIN_KEY_DIGESTS", None)
            self.assertFalse(secret.can_write())
            self.assertTrue(secret.usable())
            self.assertTrue(keyfile.read(volume).recognised)

    def test_the_digest_is_kept_where_an_elevated_run_will_find_it(self):
        """THE BUG THIS CLOSES. The panel restarts itself as root, and
        root's home is not the home of the person who typed
        `tools/key_digest.py --remember`. Kept in the settings directory,
        the digest was written in one place and read in another: the stick
        went in and the panel sat there as if the slot were empty. The
        checkout is the one path both processes agree on.
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(secret.STORE, None)
            self.assertEqual(secret._remembered_file(),
                             settings.ROOT / secret.REMEMBERED)

    def test_a_packaged_build_ignores_what_is_on_disk(self):
        """What a package accepts is decided at build time. A file in the
        settings directory may not add to it, or the separation between
        customer packages would be a file away from gone."""
        store = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-store-")))
        with mock.patch.dict(os.environ, {secret.STORE: str(store)}), \
                mock.patch.object(settings, "FROZEN", True):
            secret.remember("a" * 64)
            self.assertEqual(secret.remembered_digests(), ())
        # Nothing was written either.
        self.assertFalse((store / secret.REMEMBERED).exists())

    def test_only_a_real_digest_is_remembered(self):
        store = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-store-")))
        with mock.patch.dict(os.environ, {secret.STORE: str(store)}):
            # "AA" * 32 is deliberately NOT here: it is 64 hex characters
            # and therefore a perfectly good digest.
            for rubbish in ("", "not-a-digest", "zz" * 32, "a" * 63, None):
                secret.remember(rubbish)
            self.assertEqual(secret.remembered_digests(), ())

    def test_a_build_without_key_material_says_so(self):
        """A fork, or a local build. The panel still runs; it reports that
        admin mode cannot be opened rather than looking like a key that was
        not recognised."""
        self.assertFalse(secret.usable())
        self.assertFalse(secret.can_write())

    def test_the_comparison_is_constant_time(self):
        source = (Path(secret.__file__)).read_text(encoding="utf-8")
        self.assertIn("compare_digest", source)


class TheBootstrap(PanelTest):
    """THE SECRET STANDS IN FOR THE STICK THAT DOES NOT EXIST YET.

    The first service key cannot be made by inserting a service key. So the
    build secret opens admin mode on its own — and that is the ONLY thing
    that opens admin mode without a key.

    THERE IS NO SERVICE PACKAGE ANY MORE. There used to be a fourth edition
    that carried the secret and opened as admin; it is gone, because a build
    that lets itself in is a build that can reach a customer's machine. The
    secret now belongs to whoever cuts the builds, it is never stamped into
    a package (`dabp.spec`), and it is read only from the environment of a
    SOURCE run. So in the field there is no way in but a stick.
    """

    def tearDown(self):
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_the_secret_opens_any_edition_from_source(self):
        """That is the whole of the bootstrap: the machine that writes the
        first key is somebody's own, and it holds the secret."""
        with with_secret():
            for edition_id in editions.IDS:
                with self.subTest(edition_id):
                    editions.activate(edition_id)
                    self.assertTrue(editions.opens_as_admin())
                    self.assertEqual(editions.mode(), "admin")
                    self.assertIn("piscu", editions.views())

    def test_a_packaged_build_cannot_be_opened_by_exporting_it(self):
        """THE RULE THE WHOLE ARRANGEMENT RESTS ON. If a customer could set
        an environment variable and be admin, the stick would be
        decoration. A frozen build reads the stamp and only the stamp, and
        no package is ever stamped with the secret."""
        with with_secret(), mock.patch.object(settings, "FROZEN", True):
            self.assertIsNone(secret.build_secret())
            self.assertFalse(secret.can_write())
            editions.activate("gdm")
            self.assertFalse(editions.opens_as_admin())
            self.assertEqual(editions.mode(), "field")

    def test_a_shipped_package_opens_in_field_mode(self):
        as_shipped(self)
        editions.activate("gdm")
        self.assertFalse(editions.opens_as_admin())
        self.assertEqual(editions.mode(), "field")
        self.assertNotIn("piscu", editions.views())
        # ...and it can still be raised: it recognises the key it was
        # built for, it simply cannot make one.
        self.assertTrue(secret.usable())
        self.assertFalse(secret.can_write())

    def test_with_no_key_material_at_all_there_is_no_route_in(self):
        bare_build(self)
        editions.activate("gdm")
        self.assertEqual(
            api.call("POST", "/api/admin/mode",
                     body={"enter": True}).status, 409)

    def test_a_run_that_opened_as_admin_can_step_down_and_back_up(self):
        """It used to be a one-way door, on the grounds that there was
        nothing to fall back to. There is: the customer's own field view,
        which is exactly what an engineer wants to look at. And nothing was
        given up — the secret is still in hand, so the way back is open."""
        with with_secret():
            editions.activate("vip-yatakli")
            self.assertEqual(editions.mode(), "admin")

            down = api.call("POST", "/api/admin/mode", body={"enter": False})
            self.assertEqual(down.status, 200)
            self.assertEqual(down.body["mode"], "field")
            self.assertNotIn("piscu", down.body["views"])

            # ...and back, with nothing plugged into the machine.
            with mock.patch.object(volumes, "removable", return_value=[]):
                up = api.call("POST", "/api/admin/mode", body={"enter": True})
        self.assertEqual(up.status, 200)
        self.assertEqual(up.body["mode"], "admin")
        self.assertIn("piscu", up.body["views"])

    def test_the_ui_is_told_it_needs_no_key(self):
        """`adminByDefault` is what the window offers the way back in on
        (see renderMode in static/js/app.js): with the secret it needs no
        stick, and without one it needs the stick to be recognised."""
        with with_secret():
            editions.activate("vip-yatakli")
            body = api.call("GET", "/api/edition").body
        self.assertTrue(body["adminByDefault"])
        self.assertTrue(body["canWriteKey"])

    def test_a_shipped_package_is_told_it_may_be_raised(self):
        """It can recognise a key, so the UI offers the question; it cannot
        write one, so the screen that mints keys is not there."""
        as_shipped(self)
        editions.activate("gaziray")
        body = api.call("GET", "/api/edition").body
        self.assertEqual(body["mode"], "field")
        self.assertFalse(body["adminByDefault"])
        self.assertTrue(body["adminAvailable"])
        self.assertFalse(body["canWriteKey"])

    def test_a_build_with_no_material_says_so_rather_than_staying_silent(self):
        """Nothing to wait for: the build cannot recognise any key, and
        "insert one" would be advice that never works."""
        bare_build(self)
        editions.activate("gdm")
        body = api.call("GET", "/api/edition").body
        self.assertFalse(body["adminAvailable"])
        self.assertFalse(body["canWriteKey"])


class KeyFileOnTheStick(unittest.TestCase):
    """Everything read here was written by someone else."""

    def setUp(self):
        self.volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dapkey-")))

    def write(self, body) -> Path:
        path = self.volume / keyfile.FILENAME
        path.write_text(json.dumps(body) if isinstance(body, dict) else body,
                        encoding="utf-8")
        return path

    def test_a_volume_with_nothing_on_it_is_simply_not_a_key(self):
        self.assertIsNone(keyfile.read(self.volume))

    def test_a_key_that_cannot_be_read_is_not_an_empty_slot(self):
        """THE BUG THIS CLOSES, and it cost an afternoon. macOS gates
        removable volumes behind a privacy permission; the panel runs
        elevated, and the elevated process was never granted one — so the
        stick is listed and every file on it answers EPERM. Swallowed, that
        is indistinguishable from nothing being plugged in, and the panel
        sat there saying nothing at all.
        """
        self.write({"format": keyfile.FORMAT, "version": keyfile.VERSION,
                    "proof": "irrelevant"})
        with mock.patch.object(Path, "is_file",
                               side_effect=PermissionError(1, "denied")):
            found = keyfile.read(self.volume)
        self.assertIsNotNone(found)
        self.assertFalse(found.recognised)
        self.assertEqual(found.reason, "denied")

    def test_a_refused_read_is_handed_down_to_the_operator(self):
        """AND THEN IT SIMPLY WORKS. The elevated process may not read the
        stick, but the person who plugged it in may — so the read goes
        through their session and the key is recognised without anybody
        being sent to a settings screen."""
        with with_secret():
            keyfile.write(self.volume, "Piton service 01")
            body = (self.volume / keyfile.FILENAME).read_bytes()
            # This process never touches the volume: `is_file` would raise
            # here, exactly as it does in the field, and the read still has
            # to come back whole.
            with mock.patch.object(handback, "applicable",
                                   return_value=True), \
                    mock.patch.object(Path, "is_file",
                                      side_effect=PermissionError(1, "no")), \
                    mock.patch.object(handback, "names",
                                      return_value=[keyfile.FILENAME]), \
                    mock.patch.object(handback, "read_bytes",
                                      return_value=body):
                found = keyfile.read(self.volume)
        self.assertTrue(found.recognised)
        self.assertEqual(found.label, "Piton service 01")

    def test_the_operators_session_is_asked_before_this_process_looks(self):
        """THE ORDERING IS THE FIX. Measured on macOS: whichever side asks
        first decides for the whole process tree, so a direct read that is
        refused takes the handback down with it. `read` must therefore not
        touch the volume at all where there is somebody to hand the work
        to."""
        with with_secret():
            keyfile.write(self.volume, "Piton service 01")
        with mock.patch.object(handback, "applicable", return_value=True), \
                mock.patch.object(handback, "names",
                                  return_value=[keyfile.FILENAME]), \
                mock.patch.object(handback, "read_bytes",
                                  return_value=b"{}") as read_bytes, \
                mock.patch.object(handback, "names") as names, \
                mock.patch.object(Path, "is_file") as is_file:
            keyfile.read(self.volume)
        is_file.assert_not_called()
        # And a key that reads first time costs ONE command, not two: this
        # runs every couple of seconds for as long as the panel is open.
        read_bytes.assert_called_once()
        names.assert_not_called()

    def test_a_refused_volume_with_no_key_on_it_is_still_not_a_key(self):
        """Somebody's holiday photos, on a machine that refuses the panel.
        Reporting THAT as a key nobody was allowed to read would put a
        permission warning on screen for every stick in the building."""
        with mock.patch.object(handback, "applicable", return_value=True), \
                mock.patch.object(handback, "names",
                                  return_value=["DCIM", "notes.txt"]), \
                mock.patch.object(handback, "read_bytes",
                                  return_value=None):
            self.assertIsNone(keyfile.read(self.volume))

    def test_a_genuine_key_round_trips(self):
        with with_secret():
            keyfile.write(self.volume, "Piton service 01")
            found = keyfile.read(self.volume)
        self.assertIsNotNone(found)
        self.assertTrue(found.recognised)
        self.assertEqual(found.label, "Piton service 01")

    def test_a_key_from_another_secret_is_found_and_refused(self):
        """Reported rather than ignored: a stick that looks right and is not
        is otherwise indistinguishable from no stick at all."""
        bare_build(self)
        # Written by hand, NOT through keyfile.write: a foreign stick was
        # made by somebody else's build, and writing one here would remember
        # its digest for source runs (see secret.remember) — which is the
        # one thing that must not happen to a key this build has never seen.
        theirs = secret.derive(b"somebody-elses-secret-entirely")
        self.write({
            "format": keyfile.FORMAT, "version": keyfile.VERSION,
            "proof": base64.b64encode(theirs).decode("ascii"),
            "label": "theirs",
        })
        patcher, _digest = with_digest_only()
        with patcher:
            os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
            found = keyfile.read(self.volume)
        self.assertIsNotNone(found)
        self.assertFalse(found.recognised)
        self.assertEqual(found.reason, "unrecognised")

    def test_nothing_on_a_stick_can_raise(self):
        for body in ("", "{", "[]", "null", '{"format": "something else"}',
                     '{"format": "dabp-admin-key"}',
                     ('{"format": "dabp-admin-key", "version": 99,'
                     ' "proof": "x"}'),
                     ('{"format": "dabp-admin-key", "version": 1,'
                     ' "proof": 12}')):
            with self.subTest(body[:32]):
                self.write(body)
                found = keyfile.read(self.volume)
                self.assertTrue(found is None or not found.recognised)

    def test_a_later_format_is_refused_rather_than_guessed_at(self):
        self.write({"format": keyfile.FORMAT, "version": keyfile.VERSION + 1,
                    "proof": "anything"})
        found = keyfile.read(self.volume)
        self.assertFalse(found.recognised)
        self.assertEqual(found.reason, "version")

    def test_an_enormous_file_is_not_read(self):
        """Never read an unbounded amount from removable media."""
        self.write("x" * (keyfile.MAX_BYTES + 10))
        found = keyfile.read(self.volume)
        self.assertFalse(found.recognised)
        self.assertEqual(found.reason, "oversize")

    def test_a_package_without_the_secret_cannot_write(self):
        """A customer package, and a service one built from a recovered
        digest: both recognise keys, neither makes them."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
            with self.assertRaises(RuntimeError):
                keyfile.write(self.volume, "")

    def test_the_file_is_not_named_dot_key(self):
        """`.gitignore` ignores *.key and CI warns on a tracked one, so a
        fixture with that name would vanish or raise a false alarm."""
        self.assertTrue(keyfile.FILENAME.endswith(".json"))


class Handback(unittest.TestCase):
    """Reading a volume the elevated process is not allowed to read."""

    def test_nothing_is_spawned_where_there_is_nobody_to_ask(self):
        """On Linux and Windows the refusal means something else, and
        running the same command as the same user again is a process spent
        to be told the same thing — twice a second, on the watcher's
        thread."""
        with (mock.patch.object(handback.subprocess, "run") as run,
              mock.patch.object(handback, "applicable",
                                return_value=False)):
            self.assertIsNone(handback.names("/Volumes/X"))
            self.assertIsNone(handback.read_bytes("/Volumes/X/k", 10))
        run.assert_not_called()

    def test_the_command_goes_through_the_operators_session(self):
        with mock.patch.object(handback, "applicable", return_value=True), \
                mock.patch.object(handback, "as_console_user",
                                  side_effect=lambda c: ["sudo", *c]) as hand, \
                mock.patch.object(handback.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"a\nb\n")
            self.assertEqual(handback.names("/Volumes/X"), ["a", "b"])
        hand.assert_called_once()
        self.assertEqual(run.call_args[0][0][:2], ["sudo", "/bin/ls"])

    def test_a_failed_command_reads_as_nothing_rather_than_as_empty(self):
        with mock.patch.object(handback, "applicable", return_value=True), \
                mock.patch.object(handback.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout=b"")
            self.assertIsNone(handback.names("/Volumes/X"))

    def test_the_cap_is_applied_at_the_source(self):
        """What is on the other end is somebody else's media, and a process
        is a poor place to discover that it holds four gigabytes."""
        with mock.patch.object(handback, "applicable", return_value=True), \
                mock.patch.object(handback.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"x")
            handback.read_bytes("/Volumes/X/k", 64)
        self.assertEqual(run.call_args[0][0][:3], ["/usr/bin/head", "-c", "65"])


class SecretFile(PanelTest):
    """The build secret kept in the checkout, like a licence file.

    An environment variable is copied into a process when it STARTS, so
    exporting one while the panel is open reaches nothing and switching
    admin mode on meant restarting through the password box every time.
    A file is asked about at the moment the question is asked.
    """

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.dict(os.environ, {}, clear=False))
        os.environ.pop("DAP_ADMIN_KEY_SECRET", None)
        self.path = secret._secret_file()
        self.addCleanup(self._remove)
        self._remove()
        editions.activate("vip-yatakli")
        self.addCleanup(lambda: editions.activate("vip-yatakli"))

    def _remove(self):
        try:
            self.path.unlink()
        except OSError:
            pass

    def write(self, text: str) -> None:
        self.path.write_text(text, encoding="utf-8")

    def test_the_file_raises_the_run_and_taking_it_away_lowers_it(self):
        """The whole point: no restart at either end."""
        self.assertFalse(editions.opens_as_admin())

        self.write(f"{SECRET}\n")
        self.assertTrue(editions.opens_as_admin())
        self.assertTrue(secret.can_write())
        with mock.patch.object(volumes, "removable", return_value=[]):
            self.assertEqual(
                api.call("POST", "/api/admin/mode",
                         body={"enter": True}).body["mode"], "admin")

            # ...and now it is deleted, with nothing plugged in. The watcher
            # drops the mode exactly as it does when a stick is pulled.
            self._remove()
            self.assertFalse(editions.opens_as_admin())
            watcher.WATCH.observe()
        self.assertEqual(editions.mode(), "field")

    def test_the_poll_carries_the_other_way_in(self):
        """The window offers the way back into admin mode on this, because
        it can change while the panel is open and `/api/edition` is read
        once at launch."""
        self.assertFalse(api.call("GET", "/api/admin/key").body["withoutKey"])
        self.write(SECRET)
        self.assertTrue(api.call("GET", "/api/admin/key").body["withoutKey"])

    def test_the_environment_still_wins(self):
        """A file left behind in a tree must not quietly override what the
        person at the keyboard just exported."""
        self.write("from-the-file")
        with with_secret():
            self.assertEqual(secret.build_secret(),
                             SECRET.encode("utf-8"))

    def test_a_packaged_build_never_reads_it(self):
        """What a package can do is decided at build time. This file on a
        customer's disk would otherwise be "mint service keys for every
        other customer", in a text file."""
        self.write(SECRET)
        with mock.patch.object(settings, "FROZEN", True):
            self.assertIsNone(secret.build_secret())
            self.assertFalse(secret.can_write())

    def test_rubbish_in_that_place_is_not_a_secret(self):
        for content in ("", "   \n", "\x00\xff".encode("latin-1")):
            with self.subTest(repr(content)[:20]):
                if isinstance(content, bytes):
                    self.path.write_bytes(content)
                else:
                    self.write(content)
                self.assertIsNone(secret.build_secret())
        # A directory of that name, too.
        self._remove()
        self.path.mkdir()
        self.addCleanup(self.path.rmdir)
        self.assertIsNone(secret.build_secret())

    def test_the_slow_half_is_worked_out_once(self):
        """`derive` is 600 000 rounds of PBKDF2 and `accepted_digests` is on
        the path of every read of the stick — every couple of seconds, for
        as long as the panel is open."""
        self.write(SECRET)
        secret._DERIVED.clear()
        with mock.patch.object(secret, "derive",
                               side_effect=secret.derive) as derive:
            for _ in range(5):
                secret.accepted_digests()
        derive.assert_called_once()


class Handoff(unittest.TestCase):
    """Getting the build secret past the system's password box.

    The environment does not survive the prompt: the panel restarts itself
    through a dialog that builds a fresh command line under a fresh
    environment. Without this the variable the user exported simply is not
    there in the process that opens, and the panel comes up in field mode as
    though it had been ignored.
    """

    @unittest.skipIf(platform.system() == "Windows",
                     "no handover on Windows: runas takes no environment")
    def test_the_secret_is_handed_over_and_picked_up_once(self):
        with mock.patch.dict(os.environ, {handoff.SECRET_VAR: "s3cr3t"}):
            path = handoff.stash()
            self.assertTrue(path)
            # Readable by this user and by nobody else: it is on disk for
            # the second or two between the password box and the new
            # process reading it. The mode is a POSIX statement; the file
            # is not written at all where it could not be honoured.
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            os.environ.pop(handoff.SECRET_VAR)
            os.environ[handoff.FILE_VAR] = path
            handoff.claim()
            self.assertEqual(os.environ.get(handoff.SECRET_VAR), "s3cr3t")
        # ...and it does not stay behind afterwards.
        self.assertFalse(Path(path).exists())
        self.assertNotIn(handoff.FILE_VAR, os.environ)

    def test_nothing_is_written_where_it_could_never_be_picked_up(self):
        """Windows `runas` takes no environment of ours, so the path would
        never reach the new process — and the file would sit in the
        temporary directory holding a secret nobody ever came for."""
        with mock.patch.dict(os.environ, {handoff.SECRET_VAR: "s3cr3t"}), \
                mock.patch.object(handoff.platform, "system",
                                  return_value="Windows"):
            self.assertEqual(handoff.stash(), "")

    def test_there_is_nothing_to_hand_over_without_a_secret(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(handoff.SECRET_VAR, None)
            self.assertEqual(handoff.stash(), "")

    def test_a_packaged_build_neither_hands_over_nor_accepts(self):
        """What a package can do is decided at build time. A file arriving
        at a customer's package changes nothing about what it will open —
        and it is removed rather than left lying about."""
        volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-hand-")))
        dropped = volume / "secret.txt"
        dropped.write_text("s3cr3t", encoding="utf-8")
        with mock.patch.dict(os.environ, {handoff.SECRET_VAR: "s3cr3t",
                                          handoff.FILE_VAR: str(dropped)}), \
                mock.patch.object(settings, "FROZEN", True):
            self.assertEqual(handoff.stash(), "")
            os.environ.pop(handoff.SECRET_VAR)
            handoff.claim()
            self.assertNotIn(handoff.SECRET_VAR, os.environ)
        self.assertFalse(dropped.exists())

    def test_a_missing_file_is_not_a_failure(self):
        """The elevated process cannot tell why it is not there, and there
        is nothing it could do about it either way."""
        with mock.patch.dict(os.environ,
                             {handoff.FILE_VAR: "/nonexistent/secret.txt"}):
            os.environ.pop(handoff.SECRET_VAR, None)
            handoff.claim()
            self.assertNotIn(handoff.SECRET_VAR, os.environ)


class Volumes(unittest.TestCase):
    """Where a stick shows up, on each platform."""

    def test_windows_skips_the_system_drive(self):
        kernel32 = mock.Mock()
        # A:, C: and E: present.
        kernel32.GetLogicalDrives.return_value = (1 << 0) | (1 << 2) | (1 << 4)
        kernel32.GetDriveTypeW.side_effect = lambda name: {
            "A:\\": volumes.DRIVE_REMOVABLE,
            "C:\\": volumes.DRIVE_FIXED,
            "E:\\": volumes.DRIVE_FIXED,
        }[str(name.value)]
        with mock.patch.dict(os.environ, {"SystemDrive": "C:"}), \
                mock.patch.object(volumes, "ctypes") as ctypes_module:
            ctypes_module.windll.kernel32 = kernel32
            ctypes_module.c_wchar_p = mock.Mock(
                side_effect=lambda value: mock.Mock(value=value))
            found = [str(path) for path in volumes.removable("Windows")]
        # E: is "fixed" but is not the system drive: plenty of USB sticks and
        # every USB SSD enumerate that way, and refusing them would mean a
        # key that works on one engineer's stick and not another's.
        self.assertEqual(found, ["A:\\", "E:\\"])

    def test_linux_looks_under_the_user_who_plugged_it_in(self):
        """THE FIELD TRAP. The panel runs elevated through pkexec, so $USER
        is root — while the desktop mounted the stick under the name of the
        person at the keyboard. Looking only under /media/$USER finds nothing
        on the machine where it matters."""
        with mock.patch.dict(os.environ, {"SUDO_USER": "operator"}, clear=False):
            os.environ.pop("PKEXEC_UID", None)
            os.environ.pop("SUDO_UID", None)
            self.assertEqual(volumes._original_user(), "operator")

    def test_a_folder_on_the_system_disk_is_not_a_volume(self):
        """/mnt/backup on the boot disk is a folder somebody made."""
        here = Path(__file__).resolve().parent
        self.assertEqual(volumes._under([here]), [])


class KeyBesideTheApplication(unittest.TestCase):
    """A key file may sit in the application's own folder, not only on a stick.

    Added for remote work: a panel reached over a remote session has nobody
    at the keyboard to push a stick in, and the screens behind admin mode are
    the ones an engineer needs precisely when they are not in the room.

    What that trades away is the physical part and NOTHING ELSE — the file
    still carries a proof rather than the secret, and it is still checked
    against this build's stamped digests.
    """

    def test_the_folder_is_searched_after_the_sticks(self):
        """A key in hand beats one left in the folder: somebody just pushed
        that one in, and it is the one they meant."""
        with mock.patch.object(volumes, "removable",
                               return_value=[Path("/Volumes/KEY")]), \
                mock.patch.object(volumes, "beside_the_application",
                                  return_value=[Path("/opt/dabp")]):
            self.assertEqual([str(p) for p in volumes.searched()],
                             ["/Volumes/KEY", "/opt/dabp"])

    def test_from_source_it_is_the_checkout(self):
        with mock.patch.object(settings, "FROZEN", False):
            self.assertEqual(volumes.beside_the_application(),
                             [Path(settings.ROOT)])

    def test_frozen_it_is_the_folder_holding_the_executable(self):
        """Beside the .exe, which is where somebody would put it.

        NOT the settings directory: the panel restarts itself elevated and
        that directory hangs off HOME, which the elevation changes.
        """
        exe = Path(__file__).resolve()
        with mock.patch.object(settings, "FROZEN", True), \
                mock.patch.object(volumes.sys, "executable", str(exe)):
            self.assertEqual(volumes.beside_the_application(), [exe.parent])

    def test_an_unreadable_location_is_no_location(self):
        """Never raises: this runs on the watcher's thread, and an exception
        there leaves the panel believing no key was ever inserted."""
        with mock.patch.object(volumes, "Path", side_effect=OSError("gone")):
            self.assertEqual(volumes.beside_the_application(), [])

    def test_a_file_in_the_folder_is_still_checked_against_the_digests(self):
        """THE PART THAT WAS NOT TRADED AWAY.

        Being in the right folder is not what makes a key valid; carrying a
        proof this build recognises is. A file somebody else put there is
        refused exactly as a wrong stick is.
        """
        folder = Path(tempfile.mkdtemp())
        (folder / keyfile.FILENAME).write_text(json.dumps({
            "format": keyfile.FORMAT, "version": keyfile.VERSION,
            "proof": base64.b64encode(b"not a real proof").decode(),
        }), encoding="utf-8")
        with mock.patch.object(secret, "accepted_digests",
                               return_value=("00" * 32,)):
            entry = keyfile.read(folder)
        self.assertIsNotNone(entry)
        self.assertFalse(entry.recognised)
        self.assertEqual(entry.reason, "unrecognised")

    def test_the_watcher_looks_in_both_places(self):
        """The change detector still watches sticks only — the folder does
        not appear or disappear — but the read covers both."""
        source = (settings.ROOT / "panel" / "adminkey"
                  / "watcher.py").read_text(encoding="utf-8")
        self.assertIn("for volume in volumes.searched():", source)
        self.assertIn("volumes.removable())", source)


class RemovableMedia(unittest.TestCase):
    """Erasing a drive is the one thing the panel does that destroys data
    outside its own files. What these tests hold in place is the rule that
    makes it safe to have at all: the SYSTEM DISK IS NEVER A CANDIDATE, and
    an id that is not on the list is refused however it arrives."""

    # ── macOS ────────────────────────────────────────────────────────────
    def test_macos_lists_a_usb_stick(self):
        self.assertTrue(media._macos_eligible({
            "Internal": False, "SystemImage": False,
            "VirtualOrPhysical": "Physical", "Ejectable": True}))

    def test_macos_never_lists_the_internal_disk(self):
        self.assertFalse(media._macos_eligible({
            "Internal": True, "SystemImage": True,
            "VirtualOrPhysical": "Physical", "Ejectable": False}))

    def test_macos_never_lists_the_disk_the_system_booted_from(self):
        """An external disk CAN be the boot disk — a Mac started from a
        USB SSD. Being external is not enough on its own."""
        self.assertFalse(media._macos_eligible({
            "Internal": False, "SystemImage": True,
            "VirtualOrPhysical": "Physical", "Ejectable": True}))

    def test_macos_never_lists_a_disk_image(self):
        self.assertFalse(media._macos_eligible({
            "Internal": False, "SystemImage": False,
            "VirtualOrPhysical": "Virtual", "Ejectable": True}))

    # ── Windows ──────────────────────────────────────────────────────────
    def test_windows_lists_usb_and_card_readers_only(self):
        for bus, allowed in (("USB", True), ("SD", True), ("MMC", True),
                             ("SATA", False), ("NVMe", False),
                             ("RAID", False), ("", False)):
            with self.subTest(bus):
                self.assertEqual(
                    media._windows_eligible({"BusType": bus}), allowed)

    def test_windows_never_lists_the_disk_it_booted_from(self):
        """Windows can boot from USB too."""
        self.assertFalse(media._windows_eligible(
            {"BusType": "USB", "IsBoot": True}))
        self.assertFalse(media._windows_eligible(
            {"BusType": "USB", "IsSystem": True}))

    def test_one_windows_disk_still_parses(self):
        """PowerShell's ConvertTo-Json gives an object, not a list, when
        there is exactly one row — the machine with a single USB stick in
        it, which is the ordinary case."""
        self.assertEqual(media._as_list('{"Number": 2}'), [{"Number": 2}])
        self.assertEqual(media._as_list('[{"Number": 2}]'), [{"Number": 2}])
        self.assertEqual(media._as_list("not json"), [])
        self.assertEqual(media._as_list(""), [])

    # ── Linux ────────────────────────────────────────────────────────────
    def test_linux_lists_a_hotplugged_disk(self):
        self.assertTrue(media._linux_eligible({
            "type": "disk", "rm": True, "hotplug": True,
            "mountpoints": [None]}))

    def test_linux_never_lists_a_fixed_disk(self):
        self.assertFalse(media._linux_eligible({
            "type": "disk", "rm": False, "hotplug": False,
            "mountpoints": [None]}))

    def test_linux_never_lists_the_running_system(self):
        """A machine can run from a hot-pluggable disk. The root filesystem
        sits on a CHILD of it, so the whole tree is walked."""
        self.assertFalse(media._linux_eligible({
            "type": "disk", "rm": True, "hotplug": True,
            "mountpoints": [None],
            "children": [{"mountpoints": ["/"]},
                         {"mountpoints": ["/boot/efi"]}]}))

    def test_linux_ignores_partitions_and_loop_devices(self):
        for kind in ("part", "loop", "rom"):
            with self.subTest(kind):
                self.assertFalse(media._linux_eligible(
                    {"type": kind, "rm": True, "hotplug": True}))

    # ── the id the client sends ──────────────────────────────────────────
    def test_an_id_that_is_not_on_the_list_is_refused(self):
        """It was true when the screen drew. A drive can be unplugged and
        another plugged in before the click, so the list is read again."""
        with mock.patch.object(media, "drives", return_value=[]):
            with self.assertRaises(media.MediaError) as raised:
                media.prepare("/dev/disk0")
        self.assertEqual(str(raised.exception), "not-removable")

    def test_a_missing_disk_tool_is_named(self):
        """Linux ships without mkfs.vfat more often than not, and that is
        something the operator can actually fix."""
        with self.assertRaises(media.MediaError) as raised:
            media._run(["dabp-no-such-disk-tool"])
        self.assertIn("missing tool", str(raised.exception))

    def test_listing_never_raises(self):
        """It is a screen, not an operation: an unreadable disk tool leaves
        the list empty and the screen says so."""
        with mock.patch.object(media, "_run",
                               side_effect=OSError("no disk tool")):
            self.assertEqual(media.drives("Darwin"), [])
            self.assertEqual(media.drives("Linux"), [])

    def test_the_volume_label_fits_fat32(self):
        """FAT32 labels are eleven characters, upper case. The operator's
        own note is not this — it goes inside the key file, where it has
        room."""
        self.assertLessEqual(len(media.VOLUME_LABEL), 11)
        self.assertEqual(media.VOLUME_LABEL, media.VOLUME_LABEL.upper())


class PrepareEndpoint(PanelTest):

    def tearDown(self):
        watcher.WATCH.reset()
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_a_package_that_holds_no_secret_cannot_erase_anything(self):
        """The one operation that destroys data outside the panel's own
        files is not reached by being in admin mode."""
        as_shipped(self)
        editions.activate("gdm")
        editions.set_admin(True)
        response = api.call("POST", "/api/admin/key/prepare",
                            body={"drive": "/dev/disk9"})
        self.assertEqual(response.status, 403)

    def test_the_field_view_cannot_even_list_drives(self):
        as_shipped(self)
        editions.activate("gaziray")
        self.assertEqual(
            api.call("GET", "/api/admin/key/drives").status, 403)

    def test_a_drive_that_is_gone_is_reported_not_erased(self):
        editions.activate("vip-yatakli")
        with with_secret(), mock.patch.object(media, "drives",
                                              return_value=[]):
            response = api.call("POST", "/api/admin/key/prepare",
                                body={"drive": "/dev/disk9"})
        self.assertEqual(response.status, 404)

    def test_preparing_erases_then_writes_the_key(self):
        editions.activate("vip-yatakli")
        volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dabp-prep-")))
        drive = media.Drive(id="/dev/disk9", name="Kingston", size=1 << 30,
                            bus="USB")
        with with_secret(), \
                mock.patch.object(media, "drives", return_value=[drive]), \
                mock.patch.object(media, "prepare",
                                  return_value=volume) as prepare:
            response = api.call("POST", "/api/admin/key/prepare",
                                body={"drive": "/dev/disk9",
                                      "label": "Piton 01"})
        self.assertEqual(response.status, 200)
        prepare.assert_called_once_with("/dev/disk9")
        # Read back inside the same build: a package with no key material
        # recognises nothing, which is what "recognised" means.
        with with_secret():
            found = keyfile.read(volume)
        self.assertTrue(found.recognised)
        self.assertEqual(found.label, "Piton 01")


class Pack(unittest.TestCase):
    """Project device lists carried on the same stick."""

    def setUp(self):
        self.volume = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="dappack-")))
        self.folder = self.volume / keyfile.PACK_DIR
        self.folder.mkdir()

    def tearDown(self):
        pack.clear_session()

    def test_a_map_is_copied_off_the_stick(self):
        """The copy is what the panel opens, so pulling the stick cannot
        break a run that is already under way."""
        (self.folder / "DeviceMap_Gaziray.json").write_text("{}", "utf-8")
        found = pack.projects(self.volume)
        self.assertEqual([p.key for p in found], ["gaziray"])
        self.assertEqual(found[0].label, "Gaziray")
        self.assertNotIn(str(self.volume), found[0].path)
        self.assertTrue(Path(found[0].path).is_file())

    def test_an_oversized_map_is_skipped(self):
        (self.folder / "DeviceMap_Big.json").write_text(
            "x" * (pack.MAX_BYTES + 1), "utf-8")
        self.assertEqual(pack.projects(self.volume), [])

    def test_a_volume_with_no_pack_is_not_an_error(self):
        self.assertEqual(pack.projects(Path("/nonexistent-volume")), [])


class Endpoints(PanelTest):
    """What the API says about the key, and what it refuses."""

    def tearDown(self):
        watcher.WATCH.reset()
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_the_key_state_carries_no_key(self):
        """Whatever the UI polls twice a second must be worthless to steal."""
        body = api.call("GET", "/api/admin/key").body
        text = json.dumps(body)
        self.assertNotIn("proof", text)
        for digest in secret.accepted_digests():
            self.assertNotIn(digest, text)
        # Nor which drive it is on: no field screen needs to know.
        self.assertNotIn("volume", body)

    def test_admin_mode_is_refused_without_a_stick(self):
        as_shipped(self)
        editions.activate("gdm")
        with mock.patch.object(watcher.WATCH, "observe",
                               return_value={"present": False,
                                             "recognised": False}):
            response = api.call("POST", "/api/admin/mode",
                                body={"enter": True})
        self.assertEqual(response.status, 403)
        self.assertEqual(editions.mode(), "field")

    def test_a_key_that_could_not_be_read_says_so_rather_than_refusing(self):
        """"Your stick is wrong" and "nobody let me read your stick" are
        different problems, and only one of them the user can fix."""
        as_shipped(self)
        editions.activate("gdm")
        with mock.patch.object(watcher.WATCH, "observe",
                               return_value={"present": True,
                                             "recognised": False,
                                             "reason": "denied"}):
            response = api.call("POST", "/api/admin/mode",
                                body={"enter": True})
        self.assertEqual(response.status, 403)
        self.assertEqual(response.body["error"],
                         i18n.t("error.adminKeyDenied"))

    def test_admin_mode_opens_with_one(self):
        as_shipped(self)
        editions.activate("gdm")
        with mock.patch.object(watcher.WATCH, "observe",
                               return_value={"present": True,
                                             "recognised": True}):
            response = api.call("POST", "/api/admin/mode",
                                body={"enter": True})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["mode"], "admin")
        self.assertIn("piscu", response.body["views"])

    def test_the_client_is_never_taken_at_its_word(self):
        """Entering re-reads the stick; it does not consult the last poll."""
        as_shipped(self)
        editions.activate("gdm")
        with mock.patch.object(watcher.WATCH, "observe") as observe:
            observe.return_value = {"present": False, "recognised": False}
            api.call("POST", "/api/admin/mode", body={"enter": True})
        observe.assert_called_once()

    def test_a_package_that_holds_no_secret_cannot_write_a_key(self):
        """Guarded twice, and this is the second: a shipped package raised
        to admin mode by a stick CAN reach this path, and must still not be
        able to make more sticks. It holds a one-way digest, not the value
        a stick carries."""
        as_shipped(self)
        editions.activate("gdm")
        editions.set_admin(True)
        response = api.call("POST", "/api/admin/key/write",
                            body={"volume": "/x"})
        self.assertEqual(response.status, 403)

    def test_the_field_view_cannot_reach_the_key_endpoints(self):
        as_shipped(self)
        editions.activate("gaziray")
        for method, path in (("GET", "/api/admin/key/volumes"),
                             ("POST", "/api/admin/key/write")):
            with self.subTest(path):
                response = api.call(method, path, body={})
                self.assertEqual(response.status, 403)

    def test_a_path_outside_the_listed_volumes_is_refused(self):
        """The body names a drive from OUR list, never a path of its own: an
        arbitrary path here would be "write a file anywhere on this machine",
        in a process that runs elevated."""
        editions.activate("vip-yatakli")
        with with_secret(), mock.patch.object(adminkey, "removable",
                                              return_value=[]):
            response = api.call("POST", "/api/admin/key/write",
                                body={"volume": "/etc"})
        self.assertEqual(response.status, 404)


class Revocation(PanelTest):
    """What happens when the stick comes out."""

    def tearDown(self):
        watcher.WATCH.reset()
        editions.activate("vip-yatakli")
        super().tearDown()

    def test_pulling_the_key_closes_admin_mode(self):
        as_shipped(self)
        editions.activate("gdm")
        editions.set_admin(True)
        with mock.patch.object(volumes, "removable", return_value=[]):
            watcher.WATCH.observe()
        self.assertEqual(editions.mode(), "field")

    def test_a_write_in_progress_holds_the_door_open(self):
        """Dropping privileges half-way through an IP assignment or a
        firmware upload is a worse outcome than a door left open for another
        few minutes."""
        as_shipped(self)
        editions.activate("gdm")
        editions.set_admin(True)
        job = jobs.Job("firmware", "installing", 1)
        job.state = jobs.RUNNING
        with mock.patch.object(jobs.QUEUE, "list", return_value=[job]), \
                mock.patch.object(volumes, "removable", return_value=[]):
            watcher.WATCH.observe()
        self.assertEqual(editions.mode(), "admin")
        self.assertTrue(watcher.WATCH.snapshot()["revokePending"])
        # ...and it closes as soon as the queue clears.
        with mock.patch.object(volumes, "removable", return_value=[]):
            watcher.WATCH.observe()
        self.assertEqual(editions.mode(), "field")

    def test_a_run_that_opened_as_admin_is_unaffected(self):
        """It did not need a key to get in, so a key going away takes
        nothing with it."""
        editions.activate("vip-yatakli")
        with mock.patch.object(volumes, "removable", return_value=[]):
            watcher.WATCH.observe()
        self.assertEqual(editions.mode(), "admin")

    def test_a_stick_pushed_in_is_noticed_without_the_slow_beat(self):
        """THE ASYMMETRY THIS CLOSES. Pulling a stick out was noticed at
        once and pushing one in was not — which is what a two-second beat
        does to a volume that takes a second or two to mount: unmounting
        lands inside a tick, mounting finishes just after one has gone by.
        So the cheap half of the question — which volumes are mounted — is
        asked far more often than the whole of it.
        """
        mounted: list = []
        watch = watcher.KeyWatch()
        self.addCleanup(watch.stop)
        with mock.patch.object(volumes, "removable",
                               side_effect=lambda system=None: list(mounted)), \
                mock.patch.object(volumes, "beside_the_application",
                                  return_value=[]), \
                mock.patch.object(keyfile, "read", return_value=keyfile.KeyFile(
                    Path("/Volumes/X/key"), False, reason="unrecognised")):
            watch.start()
            deadline = time.monotonic() + 1.0
            while watch.snapshot()["generation"] == 0 \
                    and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(watch.snapshot()["present"])

            mounted.append(Path("/Volumes/X"))
            # Comfortably inside INTERVAL: if the slow beat were what
            # noticed, this would still be False here.
            deadline = time.monotonic() + watcher.INTERVAL * 0.6
            while not watch.snapshot()["present"] \
                    and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertTrue(watch.snapshot()["present"])

    def test_asking_is_what_makes_an_observation(self):
        """WHY THE PANEL USED TO NOTICE LATE. The window polls every couple
        of seconds and the thread looked every couple of seconds, and the
        two are not in step: a stick pushed in just after a look was
        answered out of that look, so the news could be two intervals old.
        Now a stale answer is re-taken by whoever asks."""
        with mock.patch.object(volumes, "removable", return_value=[]):
            watcher.WATCH.observe()
            with mock.patch.object(watcher.WATCH, "observe") as observe:
                # Just taken: the caller is handed what is already there.
                watcher.WATCH.fresh()
                observe.assert_not_called()
                # Stale: the caller takes its own look rather than waiting
                # for the thread's next one.
                watcher.WATCH._seen_at -= watcher.FRESH + 1.0
                watcher.WATCH.fresh()
                observe.assert_called_once()

    def test_the_observation_counter_moves_only_on_a_change(self):
        """The UI polls twice a second and acts on this number alone."""
        with mock.patch.object(volumes, "removable", return_value=[]):
            first = watcher.WATCH.observe()["generation"]
            self.assertEqual(watcher.WATCH.observe()["generation"], first)


if __name__ == "__main__":
    unittest.main()
