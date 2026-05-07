"""ms_graph extension (P1 stub — real impl lands in P4/P5)."""

from __future__ import annotations

from typing import Any

from assistant.extensions._stub import StubExtension


def create_extension(
    config: dict[str, Any], *, persona: Any = None
) -> StubExtension:
    # P5 wp-foundation-protocols pre-stage: factory now accepts the
    # persona kwarg per the new contract. The real ``MsGraphExtension``
    # (and its TypeError-on-persona=None short-circuit) lands in
    # wp-ms-graph; until then we stay a stub for parity with gmail/gcal
    # /gdrive.
    _ = persona
    return StubExtension("ms_graph", config)
