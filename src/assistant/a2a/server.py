"""A2A server surface — agent-card GET + JSON-RPC POST routes.

Routes (registered onto an existing FastAPI app by ``register_a2a_routes``;
the web app factory mounts them when ``assistant serve --a2a`` is used):

  GET  /.well-known/agent-card.json  — agent card (A2A ≥ 0.3.0 canonical)
  GET  /.well-known/agent.json       — same card (pre-0.3.0 legacy alias)
  POST /a2a/v1                       — JSON-RPC 2.0: message/send,
                                       message/stream (SSE)
  POST /a2a/v1/message:stream        — REST-style (HTTP+JSON transport)
                                       alias for message/stream; body is
                                       MessageSendParams, SSE events are
                                       bare A2A objects (no JSON-RPC
                                       envelope)

JSON-RPC conventions: every protocol-level failure is an HTTP 200 with a
``JSONRPCErrorResponse`` body (JSON-RPC-over-HTTP convention; A2A error
codes from ``assistant.a2a.types``). Task-level failures are NOT JSON-RPC
errors — the request succeeded, the task failed — so they surface as a
terminal ``failed`` status (message/send result / final stream event).

State: routes read an ``A2AServerState`` from ``request.app.state.a2a``,
which the web lifespan constructs via ``build_a2a_state`` (mirroring the
``web/routes.py`` register-then-populate pattern).
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from assistant.a2a.agent_card import build_agent_card
from assistant.a2a.task_handler import A2ATaskHandler
from assistant.a2a.types import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    A2AProtocolError,
    AgentCard,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCSuccessResponse,
    MessageSendParams,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.sessions import (
    DEFAULT_IDLE_TTL_SECONDS,
    RebindFactory,
    SessionFactory,
    SessionRegistry,
)

logger = logging.getLogger(__name__)

WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"
WELL_KNOWN_AGENT_JSON_PATH = "/.well-known/agent.json"  # legacy (< 0.3.0)
A2A_RPC_PATH = "/a2a/v1"
A2A_MESSAGE_STREAM_PATH = "/a2a/v1/message:stream"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


@dataclass
class A2AServerState:
    """Everything the A2A routes need, hung on ``app.state.a2a``.

    ``expected_token`` is the resolved inbound bearer token (P25
    agent-iam); ``None`` keeps the pre-P25 loopback-unauthenticated
    posture. Excluded from repr — it is a secret.
    """

    card: AgentCard
    registry: SessionRegistry
    handler: A2ATaskHandler
    expected_token: str | None = field(default=None, repr=False)


def build_a2a_state(
    persona: PersonaConfig,
    roles: list[RoleConfig],
    *,
    session_factory: SessionFactory,
    base_url: str,
    idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
    version: str | None = None,
    session_store: Any | None = None,
    rebind_factory: RebindFactory | None = None,
    serving_role: str = "",
    harness_name: str = "",
) -> A2AServerState:
    """Assemble card + registry + handler for one persona binding.

    P30 durable-sessions: ``session_store`` + ``rebind_factory`` make
    known-but-released ``contextId`` values resumable (the registry
    re-binds a fresh harness with the recorded thread_id; the durable
    checkpointer restores the conversation). Omitted → pure in-memory
    behavior, exactly as before.

    P25 agent-iam inbound auth: when the persona declares ``auth.a2a``
    the expected bearer token resolves through the persona's
    ``CredentialProvider`` (never raw ``os.environ``); a declared-but-
    unresolvable token FAILS startup (declared auth must never
    silently disable). Without a declaration the surface stays
    unauthenticated — current loopback behavior — with a startup
    WARNING so the posture is visible.
    """
    auth = getattr(persona, "a2a_auth", None)
    expected_token: str | None = None
    if auth is not None:
        expected_token = persona.credentials.get_credential(auth.token_env)
        if not expected_token:
            raise ValueError(
                f"Persona '{persona.name}' declares auth.a2a with "
                f"token_env '{auth.token_env}', but the ref resolved "
                f"empty. Set it in the persona .env, the process "
                f"environment, or the vault backend — or remove the "
                f"auth.a2a declaration to serve unauthenticated."
            )
    else:
        logger.warning(
            "A2A surface for persona '%s' is UNAUTHENTICATED (no "
            "auth.a2a declared) — safe only behind the default "
            "loopback binding. Declare auth.a2a: {type: bearer, "
            "token_env: ...} before exposing it beyond localhost.",
            persona.name,
        )
    registry = SessionRegistry(
        session_factory,
        idle_ttl_seconds=idle_ttl_seconds,
        store=session_store,
        rebind_factory=rebind_factory,
        persona=persona.name,
        role=serving_role,
        harness=harness_name,
        durable_ttl_seconds=float(
            getattr(
                getattr(persona, "sessions", None),
                "session_ttl_seconds",
                0.0,
            )
            or 0.0
        ),
    )
    return A2AServerState(
        card=build_agent_card(
            persona, roles, base_url=base_url, version=version, auth=auth
        ),
        registry=registry,
        handler=A2ATaskHandler(registry),
        expected_token=expected_token,
    )


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(by_alias=True, exclude_none=True, mode="json")


def _rpc_error(
    req_id: str | int | None, code: int, message: str
) -> JSONResponse:
    body = JSONRPCErrorResponse(
        id=req_id, error=JSONRPCError(code=code, message=message)
    )
    return JSONResponse(status_code=200, content=_dump(body))


def _auth_failure(state: A2AServerState, req: Request) -> JSONResponse | None:
    """Verify the inbound bearer token; ``None`` means authorized.

    P25 agent-iam: auth failures are HTTP-level (401 +
    ``WWW-Authenticate: Bearer``), NOT JSON-RPC errors — per the A2A
    spec, transport auth uses standard HTTP status codes and the
    request never reaches protocol handling. Comparison is
    constant-time (``secrets.compare_digest``). The agent card routes
    are deliberately NOT gated: the card is how clients discover the
    required scheme.
    """
    if state.expected_token is None:
        return None
    header = req.headers.get("authorization", "")
    scheme, _, credential = header.partition(" ")
    if scheme.lower() == "bearer" and secrets.compare_digest(
        credential.strip().encode(), state.expected_token.encode()
    ):
        return None
    return JSONResponse(
        status_code=401,
        content={
            "type": "about:blank",
            "title": "Unauthorized",
            "status": 401,
            "detail": (
                "This A2A surface requires a bearer token; see the "
                "agent card's securitySchemes."
            ),
        },
        media_type="application/problem+json",
        headers={"WWW-Authenticate": "Bearer"},
    )


def register_a2a_routes(app: FastAPI) -> None:
    """Register the A2A routes; they read ``app.state.a2a`` per request."""

    def _state(req: Request) -> A2AServerState:
        return req.app.state.a2a

    async def _agent_card(req: Request) -> JSONResponse:
        return JSONResponse(content=_dump(_state(req).card))

    # Canonical (A2A >= 0.3.0) and legacy well-known paths serve the
    # same card so pre-0.3 clients keep resolving us.
    app.add_api_route(
        WELL_KNOWN_AGENT_CARD_PATH, _agent_card, methods=["GET"]
    )
    app.add_api_route(
        WELL_KNOWN_AGENT_JSON_PATH, _agent_card, methods=["GET"]
    )

    @app.post(A2A_RPC_PATH)
    async def a2a_rpc(req: Request):
        state = _state(req)

        denied = _auth_failure(state, req)
        if denied is not None:
            return denied

        raw = await req.body()
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _rpc_error(None, PARSE_ERROR, "Invalid JSON payload")

        try:
            rpc = JSONRPCRequest.model_validate(payload)
        except ValidationError:
            req_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(req_id, (str, int)):
                req_id = None
            return _rpc_error(
                req_id, INVALID_REQUEST, "Invalid JSON-RPC request envelope"
            )

        if rpc.method not in ("message/send", "message/stream"):
            return _rpc_error(
                rpc.id, METHOD_NOT_FOUND, f"Unknown method '{rpc.method}'"
            )

        try:
            params = MessageSendParams.model_validate(rpc.params or {})
        except ValidationError as exc:
            first = exc.errors()[0]["msg"] if exc.errors() else "invalid params"
            return _rpc_error(rpc.id, INVALID_PARAMS, first)

        if rpc.method == "message/send":
            try:
                task = await state.handler.handle_message_send(params)
            except A2AProtocolError as exc:
                return _rpc_error(rpc.id, exc.code, exc.message)
            return JSONResponse(
                status_code=200,
                content=_dump(JSONRPCSuccessResponse(id=rpc.id, result=_dump(task))),
            )

        # message/stream — each SSE data line is a full JSON-RPC response
        # envelope whose result is one A2A event (JSONRPC transport rule).
        async def _generate() -> AsyncIterator[str]:
            stream = state.handler.handle_message_stream(params)
            async with aclosing(stream) as events:
                try:
                    async for event in events:
                        yield json.dumps(
                            _dump(
                                JSONRPCSuccessResponse(
                                    id=rpc.id, result=_dump(event)
                                )
                            )
                        )
                except A2AProtocolError as exc:
                    # Validation failures surface on first iteration —
                    # emit a JSON-RPC error envelope, then close.
                    yield json.dumps(_dump(JSONRPCErrorResponse(
                        id=rpc.id, error=exc.to_error(),
                    )))

        return EventSourceResponse(_generate(), headers=dict(_SSE_HEADERS))

    @app.post(A2A_MESSAGE_STREAM_PATH)
    async def a2a_message_stream_rest(params: MessageSendParams, req: Request):
        """REST-style alias (HTTP+JSON transport): bare A2A events."""
        state = _state(req)

        denied = _auth_failure(state, req)
        if denied is not None:
            return denied

        async def _generate() -> AsyncIterator[str]:
            stream = state.handler.handle_message_stream(params)
            async with aclosing(stream) as events:
                try:
                    async for event in events:
                        yield json.dumps(_dump(event))
                except A2AProtocolError as exc:
                    yield json.dumps(_dump(exc.to_error()))

        return EventSourceResponse(_generate(), headers=dict(_SSE_HEADERS))


__all__ = [
    "A2A_MESSAGE_STREAM_PATH",
    "A2A_RPC_PATH",
    "WELL_KNOWN_AGENT_CARD_PATH",
    "WELL_KNOWN_AGENT_JSON_PATH",
    "A2AServerState",
    "build_a2a_state",
    "register_a2a_routes",
]
