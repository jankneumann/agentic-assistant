"""Registry of discovered HTTP tools keyed by ``{source}:{operation_id}``.

Concrete class (not a Protocol) per design decision D7 — only one
implementation is in sight for P3. Key naming per D3. Since P17
``mcp-server-exposure`` the registry holds harness-neutral
:class:`~assistant.core.toolspec.ToolSpec` instances (spec ``tool-spec``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from assistant.core.toolspec import ToolSpec


def tool_key(source: str, op_id: str) -> str:
    """Compose the canonical registry key ``"{source}:{op_id}"``."""
    return f"{source}:{op_id}"


@dataclass
class HttpToolRegistry:
    """Holds discovered tools with source-scoped and preference-scoped lookups."""

    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, source: str, op_id: str, tool: ToolSpec) -> None:
        """Store ``tool`` under the ``{source}:{op_id}`` key."""
        self._tools[tool_key(source, op_id)] = tool

    def list_all(self) -> list[ToolSpec]:
        """Return every registered tool sorted lexicographically by key.

        The sort makes repeated calls byte-identical, which downstream
        tests and snapshots rely on.
        """
        return [self._tools[k] for k in sorted(self._tools)]

    def by_source(self, name: str) -> list[ToolSpec]:
        """Return tools whose registry key starts with ``f"{name}:"``."""
        prefix = f"{name}:"
        return [
            self._tools[k] for k in sorted(self._tools) if k.startswith(prefix)
        ]

    def by_preferred(
        self, preferred: Iterable[str]
    ) -> list[ToolSpec]:
        """Return tools whose key appears in ``preferred`` (unknown keys dropped)."""
        return [self._tools[k] for k in preferred if k in self._tools]

    def __len__(self) -> int:
        return len(self._tools)

    def __bool__(self) -> bool:
        return bool(self._tools)
