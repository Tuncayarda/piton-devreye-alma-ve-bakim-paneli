#!/usr/bin/env python3
"""KYLAND switch access — the single client for the whole panel."""
from __future__ import annotations

from .client import SwitchClient, create_session, looks_like_switch
from .discovery import (DEFAULT_DISCOVERY_CIDR, DEFAULT_PREFIX,
                        HTTP_FALLBACK_LIMIT, MAX_DISCOVERY_ADDRESSES,
                        TCP_PROBE_TIMEOUT, resolve_addresses, target_network,
                        tcp_open)
from . import device, network, ports, validation

# One client for the process. It holds no credentials (see panel.credentials);
# what it does hold is the pooled HTTP session, the per-switch write locks and
# the single-scan gate — all of which must be shared or they are pointless.
CLIENT = SwitchClient()


def reset() -> None:
    """Drop the scan state on shutdown. Credentials are not ours to clear."""
    CLIENT.stop_scan(wait=0.1)


__all__ = [
    "CLIENT",
    "DEFAULT_DISCOVERY_CIDR",
    "DEFAULT_PREFIX",
    "HTTP_FALLBACK_LIMIT",
    "MAX_DISCOVERY_ADDRESSES",
    "TCP_PROBE_TIMEOUT",
    "SwitchClient",
    "create_session",
    "device",
    "looks_like_switch",
    "network",
    "ports",
    "reset",
    "resolve_addresses",
    "target_network",
    "tcp_open",
    "validation",
]
