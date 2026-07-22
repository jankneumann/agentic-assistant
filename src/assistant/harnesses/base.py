"""Harness adapter base classes — SDK and Host tiers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig

if TYPE_CHECKING:
    from assistant.delegation.context import DelegationContext
    from assistant.harnesses.sdk.events import HarnessEvent

logger = logging.getLogger(__name__)


class HarnessAdapter(ABC):
    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        self.persona = persona
        self.role = role

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def harness_type(self) -> str: ...


class SdkHarnessAdapter(HarnessAdapter):
    """SDK-based harness that owns the agent loop."""

    def harness_type(self) -> str:
        return "sdk"

    @property
    def thread_id(self) -> str:
        """Stable conversation-thread identifier for this adapter instance.

        Concrete SDK harnesses MUST override this property to return a
        non-empty string that persists for the lifetime of the adapter
        instance (i.e., across multiple ``invoke`` and ``astream_invoke``
        calls).

        The web transport layer passes this value to the AG-UI mapper as the
        ``thread_id`` keyword argument (per D4 and the harness-adapter spec
        "SdkHarnessAdapter exposes a thread_id for transport binding").

        Examples:
        - ``DeepAgentsHarness`` synthesizes a UUID at construction and
          returns it unchanged for the adapter instance's lifetime.
        - ``MSAgentFrameworkHarness`` synthesizes a UUID at construction.

        Raises ``NotImplementedError`` on the base class — concrete
        implementations MUST override.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.thread_id is not implemented. "
            "Concrete SDK harnesses must override this property."
        )

    @abstractmethod
    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any: ...

    @abstractmethod
    async def invoke(self, agent: Any, message: str) -> str: ...

    def astream_invoke(
        self, agent: Any, message: str
    ) -> AsyncIterator[HarnessEvent]:
        """Stream a harness invocation as a sequence of HarnessEvent instances.

        The returned async iterator MUST:
        - Begin with a ``RunStarted`` event.
        - Yield zero or more ``TextDelta``, ``ToolCallStart``,
          ``ToolCallArgs``, and ``ToolCallEnd`` events.
        - End with a ``RunFinished`` event (``error=None`` on success;
          ``error=<ClassName>`` on failure, per D8 two-phase error contract).
        - After a failure ``RunFinished``, re-raise the original exception
          (Phase 2 of the D8 two-phase error contract).

        The ``@traced_harness`` decorator MUST be applied to every concrete
        override. It MUST NOT be applied to this base-class stub.

        Concrete implementations override this method as an async generator
        function (``async def astream_invoke(self, ...) -> AsyncIterator[...]``
        with ``yield`` statements). The base raises ``NotImplementedError``
        so the contract is enforced at runtime for any harness that has not
        implemented streaming.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.astream_invoke is not implemented. "
            "Concrete SDK harnesses must override this method."
        )

    @abstractmethod
    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
        context: DelegationContext | None = None,
    ) -> str:
        """Spawn a nested sub-agent for ``role`` and run it on ``task``.

        ``context`` (P12 delegation-context) is an ADDITIVE keyword
        parameter: ``None`` preserves the pre-P12 behavior exactly.
        When provided, concrete harnesses MUST render
        ``context.render()`` as a ``## Delegation context`` block ahead
        of the sub-agent's composed system prompt (mirroring the D27
        ``## Recent context`` prepend).
        """
        ...

    async def _capture_interaction(
        self, user_message: str, response: str
    ) -> None:
        """Best-effort post-turn memory capture (memory-retrieval-activation).

        Called by concrete harnesses after a *successful* ``invoke`` /
        ``astream_invoke`` completion. Resolves the harness's
        ``MemoryPolicy`` (via the concrete class's
        ``_resolve_memory_policy``, when it defines one) and awaits
        ``record_interaction``. Every failure — policy resolution,
        missing method, backend write — is swallowed with a WARNING
        log: memory failures must never break a conversation.
        """
        try:
            resolve = getattr(self, "_resolve_memory_policy", None)
            if resolve is None:
                return
            policy = resolve()
            record = getattr(policy, "record_interaction", None)
            if record is None:
                return
            await record(
                self.persona,
                self.role,
                user_message=user_message,
                response=response,
            )
        except Exception:
            logger.warning(
                "Post-turn memory capture failed for persona '%s' "
                "(role '%s'); continuing without capture",
                getattr(self.persona, "name", "<unknown>"),
                getattr(self.role, "name", "<unknown>"),
                exc_info=True,
            )


class HostHarnessAdapter(HarnessAdapter):
    """Host harness where the host owns the agent loop.

    Our code exports configuration artifacts; the host provides
    memory, sandbox, permissions, and tool execution.
    """

    def harness_type(self) -> str:
        return "host"

    @abstractmethod
    def export_context(self, capabilities: Any) -> dict[str, str]: ...

    @abstractmethod
    def export_guardrail_declarations(
        self, capabilities: Any
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def export_tool_manifest(
        self, capabilities: Any
    ) -> dict[str, Any]: ...
