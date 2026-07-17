"""A2A transport layer: maps HarnessEvent streams to A2A protocol events.

Sibling of ``transports/ag_ui`` — a second mapping over the SAME
``HarnessEvent`` vocabulary (the AG-UI mapper is untouched). Types live
in ``assistant.a2a.types`` (spec-shaped, migration-ready for the
official ``a2a-sdk``); this package only owns the event mapping.
"""

from assistant.transports.a2a.mapper import (
    APPROVAL_DENIED_ERROR_CLASSES,
    map_harness_to_a2a,
)

__all__ = ["APPROVAL_DENIED_ERROR_CLASSES", "map_harness_to_a2a"]
