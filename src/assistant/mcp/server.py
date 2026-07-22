"""MCP server surface — streamable-HTTP mount + ask tools (P17).

Mirrors the P6 A2A mount pattern: the web app factory
(``assistant.web.app.make_app``) constructs this state inside its
lifespan when ``assistant serve --mcp`` is used, hangs it on
``app.state.mcp``, and mounts the transport at :data:`MCP_PATH`.

Implementation decisions (design.md of ``mcp-server-exposure``):

- **Official ``mcp`` Python SDK, low-level server.** The low-level
  ``mcp.server.lowlevel.Server`` (not FastMCP) is used because its
  ``tools/list`` handler accepts pre-built ``mcp.types.Tool`` entries —
  a field-for-field rendering of our MCP-shaped
  :class:`~assistant.core.toolspec.ToolSpec` via
  ``render_mcp_tools`` — so serving a ToolSpec really is a transport
  concern with no translation layer (spec ``tool-spec``).
- **Stateless streamable HTTP, JSON responses.** Each POST is handled
  independently (``StreamableHTTPSessionManager(stateless=True,
  json_response=True)``); conversation continuity is carried by the
  explicit ``context_id`` tool argument (≡ session ``thread_id``,
  exactly like A2A's ``contextId``), not by MCP transport sessions.
- **One tool per enabled role** — ``ask_<role>`` — plus a generic
  ``ask`` bound to the serving role. Each invocation multiplexes over
  the shared :class:`~assistant.a2a.task_handler.SessionRegistry`
  machinery: no ``context_id`` creates a fresh session (harness +
  agent via the same pipeline as ``/chat``), a known ``context_id``
  reuses it, an unknown one is rejected (sessions are in-memory until
  durable session persistence lands).
- **Auth is deferred to P25** (OAuth 2.1 / MCP authorization spec);
  the server is loopback-only by default via the CLI's bind-host
  default and non-loopback warning.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.core.toolspec import ToolSpec
from assistant.harnesses.sessions import (
    DEFAULT_IDLE_TTL_SECONDS,
    SessionRegistry,
)
from assistant.harnesses.tool_adapters import render_mcp_tools

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server
    from mcp.server.streamable_http_manager import (
        StreamableHTTPSessionManager,
    )

#: Mount path for the streamable-HTTP MCP transport.
MCP_PATH = "/mcp"

#: Server identity advertised during MCP initialization.
MCP_SERVER_NAME = "agentic-assistant"

# Builds a fresh (harness, agent) pair for a given role — the same
# persona/role/harness pipeline the web lifespan runs, parameterized by
# role so each ask_<role> tool gets role-true sessions.
RoleSessionFactory = Callable[[RoleConfig], Awaitable[tuple[Any, Any]]]

# P30 durable-sessions: rebuilds a (harness, agent) pair for a given
# role BOUND to an existing thread_id (durable re-bind — the LangGraph
# checkpointer restores the conversation state for that id).
RoleRebindFactory = Callable[[RoleConfig, str], Awaitable[tuple[Any, Any]]]

_ASK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "The user message / task for the assistant.",
        },
        "context_id": {
            "type": "string",
            "description": (
                "Optional conversation id from a previous call's result; "
                "pass it back to continue that conversation. Omit to "
                "start a fresh one."
            ),
        },
    },
    "required": ["message"],
}


def sanitize_tool_name(role_name: str) -> str:
    """Map a role name onto the MCP tool-name charset ``[A-Za-z0-9_-]``."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", role_name)


@dataclass
class MCPServerState:
    """Everything the MCP surface needs, hung on ``app.state.mcp``."""

    persona_name: str
    default_role: str
    tool_specs: list[ToolSpec]
    registries: dict[str, SessionRegistry]
    server: Server = field(repr=False)
    session_manager: StreamableHTTPSessionManager = field(repr=False)


def _make_ask_handler(
    registry: SessionRegistry,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build the async handler backing one ``ask*`` ToolSpec."""

    async def _ask(
        message: str, context_id: str | None = None
    ) -> dict[str, Any]:
        if context_id is not None:
            # P30 durable-sessions: live session first, then durable
            # re-bind; only truly unknown/expired ids are rejected.
            session = await registry.resolve(context_id)
            if session is None:
                raise ValueError(
                    f"unknown context_id '{context_id}' "
                    "(never created, expired, or not durably resumable)"
                )
        else:
            session = await registry.create()
        # Serialize turns on the same session — mirrors the A2A task
        # handler's per-session lock so concurrent tools/call requests
        # against one context don't interleave harness turns.
        async with session.lock:
            response = await session.harness.invoke(session.agent, message)
        return {"response": response, "context_id": session.thread_id}

    return _ask


def build_ask_tool_specs(
    roles: list[RoleConfig],
    registries: dict[str, SessionRegistry],
    *,
    default_role: str,
) -> list[ToolSpec]:
    """One ``ask_<role>`` ToolSpec per enabled role + a generic ``ask``.

    The generic ``ask`` shares the default role's SessionRegistry, so a
    conversation started via ``ask`` can be continued via
    ``ask_<default-role>`` (and vice versa).
    """
    specs: list[ToolSpec] = []
    for rc in roles:
        registry = registries[rc.name]
        description = (
            f"Ask the '{rc.name}' role of this assistant "
            f"({rc.description or rc.display_name or rc.name}). "
            "Returns the response plus a context_id you can pass back "
            "to continue the conversation."
        )
        specs.append(
            ToolSpec(
                name=f"ask_{sanitize_tool_name(rc.name)}",
                description=description,
                input_schema=dict(_ASK_INPUT_SCHEMA),
                handler=_make_ask_handler(registry),
                source="mcp:serve",
            )
        )
    if default_role in registries:
        specs.append(
            ToolSpec(
                name="ask",
                description=(
                    "Ask this assistant (default role: "
                    f"'{default_role}'). Returns the response plus a "
                    "context_id you can pass back to continue the "
                    "conversation."
                ),
                input_schema=dict(_ASK_INPUT_SCHEMA),
                handler=_make_ask_handler(registries[default_role]),
                source="mcp:serve",
            )
        )
    return specs


def _build_server(tool_specs: list[ToolSpec]) -> Server:
    """Wire the low-level MCP server's tools/list + tools/call handlers.

    ``tools/list`` is a pure rendering of the ToolSpecs via the MCP
    adapter; ``tools/call`` dispatches to the matching spec's handler.
    Handler exceptions surface as MCP tool errors (``isError=True``
    results) via the SDK's built-in mapping; the SDK also validates
    arguments against each tool's ``inputSchema`` before the handler
    runs.
    """
    from mcp.server.lowlevel import Server

    server: Server = Server(MCP_SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        return render_mcp_tools(tool_specs)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
        spec = next((s for s in tool_specs if s.name == name), None)
        if spec is None:
            raise ValueError(f"unknown tool '{name}'")
        return await spec.handler(**arguments)

    return server


def build_mcp_state(
    persona: PersonaConfig,
    roles: list[RoleConfig],
    *,
    session_factory: RoleSessionFactory,
    default_role: str,
    idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
    session_store: Any | None = None,
    rebind_factory: RoleRebindFactory | None = None,
    harness_name: str = "",
) -> MCPServerState:
    """Assemble registries + ask tools + SDK server for one persona.

    The caller (web lifespan) owns the returned state: it must enter
    ``state.session_manager.run()`` for the app's lifetime and route
    HTTP requests under :data:`MCP_PATH` to
    ``state.session_manager.handle_request``.

    P30 durable-sessions: ``session_store`` + ``rebind_factory`` make
    known-but-released ``context_id`` values resumable (per-role
    registries re-bind through the same pipeline with the recorded
    thread_id). Omitting them keeps the pure in-memory behavior.
    """
    from mcp.server.streamable_http_manager import (
        StreamableHTTPSessionManager,
    )

    durable_ttl = float(
        getattr(getattr(persona, "sessions", None), "session_ttl_seconds", 0.0)
        or 0.0
    )
    registries: dict[str, SessionRegistry] = {}
    for rc in roles:
        async def _factory(rc: RoleConfig = rc) -> tuple[Any, Any]:
            return await session_factory(rc)

        rebind = None
        if rebind_factory is not None:
            async def _rebind(
                thread_id: str, rc: RoleConfig = rc
            ) -> tuple[Any, Any]:
                return await rebind_factory(rc, thread_id)

            rebind = _rebind

        registries[rc.name] = SessionRegistry(
            partial(_factory),
            idle_ttl_seconds=idle_ttl_seconds,
            store=session_store,
            rebind_factory=rebind,
            persona=persona.name,
            role=rc.name,
            harness=harness_name,
            durable_ttl_seconds=durable_ttl,
        )

    tool_specs = build_ask_tool_specs(
        roles, registries, default_role=default_role
    )
    server = _build_server(tool_specs)
    # Stateless + JSON responses: every POST is self-contained; session
    # continuity is the explicit context_id tool argument, and clients
    # that cannot hold SSE streams still get plain JSON bodies.
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
    )
    return MCPServerState(
        persona_name=persona.name,
        default_role=default_role,
        tool_specs=tool_specs,
        registries=registries,
        server=server,
        session_manager=session_manager,
    )


__all__ = [
    "MCP_PATH",
    "MCP_SERVER_NAME",
    "MCPServerState",
    "RoleRebindFactory",
    "RoleSessionFactory",
    "build_ask_tool_specs",
    "build_mcp_state",
    "sanitize_tool_name",
]
