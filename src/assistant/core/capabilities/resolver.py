"""CapabilityResolver — assembles CapabilitySet per harness type — Task 2.2."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from assistant.core.capabilities.context import ContextProvider, DefaultContextProvider
from assistant.core.capabilities.guardrails import (
    AllowAllGuardrails,
    GuardrailConfig,
    GuardrailProvider,
    PolicyGuardrails,
)
from assistant.core.capabilities.memory import (
    FileMemoryPolicy,
    HostProvidedMemoryPolicy,
    MemoryPolicy,
    PostgresGraphitiMemoryPolicy,
)
from assistant.core.capabilities.models import (
    HostProvidedModelProvider,
    ModelProvider,
    ModelRegistry,
    RegistryModelProvider,
    default_model_registry,
)
from assistant.core.capabilities.sandbox import PassthroughSandbox, SandboxProvider
from assistant.core.capabilities.tools import DefaultToolPolicy, ToolPolicy
from assistant.core.capabilities.types import (
    CapabilitySet,
    ExecutionContext,
    SandboxConfig,
)
from assistant.http_tools import HttpToolRegistry


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
        model_factory: Callable[[], ModelProvider] | None = None,
        http_tool_registry: HttpToolRegistry | None = None,
    ) -> None:
        self._guardrail_factory = guardrail_factory
        self._sandbox_factory = sandbox_factory
        self._memory_factory = memory_factory
        self._tool_factory = tool_factory
        self._context_factory = context_factory
        self._model_factory = model_factory
        self._http_tool_registry = http_tool_registry

    def _resolve_models(self, persona: Any, harness_type: str) -> ModelProvider:
        """Slot #6 — capability-resolver spec + P19 model-provider-routing.

        Host harnesses get :class:`HostProvidedModelProvider` (the host
        seat owns model selection). SDK harnesses always get a
        :class:`RegistryModelProvider` — backed by the persona's
        ``models:`` registry when declared, else by the registry
        synthesized from the known harness defaults
        (:func:`default_model_registry`; P19 owner review verdict #3,
        registry-only).
        """
        if self._model_factory:
            return self._model_factory()
        if harness_type == "host":
            return HostProvidedModelProvider()
        registry = getattr(persona, "models", None)
        if isinstance(registry, ModelRegistry) and registry.entries:
            return RegistryModelProvider(registry)
        return RegistryModelProvider(default_model_registry())

    def _resolve_guardrails(self, persona: Any) -> GuardrailProvider:
        """Guardrail slot — P13 security-hardening.

        Factory override wins (unchanged). Otherwise, a persona that
        declares a non-empty ``guardrails:`` section gets
        :class:`PolicyGuardrails` (both host and sdk branches); every
        other persona keeps :class:`AllowAllGuardrails`, preserving
        pre-P13 behavior.
        """
        if self._guardrail_factory:
            return self._guardrail_factory()
        config = getattr(persona, "guardrails", None)
        if isinstance(config, GuardrailConfig) and config:
            return PolicyGuardrails(
                config, persona=getattr(persona, "name", "")
            )
        return AllowAllGuardrails()

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
                guardrails=self._resolve_guardrails(persona),
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
                    else DefaultToolPolicy(
                        http_tool_registry=self._http_tool_registry,
                    )
                ),
                context=context,
                models=self._resolve_models(persona, harness_type),
            )

        if self._memory_factory:
            memory = self._memory_factory()
        elif getattr(persona, "database_url", ""):
            memory = PostgresGraphitiMemoryPolicy(persona)
        else:
            memory = FileMemoryPolicy()

        return CapabilitySet(
            guardrails=self._resolve_guardrails(persona),
            sandbox=(
                self._sandbox_factory()
                if self._sandbox_factory
                else PassthroughSandbox()
            ),
            memory=memory,
            tools=(
                self._tool_factory()
                if self._tool_factory
                else DefaultToolPolicy(
                    http_tool_registry=self._http_tool_registry,
                )
            ),
            context=context,
            models=self._resolve_models(persona, harness_type),
        )
