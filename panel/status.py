#!/usr/bin/env python3
"""The panel's five states and five verification outcomes.

Defined once here because both the error classes and the probe results
produce them, and the UI colours every row from them:

    ok       reached the device and verified the expected data
    auth     device is reachable but wants a username/password
    review   alive on the network (answers ping) but gave no information
    failed   timeout, refused connection, network error, unverifiable reply
    unknown  not applicable to this device, or not read yet

"not applicable" and "not read" stay distinct on purpose: collapsing them
shows a broken device as normal, or a normal device as broken.

`review` exists because red was carrying two different afternoons. A device
that is OFF and a device that is up but silent on its protocol used to look
identical, and the operator walked to both. The probe now follows a failed
read with one ping (`probe.reader`): no answer stays red — go power it —
and an answer becomes "needs inspection", which is a different errand.
"""
from __future__ import annotations

OK = "ok"
AUTH = "auth"
REVIEW = "review"
FAILED = "failed"
UNKNOWN = "unknown"

VERIFIED = "verified"
AUTH_REQUIRED = "auth_required"
UNVERIFIED = "unverified"
NOT_READ = "not_read"
NOT_APPLICABLE = "not_applicable"
