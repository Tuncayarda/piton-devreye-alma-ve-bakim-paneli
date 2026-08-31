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

from .addressing import (DEFAULT_TARGET_PREFIX, MAX_TARGET_PREFIX,
                         effective_prefix,
                         MIN_TARGET_PREFIX, SEARCH_LIMIT, can_flush_arp,
                         factory_ip, is_ipv4, netmask_for, parse_prefix,
                         parse_set, range_candidates, search_candidates)
from .audit import address_map, audit_identities, extension_of
from .factory_reset import reset_to_factory
from .plan import (assignment_kind, build_plan, device_switch_for,
                   devices_by_port, front_panel, run_allowed_ports,
                   resolve_groups)
from .ports import (allowed_ports, assert_not_protected, computer_port,
                    format_ports, parse_ports, port_key, protected_ports)
from .preflash import choose_file as choose_preflash_file
from .preflash import chosen as preflash_file
from .preflash import forget_file as forget_preflash_file
from .preflash import options_from as preflash_options
from .preflash import validate as validate_preflash
from .progress import RunProgress, parse_event
from .lcd_runner import manual_candidates as lcd_manual_candidates
from .lcd_runner import run_manual as run_lcd_manual
from .runner import groups_without_runner, run

__all__ = [
                         "DEFAULT_TARGET_PREFIX",
                         "MAX_TARGET_PREFIX",
                         "MIN_TARGET_PREFIX",
                         "SEARCH_LIMIT",
                         "RunProgress",
                         "address_map",
                         "allowed_ports",
                         "assert_not_protected",
                         "assignment_kind",
                         "audit_identities",
                         "build_plan",
                         "can_flush_arp",
                         "choose_preflash_file",
                         "computer_port",
                         "device_switch_for",
                         "devices_by_port",
                         "effective_prefix",
                         "extension_of",
                         "factory_ip",
                         "forget_preflash_file",
                         "format_ports",
                         "front_panel",
                         "groups_without_runner",
                         "is_ipv4",
                         "lcd_manual_candidates",
                         "netmask_for",
                         "parse_event",
                         "parse_ports",
                         "parse_prefix",
                         "parse_set",
                         "port_key",
                         "preflash_file",
                         "preflash_options",
                         "protected_ports",
                         "range_candidates",
                         "reset_to_factory",
                         "resolve_groups",
                         "run",
                         "run_allowed_ports",
                         "run_lcd_manual",
                         "search_candidates",
                         "validate_preflash",
]
