"""Reading device configuration and writing target values.

The screen shows two columns side by side: what the device actually reports
and what will be written. An unreadable field stays empty (—) rather than
showing a default — calling a field "matching" without knowing what is on the
device makes the verification meaningless.
"""

from .apply import apply_targets, fetch
from .fields import FIELDS, config_scope, field_list, writable_for_scope
from .storage import (clear_saved_defaults, load_saved_defaults,
                      saved_defaults_summary)
from .targets import (forget_targets, group_secret_fields,
                      group_target_display, group_targets, resolve_target,
                      set_group_target, set_target, target_detail)

__all__ = ["FIELDS", "apply_targets", "clear_saved_defaults",
           "config_scope", "fetch",
           "field_list", "forget_targets", "group_secret_fields",
           "group_target_display", "group_targets", "load_saved_defaults",
           "resolve_target", "saved_defaults_summary", "set_group_target",
           "set_target", "target_detail", "writable_for_scope"]
