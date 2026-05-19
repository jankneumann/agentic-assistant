"""FastAPI application factory for the AG-UI bridge.

Design decisions: D3 (single harness per process), D6 (import direction),
D8 (two-phase error contract handled by mapper).

Usage::

    from assistant.web.app import make_app
    app = make_app(persona="personal", role="assistant", harness_name="deep_agents")

The lifespan context manager constructs the harness once at startup and stores
it on ``app.state.harness``.  All ``/chat`` requests share the same instance.

Host harnesses (``HostHarnessAdapter``) are rejected at lifespan time because
they cannot satisfy the streaming contract.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleRegistry
from assistant.harnesses.base import HostHarnessAdapter
from assistant.harnesses.factory import create_harness


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


def make_app(persona: str, role: str, harness_name: str) -> FastAPI:
    """Build and return a configured FastAPI application.

    The lifespan constructs the harness exactly once (D3).  Raises
    ``ValueError`` if the resolved harness is a host harness or if the
    factory raises (e.g. harness disabled for the persona).

    Args:
        persona: Persona name (looked up via PersonaRegistry).
        role: Role name (looked up via RoleRegistry).
        harness_name: One of the registered SDK harness names.

    Returns:
        A FastAPI application with ``/chat`` (SSE) and ``/health`` routes,
        a custom RequestValidationError handler (RFC 7807), and the harness
        bound to ``app.state.harness`` after startup.
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
        app.state.harness = harness
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
