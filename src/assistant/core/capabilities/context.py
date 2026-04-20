"""ContextProvider protocol — formalizes system prompt composition."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ContextProvider(Protocol):
    def compose_system_prompt(self, persona: Any, role: Any) -> str: ...
    def export_context(self, persona: Any, role: Any) -> dict[str, str]: ...


class DefaultContextProvider:
    """Delegates to the existing compose_system_prompt function."""

    def compose_system_prompt(self, persona: Any, role: Any) -> str:
        from assistant.core.composition import compose_system_prompt

        return compose_system_prompt(persona, role)

    def export_context(self, persona: Any, role: Any) -> dict[str, str]:
        return {"system_prompt": self.compose_system_prompt(persona, role)}
