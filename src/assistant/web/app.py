"""FastAPI application factory for the AG-UI bridge.

Design decisions: D3 (single harness per process), D6 (import direction),
D8 (two-phase error contract handled by mapper).

Usage::

    from assistant.web.app import make_app
    app = make_app(persona="personal", role="assistant", harness_name="deep_agents")

The lifespan context manager constructs the harness once at startup,
runs the same tool/extension/agent setup pipeline that ``assistant run``
uses, and stores both ``harness`` and ``agent`` on ``app.state``. All
``/chat`` requests share the same harness + agent instance.

Host harnesses (``HostHarnessAdapter``) are rejected eagerly because
they cannot satisfy the streaming contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleRegistry
from assistant.harnesses.base import HostHarnessAdapter
from assistant.harnesses.factory import create_harness

AgentFactory = Callable[
    [Any, Any, Any, PersonaRegistry, "httpx.AsyncClient | None"],
    Awaitable[Any],
]


def _problem_response(detail: str, status: int = 422) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": "Unprocessable Entity",
            "status": status,
            "detail": detail,
        },
        media_type="application/problem+json",
    )


async def _default_agent_factory(
    harness: Any,
    pc: Any,
    rc: Any,
    persona_reg: PersonaRegistry,
    http_client: httpx.AsyncClient | None,
) -> Any:
    """Run the same tool/extension/agent setup pipeline as ``assistant run``.

    Lazy-imports the capability + tool-discovery machinery so the
    privacy-boundary test for the telemetry subtree stays clean (no
    eager FastAPI-adjacent imports in the assistant.web module).

    ``http_client`` is owned by the FastAPI lifespan (see ``make_app``) so
    that discovered HTTP tools — which close over the caller-supplied
    client per ``discover_tools``' contract — remain usable for the
    lifetime of the agent. Passing ``None`` is only valid when the
    persona declares no ``tool_sources``. IMPL_REVIEW round-1 codex #2.
    """
    from assistant.core.capabilities.resolver import CapabilityResolver
    from assistant.http_tools import HttpToolRegistry
    from assistant.http_tools.discovery import discover_tools

    # Async variant: the lifespan runs inside the event loop, and the
    # extensions' initialize() hooks must be awaited (P10
    # extension-lifecycle). Shutdown is owned by the lifespan finally.
    extensions = await persona_reg.load_extensions_async(pc)

    tool_sources = getattr(pc, "tool_sources", None) or {}
    if tool_sources:
        if http_client is None:
            raise ValueError(
                "http_client is required when persona declares tool_sources "
                "(discovered tools close over the caller-owned AsyncClient)"
            )
        registry = await discover_tools(
            tool_sources,
            client=http_client,
            credentials=getattr(pc, "credentials", None),
        )
    else:
        registry = HttpToolRegistry()

    resolver = CapabilityResolver(http_tool_registry=registry)
    capabilities = resolver.resolve(pc, "sdk", rc)
    authorized = capabilities.tools.authorized_tools(
        pc, rc, loaded_extensions=extensions,
    )
    return await harness.create_agent(tools=authorized, extensions=extensions)


def make_app(
    persona: str,
    role: str,
    harness_name: str,
    *,
    _agent_factory: AgentFactory = _default_agent_factory,
    enable_a2a: bool = False,
    a2a_base_url: str = "http://127.0.0.1:8765",
    enable_mcp: bool = False,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    The lifespan constructs the harness exactly once (D3), runs the
    agent factory (default: full HTTP-tool discovery + capability
    resolution + ``create_agent``), and stores both the harness and
    the resulting agent on ``app.state``. Raises ``ValueError`` eagerly
    if the resolved harness is a host harness or if the harness factory
    raises (e.g. harness disabled for the persona).

    Args:
        persona: Persona name (looked up via PersonaRegistry).
        role: Role name (looked up via RoleRegistry).
        harness_name: One of the registered SDK harness names.
        _agent_factory: Override for the agent-construction pipeline.
            Tests inject a trivial factory to avoid mocking the full
            discover/resolve/authorize chain. Production callers should
            never pass this.
        enable_a2a: When True, additionally mounts the A2A protocol
            surface (P6 a2a-server): agent card at
            ``/.well-known/agent-card.json`` (+ legacy ``agent.json``)
            and JSON-RPC ``POST /a2a/v1`` with message/send +
            message/stream. A2A tasks multiplex over a
            ``SessionRegistry`` whose session factory runs the SAME
            harness/agent pipeline as this app's lifespan — one fresh
            harness (and thread_id) per A2A context.
        a2a_base_url: Externally reachable base URL advertised in the
            agent card's ``url`` field (the CLI passes
            ``http://<host>:<port>``).
        enable_mcp: When True, additionally mounts the MCP server
            surface (P17 mcp-server-exposure): a stateless streamable-
            HTTP transport at ``/mcp`` exposing one ``ask_<role>`` tool
            per enabled role (plus a generic ``ask`` bound to this
            app's serving role). MCP tool calls multiplex over per-role
            ``SessionRegistry`` instances whose session factory runs
            the SAME harness/agent pipeline as this app's lifespan —
            one fresh harness (and thread_id ≡ context_id) per
            conversation. Auth is deferred to P25; keep the bind host
            loopback-only.

    Returns:
        A FastAPI application with ``/chat`` (SSE) and ``/health`` routes,
        a custom RequestValidationError handler (RFC 7807), and ``harness``
        plus ``agent`` bound to ``app.state`` after lifespan startup.
    """
    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

    pc = persona_reg.load(persona)
    rc = role_reg.load(role, pc)

    harness = create_harness(pc, rc, harness_name)
    if isinstance(harness, HostHarnessAdapter):
        raise ValueError(
            f"Harness '{harness_name}' is a host harness. "
            "Use 'assistant export' for host harnesses; 'assistant serve' requires an SDK harness."
        )

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        # The AsyncClient is owned by the lifespan so that discovered HTTP
        # tools — which close over the caller-supplied client — remain
        # usable for the lifetime of the agent. Closing the client before
        # the agent is destroyed would orphan every discovered tool.
        # IMPL_REVIEW round-1 codex #2.
        tool_sources = getattr(pc, "tool_sources", None) or {}
        http_client: httpx.AsyncClient | None = None
        if tool_sources:
            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=False,
                verify=True,
                limits=httpx.Limits(
                    max_connections=20, max_keepalive_connections=5,
                ),
            )
        try:
            agent = await _agent_factory(
                harness, pc, rc, persona_reg, http_client,
            )
            app.state.harness = harness
            app.state.agent = agent
            app.state.persona = persona
            app.state.role = role
            app.state.harness_name = harness_name
            app.state.http_client = http_client
            if enable_a2a:
                # P6 a2a-server: sessions are created lazily per A2A
                # context through the same create_harness + agent
                # pipeline this lifespan just ran — the AG-UI harness
                # above stays the single instance for /chat, while A2A
                # multiplexes fresh instances via the SessionRegistry.
                from assistant.a2a.server import build_a2a_state

                async def _session_factory():
                    session_harness = create_harness(pc, rc, harness_name)
                    session_agent = await _agent_factory(
                        session_harness, pc, rc, persona_reg, http_client,
                    )
                    return session_harness, session_agent

                role_names = role_reg.available_for_persona(pc)
                role_cfgs = [role_reg.load(n, pc) for n in role_names]
                app.state.a2a = build_a2a_state(
                    pc,
                    role_cfgs,
                    session_factory=_session_factory,
                    base_url=a2a_base_url,
                )
            async with AsyncExitStack() as stack:
                if enable_mcp:
                    # P17 mcp-server-exposure: same mount pattern as
                    # A2A — per-role sessions run the same
                    # create_harness + agent pipeline as this lifespan;
                    # the streamable-HTTP session manager's run()
                    # context is held open for the app's lifetime.
                    from assistant.mcp.server import build_mcp_state

                    async def _mcp_session_factory(role_cfg):
                        session_harness = create_harness(
                            pc, role_cfg, harness_name
                        )
                        session_agent = await _agent_factory(
                            session_harness, pc, role_cfg,
                            persona_reg, http_client,
                        )
                        return session_harness, session_agent

                    mcp_role_names = role_reg.available_for_persona(pc)
                    mcp_role_cfgs = [
                        role_reg.load(n, pc) for n in mcp_role_names
                    ]
                    mcp_state = build_mcp_state(
                        pc,
                        mcp_role_cfgs,
                        session_factory=_mcp_session_factory,
                        default_role=role,
                    )
                    app.state.mcp = mcp_state
                    await stack.enter_async_context(
                        mcp_state.session_manager.run()
                    )
                yield
        finally:
            # P10 extension-lifecycle: run extension shutdown() hooks
            # on server teardown. Idempotent + safe when the injected
            # _agent_factory never loaded extensions (empty active
            # list → no-op).
            await persona_reg.shutdown_extensions()
            if http_client is not None:
                await http_client.aclose()

    app = FastAPI(title="agentic-assistant AG-UI bridge", lifespan=_lifespan)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        detail = errors[0]["msg"] if errors else "Validation error"
        return _problem_response(detail, status=422)

    from assistant.web.routes import register_routes
    register_routes(app)

    if enable_a2a:
        from assistant.a2a.server import register_a2a_routes
        register_a2a_routes(app)

    if enable_mcp:
        from assistant.mcp.server import MCP_PATH

        async def _mcp_asgi(scope, receive, send) -> None:
            # The session manager is constructed (and its run() context
            # entered) by the lifespan above; the mount forwards raw
            # ASGI so streamable-HTTP semantics stay SDK-owned.
            await app.state.mcp.session_manager.handle_request(
                scope, receive, send
            )

        app.mount(MCP_PATH, _mcp_asgi)

    return app
