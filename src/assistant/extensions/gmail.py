"""gmail extension (P1 stub — real impl lands in P4/P5)."""

from __future__ import annotations

from typing import Any

from assistant.extensions._stub import StubExtension


def create_extension(config: dict[str, Any]) -> StubExtension:
    return StubExtension("gmail", config)
