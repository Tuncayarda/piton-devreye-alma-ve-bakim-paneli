#!/usr/bin/env python3
"""The panel's four states and five verification outcomes.

Defined once here because both the error classes and the probe results
produce them, and the UI colours every row from them:

    ok       reached the device and verified the expected data
    auth     device is reachable but wants a username/password
    failed   timeout, refused connection, network error, unverifiable reply
    unknown  not applicable to this device, or not read yet

"not applicable" and "not read" stay distinct on purpose: collapsing them
shows a broken device as normal, or a normal device as broken.
"""
from __future__ import annotations

OK = "ok"
AUTH = "auth"
FAILED = "failed"
UNKNOWN = "unknown"

VERIFIED = "verified"
AUTH_REQUIRED = "auth_required"
UNVERIFIED = "unverified"
NOT_READ = "not_read"
NOT_APPLICABLE = "not_applicable"
