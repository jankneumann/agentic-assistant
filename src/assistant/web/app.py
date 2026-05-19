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
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleRegistry
from assistant.harnesses.base import HostHarnessAdapter
from assistant.harnesses.factory import create_harness

AgentFactory = Callable[[Any, Any, Any, PersonaRegistry], Awaitable[Any]]


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
    harness: Any, pc: Any, rc: Any, persona_reg: PersonaRegistry
) -> Any:
    """Run the same tool/extension/agent setup pipeline as ``assistant run``.

    Lazy-imports the capability + tool-discovery machinery so the
    privacy-boundary test for the telemetry subtree stays clean (no
    eager FastAPI-adjacent imports in the assistant.web module).
    """
    from assistant.core.capabilities.resolver import CapabilityResolver
    from assistant.http_tools import HttpToolRegistry
    from assistant.http_tools.discovery import discover_tools

    extensions = persona_reg.load_extensions(pc)

    tool_sources = getattr(pc, "tool_sources", None) or {}
    if tool_sources:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            verify=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        ) as client:
            registry = await discover_tools(tool_sources, client=client)
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
        agent = await _agent_factory(harness, pc, rc, persona_reg)
        app.state.harness = harness
        app.state.agent = agent
        app.state.persona = persona
        app.state.role = role
        app.state.harness_name = harness_name
        yield

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

    return app
