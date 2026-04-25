"""ToolPolicy protocol and DefaultToolPolicy implementation — Task 1.10.

Extended in Task 7.2 to consume an optional :class:`HttpToolRegistry`
supplied by the ``http-tools-layer`` phase: ``authorized_tools``
merges extension tools with HTTP-tool registry contents and applies
the ``role.preferred_tools`` filter uniformly by tool name
(``"{source}:{op_id}"`` for HTTP tools).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from assistant.http_tools import HttpToolRegistry
from assistant.telemetry.tool_wrap import wrap_extension_tools


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
    def __init__(
        self,
        *,
        http_tool_registry: HttpToolRegistry | None = None,
    ) -> None:
        self._http_tool_registry = http_tool_registry

    def authorized_tools(
        self, persona: Any, role: Any, *, loaded_extensions: list[Any]
    ) -> list[Any]:
        all_tools: list[Any] = []
        for ext in loaded_extensions:
            # Spec capability-resolver "Aggregated Extension Tools Are
            # Traced": each extension's tools are wrapped at the
            # aggregation site so every invocation emits one
            # ``trace_tool_call(tool_kind="extension", ...)``. The
            # shared helper keeps wrapping policy in one place.
            all_tools.extend(wrap_extension_tools(ext))

        if self._http_tool_registry is not None:
            all_tools.extend(self._http_tool_registry.list_all())

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

        if self._http_tool_registry is not None:
            # Spec: list of registered HTTP tool keys "{source}:{op_id}"
            # (not a list of dicts). See specs/tool-policy/spec.md
            # "Tool Manifest Export" scenario.
            manifest["http_tools"] = [
                t.name for t in self._http_tool_registry.list_all()
            ]

        return manifest
