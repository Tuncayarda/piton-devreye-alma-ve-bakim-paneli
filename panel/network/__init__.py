"""Preparing the computer's own network so the devices can be reached.

Every other part of the panel assumes it can talk to an address it read out of
DeviceMap. That assumption broke in the field: an unconfigured intercom
answers on 10.1.1.12 whatever train set it belongs to, and a computer sitting
on 10.17.1.222/24 has no route there at all. Nothing was wrong with the run —
the packets never left the machine. The address had to be added by hand in
system settings before any of it worked.

This package removes that step. It works out which networks an operation
needs (`planning`), which adapter is the one plugged into the switch
(`adapters`), and adds a secondary address there (`aliases`, `commands`) —
then takes it back when the application closes.

The whole of it only ever ADDS addresses beside the ones already configured.
Nothing existing is edited or deleted, no persistent configuration is written,
and no routing table, DHCP setting or VLAN is touched.

`routes` is the one part that does not prepare anything: it reads the routing
table back and reports a network the computer can no longer send into. That
state is invisible from a device's point of view — it looks exactly like dead
hardware — so it is named rather than left to be guessed at.
"""

from .adapters import Adapter, choose, list_adapters, local_networks
from .aliases import active, add, release, release_all, sweep_stale
from .planning import (DEFAULT_HOST_OCTET, DEFAULT_PREFIX, Requirement,
                       choose_host, network_of, occupied, required_networks)
from .prepare import (ensure, preferences, readiness, save_preferences,
                      select_adapter, state)
from .routes import broken_networks

__all__ = [
                       "DEFAULT_HOST_OCTET",
                       "DEFAULT_PREFIX",
                       "Adapter",
                       "Requirement",
                       "active",
                       "add",
                       "broken_networks",
                       "choose",
                       "choose_host",
                       "ensure",
                       "list_adapters",
                       "local_networks",
                       "network_of",
                       "occupied",
                       "preferences",
                       "readiness",
                       "release",
                       "release_all",
                       "required_networks",
                       "save_preferences",
                       "select_adapter",
                       "state",
                       "sweep_stale",
]
