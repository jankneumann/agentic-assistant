"""Route definitions for the AG-UI bridge.

Routes:
  POST /chat  — SSE stream of AG-UI events (text/event-stream)
  GET  /health — liveness probe with persona/role/harness identity

Design decisions: D2 (SSE), D4 (single thread_id per process),
D8 (two-phase error contract absorbed by mapper).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from assistant.transports.ag_ui.mapper import map_harness_to_ag_ui
from assistant.transports.ag_ui.types import RunErrorEvent


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32768)


def register_routes(app: FastAPI) -> None:
    """Register /chat and /health on the given FastAPI app."""

    @app.post("/chat")
    async def chat(request: ChatRequest, req: Request) -> EventSourceResponse:
        harness = req.app.state.harness
        agent = req.app.state.agent

        async def _generate() -> AsyncIterator[str]:
            # ``aclosing`` guarantees the harness's underlying generator
            # (LangGraph stream / MSAF stream) is finalized on client
            # disconnect, abnormal termination, or normal completion —
            # without it, mid-stream cancellation can leave the upstream
            # iterator un-drained.
            async with aclosing(harness.astream_invoke(agent, request.message)) as hs:
                try:
                    async for evt in map_harness_to_ag_ui(
                        hs, thread_id=harness.thread_id
                    ):
                        # by_alias + exclude_none keeps the SSE payloads in
                        # the AG-UI camelCase shape (threadId, runId,
                        # messageId, toolCallId) and drops null upstream
                        # fields the contract schema declares as
                        # additionalProperties=false.
                        yield evt.model_dump_json(by_alias=True, exclude_none=True)
                except Exception as exc:
                    # The mapper only propagates exceptions when the harness
                    # raised WITHOUT yielding a Phase-1 terminal
                    # RunFinished(error=...). Synthesize a terminal
                    # RUN_ERROR so SSE consumers always see a final event,
                    # honoring D8's "every failure path ends with a
                    # terminal event" requirement even for misbehaving
                    # harnesses. Class-name only per D8 redaction rule.
                    cls_name = type(exc).__name__
                    err = RunErrorEvent(message=cls_name, code=cls_name)
                    yield err.model_dump_json(by_alias=True, exclude_none=True)

        # Cache-Control + X-Accel-Buffering prevent reverse-proxy buffering
        # (nginx default-buffers SSE bodies which breaks real-time delivery).
        return EventSourceResponse(
            _generate(),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/health")
    async def health(req: Request) -> dict:
        return {
            "persona": req.app.state.persona,
            "role": req.app.state.role,
            "harness": req.app.state.harness_name,
        }
