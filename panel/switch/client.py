#!/usr/bin/env python3
"""The panel's KYLAND switch client. There is not a second one.

Every switch read and write in this application goes through one instance of
this class (`panel.switch.CLIENT`): the IP assignment screen's front panel,
the factory reset check, and the switch screen itself. That is not tidiness —
two clients means two ideas of what a timeout is and two ideas of when a reply
counts as "you must sign in", and the day they disagree an account that works
on one screen reports "unverified" on the other.

CREDENTIALS ARE ALWAYS PASSED IN. This class holds none and consults no store.
The panel's passwords live in `panel.credentials`, in memory, and the caller
that has one hands it over per call. A client that could reach for a password
by itself is a client that can use the wrong one.

What it does hold is worth sharing and pointless to duplicate: a pooled
proxy-free session, one write lock per switch address, and the gate that keeps
two scans from running at once.
"""
from __future__ import annotations

import threading
from concurrent import futures

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth

from .. import i18n, settings
from ..errors import AuthError, VerificationError, classify
from .discovery import (HTTP_FALLBACK_LIMIT, TCP_PROBE_TIMEOUT,
                        resolve_addresses, tcp_open)


def create_session(pool_size: int = 64) -> requests.Session:
    """A pooled session for local switch traffic.

    `trust_env = False` is the important line: a switch on 10.1.1.x is on the
    cable in front of the operator, and sending its traffic through whatever
    HTTP_PROXY the machine happens to have set makes every device on the train
    unreachable for a reason nothing on screen can explain.

    `max_retries=0` because a scan already knows how to move on. Retrying a
    dead address three times turns a two-minute sweep into six.
    """
    session = requests.Session()
    session.trust_env = False
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size,
                          max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# WHAT COUNTS AS "SIGN IN FIRST", and it is not "the reply was not JSON".
#
# Two model families say it two different ways: the Aquam boxes answer 401
# with `WWW-Authenticate: Basic realm="KYLAND"`, and the SICOM boxes answer
# 200 with their own login page in text/html. The second one used to be read
# as "anything that did not parse as JSON", which is a much wider net than it
# looks: every web server on the network that answers an unknown path with a
# page instead of a 404 fell into it. A PISCU at 10.1.1.1 was listed as a
# switch waiting for a password, and the operator was asked to sign in to it.
#
# So the page has to look like a page you can sign in ON: it must offer a box
# to type a name or a password into. A device that merely serves HTML is not
# a locked switch, it is not a switch at all, and it is dropped from the scan.
_LOGIN_FIELDS = ("type=password", "name=password", "name=passwd",
                 "name=pwd", "name=user", "name=username", "name=login")


def looks_like_login_page(body: str) -> bool:
    """Is this HTML a switch asking to be signed in to, or just a web page?"""
    # Quotes and spacing differ between firmwares; neither is worth matching.
    compact = "".join(body.lower().split()).replace('"', "").replace("'", "")
    if "<input" not in compact:
        return False
    return any(field in compact for field in _LOGIN_FIELDS)


def looks_like_switch(info: dict) -> bool:
    """Did an authenticated identity come back looking like a switch?

    A reply that carries none of these is a device that took the password and
    answered with something else. See `device.login`, which refuses to keep a
    password in that case.
    """
    return any(info.get(field) for field in ("model", "version", "mac"))


class SwitchClient:
    """Talks to a set of switches over one pooled HTTP session."""

    def __init__(self, port: int | None = None, *,
                 session: requests.Session | None = None) -> None:
        # Read at construction, not at import: the tests move
        # `settings.KYLAND_PORT` at run time to point at a fake switch, and a
        # module-level default would have been frozen before they got there.
        self.port = int(port if port is not None else settings.KYLAND_PORT)
        self._session = session if session is not None else create_session()
        self._device_locks: dict[str, threading.Lock] = {}
        self._device_locks_guard = threading.Lock()
        self._scan_lock = threading.Lock()
        self._scan_cancel = threading.Event()
        # Which IP-assignment run currently OWNS a switch, by address. The
        # run drives PoE through the field script, which does not take the
        # per-write lock above — it cannot, the lock would be held for
        # minutes and every switch-screen request would hang instead of
        # being told why. So ownership is a claim the routes consult and
        # answer 409 from, not a mutex (see panel.api.routes.switch_routes).
        self._run_owners: dict[str, str] = {}

    def lock(self, ip: str) -> threading.Lock:
        """The write lock for one switch.

        Per address rather than one global lock: two switches can be written
        at once, and the PoE and portMode endpoints below rewrite a WHOLE
        table, so two writes to the SAME switch interleaving would have one
        overwrite the other's ports with values it read before the change.
        """
        with self._device_locks_guard:
            return self._device_locks.setdefault(ip, threading.Lock())

    def start_scan(self) -> bool:
        """Claim the scan slot. False means one is already running."""
        if not self._scan_lock.acquire(blocking=False):
            return False
        self._scan_cancel.clear()
        return True

    def finish_scan(self) -> None:
        self._scan_lock.release()

    def stop_scan(self, wait: float = 10.0) -> bool:
        """Ask the running scan to stop and wait for it to let go."""
        self._scan_cancel.set()
        if self._scan_lock.acquire(timeout=wait):
            self._scan_lock.release()
            return True
        return False

    @property
    def scan_cancel_event(self) -> threading.Event:
        return self._scan_cancel

    # ── the run claim ────────────────────────────────────────────────────
    # The IP-assignment run and the switch screen write to the same switch
    # through two different clients — the panel's (this one, per-write lock)
    # and the field script's own (`switch_request`, no lock). The PoE and
    # portMode endpoints rewrite a WHOLE table, so a screen write landing
    # mid-run would overwrite ports with values read before the run changed
    # them. The queue serialises runs against each other; this claim is what
    # tells the SCREEN's request threads a run owns the switch right now.

    def claim_run(self, ip: str, owner: str) -> bool:
        """Claim a switch for a run. False if another run already holds it."""
        with self._device_locks_guard:
            holder = self._run_owners.get(ip)
            if holder and holder != owner:
                return False
            self._run_owners[ip] = owner
            return True

    def release_run(self, ip: str) -> None:
        with self._device_locks_guard:
            self._run_owners.pop(ip, None)

    def run_owner(self, ip: str) -> str:
        """Which run holds this switch, or empty."""
        with self._device_locks_guard:
            return self._run_owners.get(ip, "")

    def clear_runs(self) -> None:
        """Forget every claim. Shutdown and tests."""
        with self._device_locks_guard:
            self._run_owners.clear()

    @staticmethod
    def _authentication(credentials: tuple[str, str] | None):
        """No store is consulted. What the caller passed is what is used."""
        return HTTPBasicAuth(*credentials) if credentials else None

    def _request(self, method: str, ip: str, endpoint: str, *,
                 auth: HTTPBasicAuth | None, timeout: float,
                 **kwargs) -> requests.Response:
        url = f"http://{ip}:{self.port}/{endpoint}"
        return self._session.request(method, url, auth=auth, timeout=timeout,
                                     **kwargs)

    @staticmethod
    def _decode(response: requests.Response):
        """The reply as JSON, or the reason it is not usable.

        HTTP 200 IS NOT SUCCESS HERE. A KYLAND switch that wants a password
        answers the login page with 200 and text/html, so "did not parse as
        JSON" is an authentication result, not a parse error.
        """
        if (response.status_code in (401, 403)
                or "WWW-Authenticate" in response.headers):
            raise AuthError(i18n.t("error.probeAuth"))
        try:
            response.raise_for_status()
        except Exception as exc:
            raise classify(exc)
        try:
            return response.json()
        except ValueError as exc:
            # See the note above `looks_like_login_page`. A login page means
            # "sign in"; any other page means this is not a switch, and the
            # two must not arrive at the screen as the same answer.
            if looks_like_login_page(response.text):
                raise AuthError(i18n.t("error.probeAuth")) from exc
            raise VerificationError(i18n.t("error.notASwitch")) from exc

    def get(self, ip: str, endpoint: str, timeout: float = 5,
            credentials: tuple[str, str] | None = None, *,
            quiet: bool = False):
        """Read one endpoint. `quiet` is kept for scan call sites."""
        try:
            response = self._request(
                "GET", ip, endpoint,
                auth=self._authentication(credentials), timeout=timeout)
        except requests.RequestException as exc:
            raise classify(exc)
        return self._decode(response)

    def post(self, ip: str, endpoint: str, form: dict, timeout: float = 8,
             credentials: tuple[str, str] | None = None):
        """Write one endpoint.

        The two headers are not decoration: the switch's handler looks for the
        form encoding and answers a request without `X-Requested-With` with
        its login page instead of JSON.
        """
        try:
            response = self._request(
                "POST", ip, endpoint,
                auth=self._authentication(credentials), timeout=timeout,
                data=form,
                headers={
                    "Content-Type":
                        "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                })
        except requests.RequestException as exc:
            raise classify(exc)
        return self._decode(response)

    def identity(self, ip: str, timeout: float = 1.5,
                 credentials: tuple[str, str] | None = None, *,
                 quiet: bool = False) -> dict | None:
        """Who is at this address — or None if nobody answered.

        Three outcomes, and they are three different things to the screen:
        a filled-in identity, `locked: True` for a switch that wants a
        password, and None for an address with nothing on it. Collapsing the
        middle one into None would hide every switch the operator has not
        signed in to yet, which is all of them on the first scan.
        """
        try:
            payload = self.get(ip, "stat/basicInfo", timeout=timeout,
                               credentials=credentials, quiet=quiet)
        except AuthError:
            # A switch nobody has signed in to yet has no name to give. The
            # placeholder is a catalogue message rather than the word
            # "Switch", and lazy so it follows a language change like every
            # other stored string does (see panel/i18n.py).
            return {"ip": ip, "name": i18n.lazy("switch.headUnopened"),
                    "model": "", "version": "", "mac": "", "locked": True}
        except Exception:
            return None
        info = (payload.get("basicInfo", payload)
                if isinstance(payload, dict) else {})
        if not isinstance(info, dict):
            info = {}
        return {
            "ip": ip,
            "name": (info.get("deviceName") or info.get("sysName")
                     or i18n.lazy("switch.headUnopened")),
            "model": info.get("deviceType") or info.get("model") or "",
            "version": (info.get("softVer")
                        or info.get("softwareVersion") or ""),
            "mac": info.get("macAddress") or info.get("mac") or "",
            "locked": False,
        }

    @staticmethod
    def tcp_open(ip: str, port: int, timeout: float = 0.4) -> bool:
        return tcp_open(ip, port, timeout)

    def discover(self, expression: str, workers: int = 64,
                 cancel_event: threading.Event | None = None,
                 credentials: tuple[str, str] | None = None) -> dict:
        """Find the switches on an address, a prefix or a network.

        Two passes. The first knocks on the port, which is fast and rules out
        most of a /24 in seconds. The second asks the survivors who they are,
        which costs a request each.

        The fallback matters on small networks: a switch can refuse the TCP
        knock from a machine it does not know and still answer HTTP, so when
        the sweep finds nothing and the network is small enough to ask
        directly, every address is asked.
        """
        addresses, single = resolve_addresses(expression)

        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())

        if single:
            candidates = addresses
        else:
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                candidates = [
                    address
                    for address, is_open in zip(
                        addresses,
                        pool.map(
                            lambda address: (
                                not cancelled()
                                and self.tcp_open(address, self.port,
                                                  TCP_PROBE_TIMEOUT)),
                            addresses),
                        strict=True)
                    if is_open]
            if cancelled():
                return {"switches": [], "probed": len(addresses),
                        "queried": 0, "cancelled": True}
            if not candidates and len(addresses) <= HTTP_FALLBACK_LIMIT:
                candidates = addresses

        timeout = 6.0 if single else 4.0
        found = []
        with futures.ThreadPoolExecutor(
                max_workers=min(len(candidates) or 1, 24)) as pool:
            for result in pool.map(
                    lambda address: (
                        None if cancelled()
                        else self.identity(address, timeout=timeout,
                                           credentials=credentials,
                                           quiet=True)),
                    candidates):
                if result:
                    found.append(result)
        return {"switches": found, "probed": len(addresses),
                "queried": len(candidates), "cancelled": cancelled()}
