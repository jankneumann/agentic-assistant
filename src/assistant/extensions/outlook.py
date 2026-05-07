"""outlook extension (P1 stub — real impl lands in P4/P5)."""

from __future__ import annotations

from typing import Any

from assistant.extensions._stub import StubExtension


def create_extension(
    config: dict[str, Any], *, persona: Any = None
) -> StubExtension:
    # See ms_graph.py for the wp-foundation-protocols pre-stage
    # rationale — real OutlookExtension lands in wp-outlook.
    _ = persona
    return StubExtension("outlook", config)
