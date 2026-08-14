"""Automatic IP assignment.

The plan (which device on which port gets which IP) comes from DeviceMap. The
run itself uses the verified flow in field_scripts/intercom_ip_assign.py:
open PoE ports one at a time so only one device is up, confirm the port from
the MAC table, write the IP and confirm after the reset — all field-proven
steps. No second implementation is written here.

Credentials: the switch username/password comes from the in-memory store and
reaches the script as an in-process argument list. The real OS command line is
unchanged (rewriting sys.argv does not change `ps` output) and nothing is
written to disk.

The run writes to the network: it toggles PoE ports and writes IPs to devices.
Ports that must stay out of it (the computer's own port, the link between two
switches) are therefore rejected up front.
"""

from .addressing import (SEARCH_LIMIT, can_flush_arp, factory_ip,
                         is_ipv4, range_candidates, search_candidates)
from .audit import address_map, audit_identities, extension_of
from .factory_reset import reset_to_factory
from .plan import build_plan, devices_by_port, front_panel, resolve_groups
from .ports import (allowed_ports, assert_not_protected, computer_port,
                    format_ports, parse_ports, port_key, protected_ports)
from .progress import RunProgress, parse_event
from .runner import groups_without_runner, run

__all__ = ["SEARCH_LIMIT", "RunProgress", "address_map", "allowed_ports",
           "assert_not_protected", "audit_identities", "build_plan",
           "can_flush_arp", "computer_port", "devices_by_port",
           "extension_of", "factory_ip", "format_ports", "front_panel",
           "groups_without_runner", "is_ipv4", "parse_event", "parse_ports",
           "port_key", "protected_ports", "range_candidates",
           "reset_to_factory", "resolve_groups", "run", "search_candidates"]
