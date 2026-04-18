"""ToolPolicy protocol and DefaultToolPolicy implementation — Task 1.10."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolPolicy(Protocol):
    def authorized_tools(
        self, persona: Any, role: Any, *, loaded_extensions: list[Any]
    ) -> list[Any]: ...
    def authorized_extensions(
        self, persona: Any, role: Any, *, loaded_extensions: list[Any]
    ) -> list[Any]: ...
    def export_tool_manifest(self, persona: Any, role: Any) -> dict[str, Any]: ...


class DefaultToolPolicy:
    def authorized_tools(
        self, persona: Any, role: Any, *, loaded_extensions: list[Any]
    ) -> list[Any]:
        all_tools: list[Any] = []
        for ext in loaded_extensions:
            all_tools.extend(ext.as_langchain_tools())

        preferred = role.preferred_tools or []
        if not preferred:
            return all_tools
        return [t for t in all_tools if getattr(t, "name", None) in preferred]

    def authorized_extensions(
        self, persona: Any, role: Any, *, loaded_extensions: list[Any]
    ) -> list[Any]:
        return list(loaded_extensions)

    def export_tool_manifest(self, persona: Any, role: Any) -> dict[str, Any]:
        manifest: dict[str, Any] = {}

        extensions_map: dict[str, Any] = {}
        for ext_cfg in (persona.extensions or []):
            module_name = ext_cfg.get("module", "unknown")
            extensions_map[module_name] = ext_cfg.get("config", {})
        if extensions_map:
            manifest["extensions"] = extensions_map

        if persona.tool_sources:
            manifest["tool_sources"] = dict(persona.tool_sources)

        return manifest
