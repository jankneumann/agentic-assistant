"""CapabilityResolver — assembles CapabilitySet per harness type — Task 2.2."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from assistant.core.capabilities.context import ContextProvider, DefaultContextProvider
from assistant.core.capabilities.guardrails import AllowAllGuardrails, GuardrailProvider
from assistant.core.capabilities.memory import (
    FileMemoryPolicy,
    HostProvidedMemoryPolicy,
    MemoryPolicy,
    PostgresGraphitiMemoryPolicy,
)
from assistant.core.capabilities.sandbox import PassthroughSandbox, SandboxProvider
from assistant.core.capabilities.tools import DefaultToolPolicy, ToolPolicy
from assistant.core.capabilities.types import (
    CapabilitySet,
    ExecutionContext,
    SandboxConfig,
)


class _HostProvidedSandbox:
    def create_context(self, config: SandboxConfig) -> ExecutionContext:
        return ExecutionContext(
            work_dir=Path.cwd(), isolation_type="host_provided"
        )

    def cleanup(self, context: ExecutionContext) -> None:
        pass


class CapabilityResolver:
    def __init__(
        self,
        *,
        guardrail_factory: Callable[[], GuardrailProvider] | None = None,
        sandbox_factory: Callable[[], SandboxProvider] | None = None,
        memory_factory: Callable[[], MemoryPolicy] | None = None,
        tool_factory: Callable[[], ToolPolicy] | None = None,
        context_factory: Callable[[], ContextProvider] | None = None,
    ) -> None:
        self._guardrail_factory = guardrail_factory
        self._sandbox_factory = sandbox_factory
        self._memory_factory = memory_factory
        self._tool_factory = tool_factory
        self._context_factory = context_factory

    def resolve(
        self, persona: Any, harness_type: str, role: Any
    ) -> CapabilitySet:
        context = (
            self._context_factory()
            if self._context_factory
            else DefaultContextProvider()
        )

        if harness_type == "host":
            return CapabilitySet(
                guardrails=(
                    self._guardrail_factory()
                    if self._guardrail_factory
                    else AllowAllGuardrails()
                ),
                sandbox=(
                    self._sandbox_factory()
                    if self._sandbox_factory
                    else _HostProvidedSandbox()
                ),
                memory=(
                    self._memory_factory()
                    if self._memory_factory
                    else HostProvidedMemoryPolicy()
                ),
                tools=(
                    self._tool_factory()
                    if self._tool_factory
                    else DefaultToolPolicy()
                ),
                context=context,
            )

        if self._memory_factory:
            memory = self._memory_factory()
        elif getattr(persona, "database_url", ""):
            memory = PostgresGraphitiMemoryPolicy(persona)
        else:
            memory = FileMemoryPolicy()

        return CapabilitySet(
            guardrails=(
                self._guardrail_factory()
                if self._guardrail_factory
                else AllowAllGuardrails()
            ),
            sandbox=(
                self._sandbox_factory()
                if self._sandbox_factory
                else PassthroughSandbox()
            ),
            memory=memory,
            tools=(
                self._tool_factory()
                if self._tool_factory
                else DefaultToolPolicy()
            ),
            context=context,
        )
