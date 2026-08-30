#!/usr/bin/env python3
"""The remote service session — admin mode granted from somewhere else.

Three properties carry the arrangement, and each is the subject of a class
below:

  1. A CUSTOMER PACKAGE CANNOT GRANT ITSELF. It holds a public key and no
     private one, so the only thing that can open the door is an answer the
     grant service signed.
  2. AN ANSWER CANNOT BE REUSED. Every round carries a nonce the panel has
     just invented; yesterday's recording, and a server the customer runs
     themselves, both fail on it. Without this the whole feature would be a
     file on the customer's disk again, which is what it exists to replace.
  3. THE DOOR CLOSES BY ITSELF. Not by noticing a disconnection — by a
     deadline that nothing renews. Silence is enough.

And one that is not about this feature at all but about what adding it could
break: the service key and the remote session are TWO SOURCES for one mode,
and neither may take back what the other is holding (`Arbitration`).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import unittest
from unittest import mock

from .support.base import PanelTest
from .support import ed25519_sign as signer

from panel import api, authority, editions, remotekey
from panel.remotekey import (client, ed25519, pairing, protocol,
                             session, verify, watcher)
from panel.adminkey import watcher as key_watcher

SEED = b"a" * 32
OTHER_SEED = b"b" * 32


# ── a grant service, in this process ─────────────────────────────────────
class Answer:
    """What `requests` hands back, reduced to what the client reads."""

    def __init__(self, status: int, body, raw: bytes | None = None):
        self.status_code = status
        self._body = body
        self.content = (raw if raw is not None
                        else json.dumps(body).encode("utf-8"))

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeService:
    """Signs what it is asked to sign, and can be told to misbehave."""

    def __init__(self, *, seed: bytes = SEED, edition: str = "*",
                 label: str = "Gaziray", ttl: float = 12.0,
                 session_id: str = "sess-1"):
        self.seed = seed
        self.edition = edition
        self.label = label
        self.ttl = ttl
        self.session_id = session_id
        self.status = 200
        # The word the service puts in a refusal. For log files, and for the
        # one place the panel reads it: telling two 403s apart.
        self.word = "no"
        # Seconds, sent with a lockout and with nothing else.
        self.retry = 0
        # What a sign-in answers with. The same eight characters a code path
        # would have had dictated, because it is the same kind of session.
        self.code = "K7M29QX4"
        self.error: Exception | None = None
        self.calls: list[dict] = []
        # Overrides applied to the payload before signing, so a test can
        # produce a grant that is correctly signed and wrong.
        self.tamper: dict = {}
        self.prefix = protocol.PREFIX

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "body": json, "timeout": timeout})
        if self.error is not None:
            raise self.error
        if self.status != 200:
            body = {"error": self.word}
            if self.retry:
                body["retry"] = self.retry
            return Answer(self.status, body)
        if url.endswith("/v1/release"):
            return Answer(200, {"closed": json.get("code")})
        if url.endswith("/v1/signup"):
            return Answer(200, {"waiting": True,
                                "account": {"email": json.get("email"),
                                            "name": json.get("name")}})
        if url.endswith("/v1/signin"):
            return Answer(200, {"code": self.code, "expires": 1788031351,
                                "edition": self.edition,
                                "account": {"email": json.get("email"),
                                            "name": "Ali"}})
        return Answer(200, self.grant(json["nonce"], json["installId"]))

    def grant(self, nonce: str, install_id: str) -> dict:
        body = {"v": protocol.VERSION, "nonce": nonce, "installId": install_id,
                "edition": self.edition, "label": self.label,
                "issuedAt": 1756000000, "ttl": self.ttl,
                "session": self.session_id}
        body.update(self.tamper)
        payload = json.dumps(body, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        signature = signer.sign(self.seed, self.prefix + payload)
        return {"payload": verify.encode(payload),
                "sig": verify.encode(signature)}


class FakePairing:
    """The same service, with the pairing desk open.

    Routed by path rather than by a flag, because the point of most of these
    tests is WHICH conversation the panel had: a square asked for, a poll
    answered, and — only once somebody approves — a grant fetched with the
    code that came back.
    """

    # 33 modules and four of quiet zone on each side, which is what the
    # service's own encoder produces for a pairing address. The modules are
    # drawn the way it draws them — one unit square each — because that is
    # what the panel measures the margin with.
    QR = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 41 41">'
          '<rect width="41" height="41" fill="#ffffff"/>'
          '<path d="M4 4h1v1h-1zM36 4h1v1h-1zM4 36h1v1h-1z"'
          ' fill="#000000"/></svg>')

    def __init__(self, *, seed: bytes = SEED):
        self.grants = FakeService(seed=seed)
        self.state = "pending"
        self.code = "K7M29QX4"
        self.pair_id = "JYB6QBC7WWB7"
        self.poll_key = "k" * 32
        # None means "the address the panel is entitled to expect".
        self.url: str | None = None
        self.qr = self.QR
        self.status: dict[str, int] = {}
        self.calls: list[dict] = []

    def post(self, url, json=None, timeout=None):
        path = url[url.index("/v1/"):]
        self.calls.append({"path": path, "body": json})
        status = self.status.get(path, 200)
        if status != 200:
            return Answer(status, {"error": "no"})
        if path == "/v1/pair":
            return Answer(200, {
                "pairId": self.pair_id, "pollKey": self.poll_key,
                "url": self.address(), "qr": self.qr,
                "expires": 1788030151, "pollAfter": 2})
        if path == "/v1/pair/poll":
            if self.state != "approved":
                return Answer(200, {"state": self.state})
            return Answer(200, {"state": "approved", "code": self.code,
                                "label": "Ankara Gar", "edition": "*",
                                "expires": 1788031351, "operator": "tuncay"})
        if path == "/v1/pair/cancel":
            return Answer(200, {"cancelled": self.pair_id})
        return self.grants.post(url, json=json, timeout=timeout)

    def address(self) -> str:
        if self.url is not None:
            return self.url
        return f"{verify.service_url().rstrip('/')}/p/{self.pair_id}"

    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]


def trusting(*seeds: bytes):
    """A build that accepts exactly these signers."""
    keys = tuple(verify.encode(signer.public_key(seed)) for seed in seeds)
    return mock.patch.object(verify, "TRUSTED_KEYS", keys)


def serving(service: FakeService):
    return mock.patch.object(client, "_session", return_value=service)


class Vendored(unittest.TestCase):
    """The verification itself, against the RFC rather than against us.

    A hand-written implementation checked only by signatures the same suite
    produced would agree with itself perfectly while being wrong.
    """

    # RFC 8032 §7.1, vectors 1, 2 and 3. Each concatenation is parenthesised
    # on purpose: a bare string beside another inside a tuple is the shape of
    # a forgotten comma, and ruff refuses to tell the two apart.
    VECTORS = (
        (("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f7075"
          "11a"),
         "",
         ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490"
          "1555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e"
          "7a100b")),
        (("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af46"
          "60c"),
         "72",
         ("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb6"
          "9da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612"
          "bb0c00")),
        (("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908"
          "025"),
         "af82",
         ("6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac"
          "3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea"
          "1ec40a")),
    )

    def test_the_rfc_vectors_verify(self):
        for public, message, signature in self.VECTORS:
            with self.subTest(message=message or "(empty)"):
                self.assertTrue(ed25519.verify(binascii.unhexlify(public),
                                               binascii.unhexlify(message),
                                               binascii.unhexlify(signature)))

    def test_a_changed_message_does_not(self):
        public, _message, signature = self.VECTORS[1]
        self.assertFalse(ed25519.verify(binascii.unhexlify(public), b"\x73",
                                        binascii.unhexlify(signature)))

    def test_another_key_does_not(self):
        _public, message, signature = self.VECTORS[1]
        other = self.VECTORS[2][0]
        self.assertFalse(ed25519.verify(binascii.unhexlify(other),
                                        binascii.unhexlify(message),
                                        binascii.unhexlify(signature)))

    def test_the_wrong_number_of_bytes_is_refused_rather_than_raising(self):
        """Called on a polling thread, on bytes from a network."""
        key = signer.public_key(SEED)
        good = signer.sign(SEED, b"x")
        for public, signature in ((key, good[:63]), (key, good + b"\x00"),
                                  (key[:31], good), (b"", b""),
                                  (key, b"")):
            with self.subTest(sizes=(len(public), len(signature))):
                self.assertFalse(ed25519.verify(public, b"x", signature))

    def test_a_point_that_is_not_on_the_curve_is_refused(self):
        """A y with no matching x. Repairing it would invent a signer."""
        key = signer.public_key(SEED)
        signature = signer.sign(SEED, b"x")
        self.assertFalse(ed25519.verify(key, b"x", b"\xff" * 32
                                        + signature[32:]))
        self.assertFalse(ed25519.verify(b"\xff" * 32, b"x", signature))

    def test_a_non_canonical_scalar_is_refused(self):
        """S + L verifies under the naive equation and is a second signature
        for a message that already has one."""
        key = signer.public_key(SEED)
        signature = signer.sign(SEED, b"x")
        scalar = int.from_bytes(signature[32:], "little") + ed25519.Q
        self.assertLess(scalar, 1 << 256)
        malleable = signature[:32] + scalar.to_bytes(32, "little")
        self.assertFalse(ed25519.verify(key, b"x", malleable))


class Codes(unittest.TestCase):
    """Eight characters, read out loud and typed in by somebody else."""

    def test_what_was_meant_is_accepted(self):
        for typed in ("K7M29QX4", "k7m2-9qx4", " K7M2 9QX4 ",
                      "k7m2_9qx4", "K7M2-9QX4\t"):
            with self.subTest(typed=typed):
                self.assertEqual(protocol.normalise(typed), "K7M29QX4")

    def test_the_letters_the_alphabet_leaves_out_are_read_as_meant(self):
        self.assertEqual(protocol.normalise("IO7M29QL"), "107M29Q1")
        self.assertEqual(protocol.normalise("U7M29QX4"), "V7M29QX4")

    def test_anything_else_is_a_refusal_not_a_repair(self):
        """Dropping a stray character turns a mistyped code into a
        differently mistyped one, and the operator rereads a correct screen."""
        for typed in ("K7M29QX", "K7M29QX45", "", "K7M29QX!", "K7M29QX\u00c9",
                      None, 12345678):
            with self.subTest(typed=typed):
                self.assertIsNone(protocol.normalise(typed))

    def test_it_is_shown_the_way_it_is_read_out_and_stored_masked(self):
        self.assertEqual(protocol.display("K7M29QX4"), "K7M2-9QX4")
        self.assertEqual(protocol.mask("K7M29QX4"), "K7…X4")
        self.assertEqual(protocol.mask(""), "")


class Checks(PanelTest):
    """Every reason an answer is refused, one at a time."""

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.nonce = b"n" * 32
        self.install = "install-1"
        self.edition = "vip-yatakli"
        self.enterContext(trusting(SEED))

    def check(self, answer, **kwargs):
        fields = {"nonce": self.nonce, "install_id": self.install,
                  "edition": self.edition}
        fields.update(kwargs)
        return protocol.check(answer["payload"], answer["sig"], **fields)

    def answer(self):
        return self.service.grant(verify.encode(self.nonce), self.install)

    def test_a_good_answer_is_a_grant(self):
        grant, reason = self.check(self.answer())
        self.assertEqual(reason, "")
        self.assertEqual(grant.label, "Gaziray")
        self.assertEqual(grant.session, "sess-1")
        self.assertEqual(grant.ttl, 12.0)

    def test_a_key_this_build_does_not_hold_is_untrusted(self):
        """The customer running a server of their own arrives here, and so
        does anybody in the middle. Neither can sign."""
        self.service.seed = OTHER_SEED
        self.assertEqual(self.check(self.answer())[1], "untrusted")

    def test_a_signature_over_another_domain_is_untrusted(self):
        """The prefix is what stops a signature made for something else
        being presented as a grant."""
        self.service.prefix = b"dabp-something-else\x00"
        self.assertEqual(self.check(self.answer())[1], "untrusted")

    def test_yesterdays_answer_does_not_open_todays_door(self):
        """THE REPLAY TEST. Without this the feature is a downloadable file
        and the customer keeps a copy."""
        recorded = self.answer()
        _grant, reason = self.check(recorded)
        self.assertEqual(reason, "")
        self.assertEqual(self.check(recorded, nonce=b"m" * 32)[1], "nonce")

    def test_a_grant_for_another_machine_is_refused(self):
        self.assertEqual(self.check(self.answer(), install_id="other")[1],
                         "install")

    def test_a_grant_for_another_package_is_refused(self):
        self.service.edition = "gdm"
        self.assertEqual(self.check(self.answer())[1], "edition")

    def test_a_grant_for_every_package_is_accepted(self):
        self.service.edition = "*"
        self.assertEqual(self.check(self.answer())[1], "")

    def test_a_version_this_build_does_not_speak_is_refused(self):
        self.service.tamper = {"v": 99}
        self.assertEqual(self.check(self.answer())[1], "version")

    def test_the_ttl_is_capped_whatever_the_service_says(self):
        """A mistake at the service — a unit confused, a default left in —
        must not leave a customer package in admin mode for an afternoon."""
        self.service.tamper = {"ttl": 86400}
        grant, reason = self.check(self.answer())
        self.assertEqual(reason, "")
        self.assertEqual(grant.ttl, protocol.MAX_TTL)

    def test_a_ttl_that_is_not_a_duration_is_refused(self):
        for value in (0, -5, "12", True, None):
            with self.subTest(ttl=value):
                self.service.tamper = {"ttl": value}
                self.assertEqual(self.check(self.answer())[1], "malformed")

    def test_a_body_that_is_not_a_grant_is_refused(self):
        payload = b"not json at all"
        answer = {"payload": verify.encode(payload),
                  "sig": verify.encode(signer.sign(SEED,
                                                   protocol.PREFIX + payload))}
        self.assertEqual(self.check(answer)[1], "malformed")

    def test_rubbish_in_place_of_base64_is_refused(self):
        self.assertEqual(protocol.check("!!!", "!!!", nonce=self.nonce,
                                        install_id=self.install,
                                        edition=self.edition)[1], "malformed")

    def test_the_clock_is_not_consulted(self):
        """A machine that has been off for a month still commissions trains.

        `issuedAt` is carried for the operator's listing and never checked;
        replay is answered by the nonce, and how long a grant lasts is
        measured from when it arrived.
        """
        self.service.tamper = {"issuedAt": 0}
        self.assertEqual(self.check(self.answer())[1], "")
        self.service.tamper = {"issuedAt": 4102444800}
        self.assertEqual(self.check(self.answer())[1], "")


class Client(PanelTest):
    """What the service says, turned into a word the panel knows."""

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))

    def ask(self):
        return client.ask(code="K7M29QX4", nonce=b"n" * 32,
                          install_id="install-1", edition="vip-yatakli",
                          app_version="1.0.5")

    def test_the_question_carries_the_nonce_and_nothing_secret(self):
        self.ask()
        sent = self.service.calls[0]
        self.assertTrue(sent["url"].endswith("/v1/grant"))
        self.assertEqual(sent["body"]["code"], "K7M29QX4")
        self.assertEqual(verify.decode(sent["body"]["nonce"]), b"n" * 32)
        self.assertEqual(sent["timeout"],
                         (client.CONNECT_TIMEOUT, client.READ_TIMEOUT))

    def test_a_definite_no_keeps_its_own_word(self):
        for status, reason in client.REFUSALS.items():
            with self.subTest(status=status):
                self.service.status = status
                with self.assertRaises(client.ServiceError) as caught:
                    self.ask()
                self.assertEqual(caught.exception.reason, reason)

    def test_two_refusals_share_a_status_and_are_told_apart(self):
        """A session opened for another package and a session opened by QR
        for another machine are both 403, and they are not the same sentence.
        The word in the body chooses between the panel's OWN reasons; it is
        still never shown to anybody."""
        self.service.status = 403
        self.assertEqual(self.refused().reason, "editionNotAllowed")
        self.service.word = "notThisMachine"
        self.assertEqual(self.refused().reason, "notThisMachine")

    def refused(self):
        with self.assertRaises(client.ServiceError) as caught:
            self.ask()
        return caught.exception

    def test_a_network_that_is_not_there_is_offline(self):
        import requests
        self.service.error = requests.ConnectionError("no route")
        with self.assertRaises(client.ServiceError) as caught:
            self.ask()
        self.assertEqual(caught.exception.reason, "offline")

    def test_anything_else_is_a_service_fault(self):
        self.service.status = 500
        with self.assertRaises(client.ServiceError) as caught:
            self.ask()
        self.assertEqual(caught.exception.reason, "service")

    def test_a_body_too_large_to_be_a_grant_is_not_parsed(self):
        big = Answer(200, {"payload": "x", "sig": "y"},
                     raw=b"x" * (client.MAX_BODY + 1))
        with mock.patch.object(self.service, "post", return_value=big):
            with self.assertRaises(client.ServiceError) as caught:
                self.ask()
        self.assertEqual(caught.exception.reason, "service")

    def test_the_environment_may_point_a_source_run_elsewhere(self):
        """Development against a Worker of one's own. A frozen build takes
        the service it was built with and nothing may add to it."""
        with mock.patch.dict(os.environ,
                             {verify.URL_ENV: "https://elsewhere.test"}):
            self.assertEqual(verify.service_url(), "https://elsewhere.test")
            with mock.patch.object(verify.settings, "FROZEN", True):
                self.assertEqual(verify.service_url(), verify.SERVICE_URL)


class Sessions(PanelTest):
    """Connecting, staying connected, and the door closing on its own."""

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.watch = remotekey.WATCH
        self.addCleanup(self.watch.reset)
        # The thread would beat against the fake service on real seconds
        # while the clock this test moves is a fake one. Every round below is
        # driven directly, which is also the only way to say WHEN it happens.
        self.enterContext(mock.patch.object(self.watch, "_run",
                                            lambda: None))

    def test_a_code_that_checks_out_holds_the_door(self):
        self.assertEqual(self.watch.connect("k7m2-9qx4"), "")
        self.assertTrue(self.watch.live())
        self.assertEqual(self.watch.snapshot()["label"], "Gaziray")
        self.assertIn(authority.REMOTE, authority.holding())

    def test_a_code_of_the_wrong_shape_never_reaches_the_service(self):
        self.assertEqual(self.watch.connect("nope"), "badCode")
        self.assertEqual(self.service.calls, [])

    def test_a_build_with_no_public_key_offers_nothing(self):
        with mock.patch.object(verify, "TRUSTED_KEYS", ()):
            self.assertFalse(verify.available())
            self.assertEqual(self.watch.connect("K7M29QX4"), "unavailable")
        self.assertEqual(self.service.calls, [])

    def test_the_service_saying_no_is_reported_and_nothing_is_held(self):
        self.service.status = 404
        self.assertEqual(self.watch.connect("K7M29QX4"), "unknownCode")
        self.assertFalse(self.watch.live())
        self.assertNotIn(authority.REMOTE, authority.holding())

    def test_the_door_closes_when_nothing_renews_the_grant(self):
        """No disconnection is detected. The deadline simply arrives."""
        self.watch.connect("K7M29QX4")
        self.clock.sleep(self.service.ttl - 1)
        self.assertTrue(self.watch.live())
        self.clock.sleep(2)
        self.assertFalse(self.watch.live())
        self.assertFalse(self.watch.snapshot()["active"])

    def test_each_answer_pushes_the_deadline_out(self):
        self.watch.connect("K7M29QX4")
        for _ in range(5):
            self.clock.sleep(4)
            self.assertEqual(self.watch._round(), "")
            self.assertTrue(self.watch.live())

    def test_silence_is_ridden_out_to_the_deadline_and_no_further(self):
        """A laptop between two access points must not cost the session."""
        import requests
        self.watch.connect("K7M29QX4")
        self.service.error = requests.ConnectionError("gone")
        self.clock.sleep(4)
        self.assertEqual(self.watch._round(), "offline")
        self.assertTrue(self.watch.live())          # still inside the ttl
        self.assertEqual(self.watch.snapshot()["reason"], "offline")
        self.clock.sleep(10)
        self.assertFalse(self.watch.live())

    def test_a_closed_link_is_felt_at_once_rather_than_waited_out(self):
        self.watch.connect("K7M29QX4")
        self.service.status = 410
        self.assertEqual(self.watch._round(), "closed")
        # The reason is fatal, so the beat gives up rather than sitting out
        # the remaining ten seconds of a grant nobody will renew.
        self.assertIn("closed", remotekey.watcher.FATAL)
        self.assertEqual(self.watch.snapshot()["reason"], "closed")

    def test_an_answer_that_does_not_verify_is_fatal_too(self):
        """Waiting to see whether the NEXT one verifies is waiting for an
        attacker to get it right."""
        self.watch.connect("K7M29QX4")
        self.service.seed = OTHER_SEED
        self.assertEqual(self.watch._round(), "untrusted")
        self.assertIn("untrusted", remotekey.watcher.FATAL)

    def test_a_stale_deadline_is_noticed_when_the_window_asks(self):
        """The beat is four seconds; a grant can run out between two of
        them, and the window must not be told "active" meanwhile."""
        self.watch.connect("K7M29QX4")
        self.clock.sleep(self.service.ttl + 1)
        self.assertFalse(self.watch.fresh()["active"])

    def test_disconnecting_gives_up_the_session(self):
        self.watch.connect("K7M29QX4")
        self.watch.disconnect()
        self.assertFalse(self.watch.live())
        self.assertEqual(self.watch.snapshot()["codeMasked"], "")
        self.assertNotIn(authority.REMOTE, authority.holding())

    def test_the_beat_leaves_room_for_a_lost_answer(self):
        """The deadline is what holds the door, so the question has to be
        asked well before it arrives — a third of the ttl, which is two
        answers' worth of slack. A beat that crept up on the deadline would
        end admin mode between two questions with nothing wrong."""
        for ttl in (1, 4, 12, 30, 45, 90, protocol.MAX_TTL):
            with self.subTest(ttl=ttl):
                beat = watcher.beat_for(ttl)
                self.assertGreaterEqual(beat, watcher.BEAT_MIN)
                self.assertLessEqual(beat, watcher.BEAT_MAX)
                # Below the floor the panel refuses to ask any faster, and a
                # grant that short is shorter than it would ever be issued.
                if ttl >= watcher.BEAT_MIN * 3:
                    self.assertLessEqual(beat * 3, ttl)

    def test_a_grant_with_no_ttl_yet_beats_at_the_floor(self):
        """Before the first answer there is nothing to derive from."""
        for nothing in (0, 0.0, -1):
            self.assertEqual(watcher.beat_for(nothing), watcher.BEAT_MIN)

    def test_the_ceiling_on_the_ttl_is_the_ceiling_on_the_beat(self):
        """These two constants are one decision written in two files.

        The panel caps the ttl it will honour; the beat is a third of the
        ttl. So `MAX_TTL` is also what decides how rarely the panel is ABLE
        to ask, and a ceiling lower than three beats would make `BEAT_MAX`
        a number that can never be reached — which is worse than a wrong
        number, because nothing on either side would say so.
        """
        self.assertGreaterEqual(protocol.MAX_TTL, watcher.BEAT_MAX * 3)

    def test_the_beat_follows_the_grant_that_arrived(self):
        """A service that starts issuing longer grants is asked less often
        without anything here being changed."""
        self.service.ttl = 90.0
        self.watch.connect("K7M29QX4")
        self.assertEqual(watcher.beat_for(self.watch._ttl), watcher.BEAT_MAX)

    def test_the_session_is_handed_back_rather_than_left_to_run_out(self):
        """A session nobody is in is a machine slot and a line on the
        operator's list that mean nothing — and with a QR session, which is
        minted for one machine, they mean nothing to anybody ever again."""
        self.watch.connect("K7M29QX4")
        self.watch.disconnect()
        self.watch.reset()                  # waits for the hand-back to go
        given = [call for call in self.service.calls
                 if call["url"].endswith("/v1/release")]
        self.assertEqual(len(given), 1)
        self.assertEqual(given[0]["body"]["code"], "K7M29QX4")
        self.assertEqual(given[0]["body"]["installId"], session.install_id())

    def test_a_session_that_ran_out_is_not_handed_back(self):
        """There is nothing to hand back: it ended at the service's end, and
        a request saying so would be a round trip that changes nothing."""
        self.watch.connect("K7M29QX4")
        self.service.status = 410
        self.watch._round()
        self.watch._lapse("closed")
        self.watch.reset()
        self.assertEqual([call for call in self.service.calls
                          if call["url"].endswith("/v1/release")], [])

    def test_the_state_the_window_polls_carries_no_way_in(self):
        """Whatever is polled once a second must be worthless to steal."""
        self.watch.connect("K7M29QX4")
        text = json.dumps(self.watch.snapshot())
        self.assertNotIn("K7M29QX4", text)
        self.assertNotIn(self.service.calls[0]["body"]["nonce"], text)
        self.assertNotIn("sig", text)
        self.assertNotIn("payload", text)

    def test_the_installation_names_itself_once_and_keeps_the_name(self):
        first = session.install_id()
        session.forget()
        self.assertEqual(session.install_id(), first)
        self.assertIn("-", first)               # a uuid4, not a counter


class Arbitration(PanelTest):
    """Two ways in, one mode. Neither may take back the other's.

    This is what the feature could have broken rather than what it adds. The
    service key's watcher used to end admin mode on its own — no stick, no
    admin — and left alone it would have taken back every remote session
    within two seconds of it opening.
    """

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.watch = remotekey.WATCH
        self.addCleanup(self.watch.reset)
        self.enterContext(mock.patch.object(self.watch, "_run",
                                            lambda: None))
        # A customer package: no build secret, so admin mode is something
        # that has to be granted rather than something the run opens with.
        self.enterContext(mock.patch.object(editions, "opens_as_admin",
                                            return_value=False))

    def test_the_key_watcher_does_not_take_back_a_remote_session(self):
        """THE REGRESSION THIS MODULE EXISTS FOR."""
        self.watch.connect("K7M29QX4")
        editions.set_admin(True)
        for _ in range(3):
            key_watcher.WATCH.observe()      # no stick in the machine
        self.assertEqual(editions.mode(), "admin")

    def test_a_remote_session_ending_leaves_a_stick_holding_the_door(self):
        editions.set_admin(True)
        self.watch.connect("K7M29QX4")
        authority.report(authority.KEY, True)
        self.watch.disconnect()
        authority.settle()
        self.assertEqual(editions.mode(), "admin")

    def test_the_mode_ends_when_the_last_source_goes(self):
        self.watch.connect("K7M29QX4")
        editions.set_admin(True)
        authority.report(authority.KEY, False)
        self.watch.disconnect()
        authority.settle()
        self.assertEqual(editions.mode(), "field")

    def test_a_write_in_progress_defers_the_drop(self):
        """An IP run half finished is worse than a door open a few minutes
        longer. The badge says so meanwhile."""
        editions.set_admin(True)
        authority.report(authority.REMOTE, True)
        with mock.patch.object(authority, "_writing", return_value=True):
            authority.report(authority.REMOTE, False)
            authority.settle()
            self.assertEqual(editions.mode(), "admin")
            self.assertTrue(authority.revoke_pending())
            # And the key watcher reports the same fact, because it is one
            # fact about one mode.
            self.assertTrue(
                key_watcher.WATCH.snapshot()["revokePending"])
        authority.settle()
        self.assertEqual(editions.mode(), "field")
        self.assertFalse(authority.revoke_pending())

    def test_a_run_holding_the_build_secret_is_left_alone(self):
        """It opened as admin with no source at all, so no source going away
        takes anything with it."""
        with mock.patch.object(editions, "opens_as_admin", return_value=True):
            editions.set_admin(True)
            authority.report(authority.KEY, False)
            authority.report(authority.REMOTE, False)
            authority.settle()
            self.assertEqual(editions.mode(), "admin")

    def test_the_arbiter_can_close_a_door_and_never_open_one(self):
        """Reporting a source live keeps a mode that was already granted; it
        cannot start one. Entering is earned where the evidence can be
        checked, so that a reporting bug is never an escalation."""
        editions.set_admin(False)
        authority.report(authority.REMOTE, True)
        authority.report(authority.KEY, True)
        authority.settle()
        self.assertEqual(editions.mode(), "field")


class Endpoints(PanelTest):
    """What the API offers, and to whom."""

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.addCleanup(remotekey.WATCH.reset)
        self.enterContext(mock.patch.object(remotekey.WATCH, "_run",
                                            lambda: None))
        self.enterContext(mock.patch.object(editions, "opens_as_admin",
                                            return_value=False))

    def test_connecting_is_reachable_from_field_mode(self):
        """It has to be: a package that could not ASK to connect could never
        use the feature at all. What keeps anybody out is the signature."""
        editions.set_admin(False)
        response = api.call("POST", "/api/admin/remote/connect",
                            body={"code": "K7M2-9QX4"})
        self.assertEqual(response.status, 200)
        self.assertEqual(editions.mode(), "admin")
        self.assertTrue(response.body["remote"]["active"])
        self.assertIn("adb", response.body["views"])

    def test_reading_the_state_is_open_and_says_nothing(self):
        editions.set_admin(False)
        body = api.call("GET", "/api/admin/remote").body
        self.assertEqual(body["active"], False)
        self.assertEqual(body["codeMasked"], "")

    def test_disconnecting_gives_up_the_mode(self):
        api.call("POST", "/api/admin/remote/connect",
                 body={"code": "K7M29QX4"})
        response = api.call("POST", "/api/admin/remote/disconnect", body={})
        self.assertEqual(response.status, 200)
        self.assertEqual(editions.mode(), "field")

    def test_a_refusal_is_a_status_and_a_sentence_of_ours(self):
        """Never the service's own words: what comes back over the network
        is a fixed vocabulary, and the text is the panel's."""
        for status, expected in ((404, 404), (410, 410), (403, 403),
                                 (429, 429)):
            with self.subTest(status=status):
                self.service.status = status
                response = api.call("POST", "/api/admin/remote/connect",
                                    body={"code": "K7M29QX4"})
                self.assertEqual(response.status, expected)
                self.assertIn("error", response.body)
                self.assertNotIn("no", response.body["error"].split())
                self.assertEqual(editions.mode(), "field")

    def test_a_mistyped_code_is_a_bad_request(self):
        response = api.call("POST", "/api/admin/remote/connect",
                            body={"code": "nope"})
        self.assertEqual(response.status, 400)
        self.assertEqual(response.body["reason"], "badCode")

    def test_an_unreachable_service_says_so(self):
        import requests
        self.service.error = requests.ConnectionError("no route")
        response = api.call("POST", "/api/admin/remote/connect",
                            body={"code": "K7M29QX4"})
        self.assertEqual(response.status, 503)

    def test_the_package_says_whether_it_can_check_a_grant_at_all(self):
        self.assertTrue(api.call("GET", "/api/edition").body["remoteAvailable"])
        with mock.patch.object(verify, "TRUSTED_KEYS", ()):
            body = api.call("GET", "/api/edition").body
            self.assertFalse(body["remoteAvailable"])

    def test_the_state_reports_why_a_session_ended(self):
        api.call("POST", "/api/admin/remote/connect",
                 body={"code": "K7M29QX4"})
        self.service.status = 410
        remotekey.WATCH._round()
        body = api.call("GET", "/api/admin/remote").body
        self.assertEqual(body["reason"], "closed")
        self.assertTrue(body["reasonText"])
        self.assertNotEqual(body["reasonText"], "closed")


class Squares(PanelTest):
    """The square on the screen: what is drawn, and what is refused.

    The pairing is the QR half of the same door. It carries a second secret
    — the key that reads the issued code back — and the whole arrangement
    rests on that key never being anywhere the square is.
    """

    def setUp(self):
        super().setUp()
        self.service = FakePairing()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.pair = remotekey.PAIR
        self.addCleanup(self.pair.reset)

    def start(self) -> str:
        return self.pair.start(install_id="install-1", edition="vip-yatakli",
                               app_version="1.0.5", hint="Ankara Gar")

    def test_the_square_is_drawn_from_what_the_service_sent(self):
        self.assertEqual(self.start(), "")
        seen = self.pair.snapshot()
        self.assertEqual(seen["state"], "pending")
        self.assertEqual(seen["pairId"], self.service.pair_id)
        self.assertTrue(seen["image"].startswith("data:image/svg+xml;base64,"))
        drawn = base64.b64decode(seen["image"].split(",", 1)[1])
        self.assertEqual(drawn.decode("utf-8"), FakePairing.QR)
        # Read off the drawing, so the window can size it to whole pixels
        # per module rather than guess — and so it knows how much of the
        # white is margin it may crop and how much is code it may not.
        self.assertEqual(seen["modules"], 41)
        self.assertEqual(seen["quiet"], 4)

    def test_the_key_that_reads_the_code_back_never_leaves_the_process(self):
        """Everything else about a pairing is on the screen already and can
        be photographed off it. This cannot, and it is the only thing that
        can collect the answer."""
        self.start()
        self.assertNotIn(self.service.poll_key,
                         json.dumps(self.pair.snapshot()))

    def test_an_address_that_is_not_the_service_is_refused(self):
        """The square sends a phone somewhere, and where it goes is the page
        that will ask an engineer for the operator token — the one secret
        here that opens sessions on any machine. So it is compared with the
        address this build was compiled with rather than taken on trust."""
        self.service.url = "https://elsewhere.test/p/JYB6QBC7WWB7"
        self.assertEqual(self.start(), "service")
        self.assertEqual(self.pair.snapshot()["image"], "")

    def test_a_drawing_that_is_not_a_drawing_is_refused(self):
        for qr in ('<svg onload="x()"><script>alert(1)</script></svg>',
                   '<svg><foreignObject><b>hi</b></foreignObject></svg>',
                   "<html><body>not a square</body></html>",
                   "x" * (pairing.MAX_IMAGE + 1),
                   # Nothing to measure, and nothing that could be a QR code:
                   # without the module count the window cannot draw it at a
                   # whole number of pixels per module.
                   '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                   '<svg viewBox="0 0 41 60"><rect/></svg>',
                   '<svg viewBox="0 0 4 4"><rect/></svg>',
                   # Nothing drawn, and a margin that is most of the
                   # picture: neither is a code, and the window would be
                   # cropping something it cannot see.
                   '<svg viewBox="0 0 41 41"><rect/></svg>',
                   ('<svg viewBox="0 0 41 41">'
                    '<path d="M20 20h1v1h-1z"/></svg>')):
            with self.subTest(qr=qr[:30]):
                self.service.qr = qr
                self.assertEqual(self.start(), "service")

    def test_a_pairing_id_of_the_wrong_shape_is_refused(self):
        for bad in ("", "SHORT", "IOU6QBC7WWB7", "JYB6QBC7WWB7X"):
            with self.subTest(id=bad):
                self.service.pair_id = bad
                self.assertEqual(self.start(), "service")

    def test_an_approval_hands_the_code_over_and_keeps_no_copy(self):
        self.assertEqual(self.start(), "")
        self.assertEqual(self.pair.poll(), ("pending", ""))
        self.service.state = "approved"
        self.assertEqual(self.pair.poll(), ("approved", "K7M29QX4"))
        self.assertNotIn("K7M29QX4", json.dumps(self.pair.snapshot()))

    def test_a_settled_pairing_is_forgotten_and_not_cancelled_after(self):
        """Denied, expired, cancelled or closed: there is nothing left to
        ask about, and nothing left to take back either. Cancelling an
        approved pairing CLOSES the session behind it, so a dialog closing
        after the fact must have nothing to cancel."""
        self.start()
        self.service.state = "denied"
        self.assertEqual(self.pair.poll(), ("denied", ""))
        self.assertEqual(self.pair.snapshot()["pairId"], "")
        before = len(self.service.calls)
        self.pair.cancel()
        self.assertEqual(len(self.service.calls), before)
        # And a window still holding the square reads the one sentence there
        # is to read about it, rather than "the service made no sense".
        self.assertEqual(self.pair.poll(), ("pairLost", ""))
        self.assertEqual(len(self.service.calls), before)

    def test_a_pairing_the_service_has_lost_ends_the_square(self):
        """An unknown pairing and a wrong key are one answer here: the square
        on the screen is attached to nothing, and the only thing to do about
        either is draw another."""
        for status in (404, 403):
            with self.subTest(status=status):
                self.start()
                self.service.status["/v1/pair/poll"] = status
                self.assertEqual(self.pair.poll(), ("pairLost", ""))
                self.assertEqual(self.pair.snapshot()["pairId"], "")
                self.service.status.clear()

    def test_asking_again_gives_the_first_square_up(self):
        self.start()
        self.start()
        self.assertEqual(self.service.paths(),
                         ["/v1/pair", "/v1/pair/cancel", "/v1/pair"])

    def test_a_build_with_no_public_key_draws_nothing(self):
        with mock.patch.object(verify, "TRUSTED_KEYS", ()):
            self.assertEqual(self.start(), "unavailable")
        self.assertEqual(self.service.calls, [])

    def test_how_often_the_window_asks_is_not_the_services_to_decide(self):
        """A number off the network deciding how hard this machine works."""
        for said, expected in ((0, pairing.MIN_POLL), (-5, pairing.MIN_POLL),
                               ("soon", pairing.DEFAULT_POLL),
                               (9000, pairing.MAX_POLL), (3, 3.0)):
            with self.subTest(said=said):
                self.assertEqual(pairing._beat(said), expected)


class SquareEndpoints(PanelTest):
    """The pairing over the API: open to ask, and granting on a signature."""

    def setUp(self):
        super().setUp()
        self.service = FakePairing()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.addCleanup(remotekey.WATCH.reset)
        self.addCleanup(remotekey.PAIR.reset)
        self.enterContext(mock.patch.object(remotekey.WATCH, "_run",
                                            lambda: None))
        self.enterContext(mock.patch.object(editions, "opens_as_admin",
                                            return_value=False))
        editions.set_admin(False)

    def ask(self):
        return api.call("POST", "/api/admin/remote/pair", body={})

    def poll(self):
        return api.call("POST", "/api/admin/remote/pair/poll", body={})

    def test_a_field_package_may_ask_for_a_square(self):
        """For the reason connecting is open: a package that could not ASK
        could never be helped."""
        response = self.ask()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["pair"]["state"], "pending")
        self.assertNotIn(self.service.poll_key, json.dumps(response.body))
        self.assertEqual(editions.mode(), "field")

    def test_the_request_says_which_machine_and_whose(self):
        """What the person holding the phone is being asked is "is this the
        machine you are on the telephone about?"."""
        self.ask()
        sent = self.service.calls[0]["body"]
        self.assertEqual(sent["installId"], session.install_id())
        self.assertEqual(sent["hint"], editions.active().product_name)
        self.assertEqual(sent["edition"], editions.active().id)

    def test_an_approval_enters_admin_mode_and_spends_the_pairing(self):
        self.ask()
        waiting = self.poll()
        self.assertEqual(waiting.body["pair"]["state"], "pending")
        self.assertEqual(editions.mode(), "field")

        self.service.state = "approved"
        response = self.poll()
        self.assertEqual(response.status, 200)
        self.assertEqual(editions.mode(), "admin")
        self.assertTrue(response.body["remote"]["active"])
        self.assertIn("adb", response.body["views"])
        # The key that could read the code back does not outlive the answer.
        self.assertEqual(response.body["pair"]["pairId"], "")

    def test_the_approval_is_not_the_permission(self):
        """Somebody approving says a session exists. It does not say this
        panel may be in admin mode — that is still the signature's answer,
        and it is asked on the same round."""
        self.ask()
        self.service.state = "approved"
        self.service.grants.seed = OTHER_SEED
        response = self.poll()
        self.assertEqual(response.status, 502)
        self.assertEqual(response.body["reason"], "untrusted")
        self.assertEqual(editions.mode(), "field")
        self.assertEqual(response.body["pair"]["pairId"], "")

    def test_a_refusal_is_a_status_and_a_sentence_of_ours(self):
        self.ask()
        self.service.state = "denied"
        response = self.poll()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["pair"]["state"], "denied")
        self.assertTrue(response.body["stateText"])
        self.assertNotEqual(response.body["stateText"], "denied")
        self.assertEqual(editions.mode(), "field")

    def test_closing_the_dialog_gives_the_square_back(self):
        self.ask()
        response = api.call("POST", "/api/admin/remote/pair/cancel", body={})
        self.assertEqual(response.status, 200)
        self.assertIn("/v1/pair/cancel", self.service.paths())
        self.assertEqual(response.body["pair"]["pairId"], "")

    def test_a_service_that_is_not_there_says_so(self):
        import requests
        self.service.grants.error = requests.ConnectionError("no route")
        with mock.patch.object(self.service, "post",
                               side_effect=requests.ConnectionError("no")):
            response = self.ask()
        self.assertEqual(response.status, 503)
        self.assertEqual(response.body["reason"], "offline")


class AccountDoor(PanelTest):
    """What both account paths need: a service, a build that trusts it, and
    a panel that is not already in admin mode."""

    def setUp(self):
        super().setUp()
        self.service = FakeService()
        self.enterContext(trusting(SEED))
        self.enterContext(serving(self.service))
        self.addCleanup(remotekey.WATCH.reset)
        self.enterContext(mock.patch.object(remotekey.WATCH, "_run",
                                            lambda: None))
        self.enterContext(mock.patch.object(editions, "opens_as_admin",
                                            return_value=False))
        editions.set_admin(False)

    def sent(self, path: str) -> dict:
        for call in self.service.calls:
            if call["url"].endswith(path):
                return call["body"]
        raise AssertionError(f"{path} was never asked")

    def asked(self) -> list[str]:
        return [call["url"].rsplit("/", 1)[-1] for call in self.service.calls]


class SigningIn(AccountDoor):
    """The third door: an account, and a session bound to this machine.

    Nobody dictates anything and nobody has to be awake to approve it — the
    engineer standing at the panel proves who they are. What the tests hold
    to is that this changes WHO ASKS and nothing else: the session that comes
    back is checked exactly as a dictated one is, and the password the
    question was asked with is gone the moment it has been asked.
    """

    def sign_in(self, email="ali@piton.com.tr", password="a-secret"):
        return api.call("POST", "/api/admin/remote/signin",
                        body={"email": email, "password": password})

    def test_an_account_opens_a_session_and_enters_admin_mode(self):
        """Reachable from field mode, for the reason connecting is: a
        package that could not ASK could never use the feature."""
        response = self.sign_in()
        self.assertEqual(response.status, 200)
        self.assertEqual(editions.mode(), "admin")
        self.assertTrue(response.body["remote"]["active"])
        self.assertIn("adb", response.body["views"])

    def test_the_request_says_which_machine_and_whose(self):
        self.sign_in()
        body = self.sent("/v1/signin")
        self.assertEqual(body["installId"], session.install_id())
        self.assertEqual(body["edition"], editions.active().id)
        self.assertEqual(body["hint"], editions.active().product_name)

    def test_the_password_travels_once_and_is_kept_nowhere(self):
        self.sign_in(password="a-secret")
        carrying = [call for call in self.service.calls
                    if "password" in (call["body"] or {})]
        self.assertEqual(len(carrying), 1)
        self.assertNotIn("a-secret", json.dumps(remotekey.WATCH.snapshot()))
        self.assertNotIn("a-secret",
                         json.dumps(api.call("GET", "/api/admin/remote").body))

    def test_the_address_is_folded_before_it_is_sent(self):
        self.sign_in(email="  Ali@Piton.com.TR ")
        self.assertEqual(self.sent("/v1/signin")["email"], "ali@piton.com.tr")

    def test_an_empty_field_is_refused_without_asking_the_service(self):
        """An empty field is a wrong credential by inspection, and asking
        would spend one of the attempts the account is locked out after."""
        for email, password in (("", "a-secret"), ("ali@piton.com.tr", ""),
                                ("x" * 121 + "@piton.com.tr", "a-secret")):
            with self.subTest(email=email[:8]):
                response = self.sign_in(email=email, password=password)
                self.assertEqual(response.status, 401)
                self.assertEqual(response.body["reason"], "badCredentials")
                self.assertEqual(self.service.calls, [])
                self.assertEqual(editions.mode(), "field")

    def test_one_status_can_mean_two_things_and_the_word_decides(self):
        """A 403 is an account without the permission or an account switched
        off; a 429 is a lockout or an address asking too often. Four
        different things to do next, so four different sentences."""
        for status, word, reason in ((401, "badCredentials", "badCredentials"),
                                     (403, "noPermission", "noPermission"),
                                     (403, "disabled", "accountDisabled"),
                                     (429, "locked", "locked"),
                                     (429, "busy", "busy"),
                                     (503, "notConfigured", "notConfigured")):
            with self.subTest(word=word):
                self.service.status = status
                self.service.word = word
                response = self.sign_in()
                self.assertEqual(response.status, status)
                self.assertEqual(response.body["reason"], reason)
                self.assertEqual(editions.mode(), "field")
                # The service's own words are never what is read on screen.
                self.assertNotIn(word, response.body["error"])

    def test_a_lockout_says_how_long_rather_than_later(self):
        self.service.status = 429
        self.service.word = "locked"
        self.service.retry = 40
        response = self.sign_in()
        self.assertEqual(response.status, 429)
        self.assertEqual(response.body["retry"], 40)
        self.assertIn("40", response.body["error"])

    def test_a_wait_that_is_not_a_wait_is_not_reported(self):
        """A number off a socket decides what a screen says."""
        for value in (-1, 0, 99999, "soon", None):
            with self.subTest(value=value):
                self.service.status = 429
                self.service.word = "locked"
                self.service.retry = value
                response = self.sign_in()
                self.assertEqual(response.status, 429)
                self.assertNotIn("retry", response.body)

    def test_signing_in_is_not_the_permission(self):
        """Proving who you are says a session exists. It does not say this
        panel may be in admin mode — that is still the signature's answer,
        and it is asked on the same round."""
        self.service.seed = OTHER_SEED
        response = self.sign_in()
        self.assertEqual(response.status, 502)
        self.assertEqual(response.body["reason"], "untrusted")
        self.assertEqual(editions.mode(), "field")

    def test_an_answer_without_a_usable_code_is_not_an_answer(self):
        self.service.code = "no"
        response = self.sign_in()
        self.assertEqual(response.status, 502)
        self.assertEqual(response.body["reason"], "service")
        self.assertEqual(editions.mode(), "field")

    def test_a_build_that_cannot_check_a_grant_does_not_offer_the_door(self):
        with mock.patch.object(verify, "TRUSTED_KEYS", ()):
            response = self.sign_in()
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["reason"], "unavailable")
        self.assertEqual(self.service.calls, [])


class AskingForAnAccount(AccountDoor):
    """Anybody holding the application may make an account; only an admin
    may make one work.

    That split is the whole feature, and the panel's half of it is small: ask
    the service, and report what came back. WHAT MUST NOT HAPPEN HERE is a
    mode, a session or a code — a door that made accounts AND let them in
    would be a door that lets anybody in.
    """

    def sign_up(self, email="new@piton.com.tr", password="a-long-enough-secret",
                name="New Person"):
        return api.call("POST", "/api/admin/remote/signup",
                        body={"email": email, "password": password,
                              "name": name})

    def test_making_an_account_grants_nothing_at_all(self):
        response = self.sign_up()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, {"waiting": True})
        self.assertEqual(editions.mode(), "field")
        self.assertFalse(remotekey.WATCH.snapshot()["active"])
        # And it did not quietly go on to open one either: one request, to
        # one path, and no grant round behind it.
        self.assertEqual(self.asked(), ["signup"])

    def test_the_request_carries_the_machine_and_the_folded_address(self):
        self.sign_up(email="  New@Piton.com.TR ", name="  New Person  ")
        body = self.sent("/v1/signup")
        self.assertEqual(body["email"], "new@piton.com.tr")
        self.assertEqual(body["name"], "New Person")
        self.assertEqual(body["installId"], session.install_id())

    def test_the_password_travels_once_and_is_kept_nowhere(self):
        self.sign_up(password="a-long-enough-secret")
        carrying = [call for call in self.service.calls
                    if "password" in (call["body"] or {})]
        self.assertEqual(len(carrying), 1)
        self.assertNotIn("a-long-enough-secret",
                         json.dumps(remotekey.WATCH.snapshot()))

    def test_an_empty_field_says_which_field(self):
        """Two boxes on the screen, so one sentence for both would leave the
        reader looking for the one it meant."""
        for email, password, reason in (
                ("", "a-long-enough-secret", "badEmail"),
                ("x" * 121 + "@piton.com.tr", "a-long-enough-secret", "badEmail"),
                ("new@piton.com.tr", "", "passwordShort")):
            with self.subTest(reason=reason):
                response = self.sign_up(email=email, password=password)
                self.assertEqual(response.status, 400)
                self.assertEqual(response.body["reason"], reason)
                self.assertEqual(self.service.calls, [])

    def test_the_services_complaint_chooses_which_sentence(self):
        """A 400 is four different corrections in four different boxes, so
        unlike everywhere else here it is not one word."""
        for status, word in ((400, "badEmail"), (400, "passwordShort"),
                             (400, "passwordLong"), (400, "passwordObvious"),
                             (409, "emailTaken"), (429, "busy"),
                             (503, "notConfigured")):
            with self.subTest(word=word):
                self.service.status = status
                self.service.word = word
                response = self.sign_up()
                self.assertEqual(response.status, status)
                self.assertEqual(response.body["reason"], word)
                self.assertNotIn(word, response.body["error"])
                self.assertEqual(editions.mode(), "field")

    def test_a_400_the_service_did_not_explain_is_not_guessed_at(self):
        self.service.status = 400
        self.service.word = "somethingNew"
        response = self.sign_up()
        self.assertEqual(response.status, 502)
        self.assertEqual(response.body["reason"], "service")

    def test_a_build_that_cannot_check_a_grant_does_not_offer_the_door(self):
        """An account is only worth having where a session can be checked."""
        with mock.patch.object(verify, "TRUSTED_KEYS", ()):
            response = self.sign_up()
        self.assertEqual(response.status, 409)
        self.assertEqual(response.body["reason"], "unavailable")
        self.assertEqual(self.service.calls, [])


if __name__ == "__main__":
    unittest.main()
