"""Extension protocol.

Extensions wrap external system APIs (Gmail, MS Graph, etc.) and expose them
to the underlying harness. P1 shipped empty-tool stubs; P5 added the four
real MS implementations; P14 adds real Google implementations.

Tool surface (P17 ``mcp-server-exposure`` / spec ``tool-spec``)
---------------------------------------------------------------

Extensions expose their tools as harness-neutral
:class:`~assistant.core.toolspec.ToolSpec` instances via a single
``tool_specs() → list[ToolSpec]`` method. The per-harness adapters in
``assistant.harnesses.tool_adapters`` render those specs to each
harness's native shape (LangChain ``StructuredTool``, MSAF
``FunctionTool``, MCP tool listings). The legacy dual-surface methods
``as_langchain_tools()`` / ``as_ms_agent_tools()`` were REMOVED from
the Protocol and from every in-tree extension per the ``tool-spec``
spec's deprecation requirement (removal is the P17 exit criterion;
owner review verdict 2026-07-16). Out-of-tree structural extensions
must migrate to ``tool_specs()`` — no compatibility shim is consulted
by any call site.

Lifecycle hooks (P10 ``extension-lifecycle``)
---------------------------------------------

Beyond the required Protocol surface below, the extension contract
defines three OPTIONAL async lifecycle hooks:

* ``async def initialize(self) -> None`` — called once by
  ``PersonaRegistry.load_extensions`` after the extension is loaded,
  before its tools are exposed (establish connections, warm caches,
  validate configuration). A raising ``initialize`` disables that
  extension without failing persona load.
* ``async def shutdown(self) -> None`` — called on graceful teardown
  (close connections, flush buffers). MUST be idempotent.
* ``async def refresh_credentials(self) -> None`` — proactive
  credential refresh seam (OAuth token refresh, key rotation) for
  periodic or on-demand invocation by lifecycle consumers (P13
  security-hardening, P14 google-extensions).

The hooks are deliberately NOT members of the ``runtime_checkable``
Protocol: adding them would flip ``isinstance(ext, Extension)`` to
``False`` for every existing private-submodule extension that
satisfies the Protocol structurally (extension-lifecycle design D1).
Callers discover each hook via ``callable(getattr(ext, hook, None))``
and treat an absent hook as a no-op; a present hook is invoked
tolerantly (its result is awaited only when awaitable), so a
synchronous hook on an out-of-tree extension is accepted (D2).

Public extensions should subclass :class:`ExtensionBase` to inherit
no-op defaults instead of hand-writing the hooks.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from assistant.core.resilience import HealthStatus
from assistant.core.toolspec import ToolSpec


@runtime_checkable
class Extension(Protocol):
    name: str

    def tool_specs(self) -> list[ToolSpec]: ...

    async def health_check(self) -> HealthStatus: ...


class ExtensionBase:
    """Optional adoption base carrying no-op lifecycle-hook defaults.

    Concrete public extensions subclass this so they are
    lifecycle-complete without boilerplate. It intentionally carries
    ONLY the lifecycle hooks — no tool-surface stubs — so it composes
    cleanly with either tool surface during the P24 ``tool-spec``
    migration window (extension-lifecycle design D8). Private
    submodule extensions may satisfy the lifecycle contract
    structurally instead; they never need to import this class.
    """

    async def initialize(self) -> None:
        """Called once post-load, before tools are exposed. Default: no-op."""
        return None

    async def shutdown(self) -> None:
        """Called on graceful teardown. Idempotent. Default: no-op."""
        return None

    async def refresh_credentials(self) -> None:
        """Proactive credential-refresh seam. Default: no-op."""
        return None
