"""Harness adapter base classes — SDK and Host tiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig

if TYPE_CHECKING:
    from assistant.harnesses.sdk.events import HarnessEvent


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
        - ``DeepAgentsHarness`` returns ``self._thread_id`` (a UUID set by
          ``create_agent``).
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
    ) -> str: ...


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
