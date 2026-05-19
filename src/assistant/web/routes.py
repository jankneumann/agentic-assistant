"""Route definitions for the AG-UI bridge.

Routes:
  POST /chat  — SSE stream of AG-UI events (text/event-stream)
  GET  /health — liveness probe with persona/role/harness identity

Design decisions: D2 (SSE), D4 (single thread_id per process),
D8 (two-phase error contract absorbed by mapper).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from assistant.transports.ag_ui.mapper import map_harness_to_ag_ui


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32768)


def register_routes(app: FastAPI) -> None:
    """Register /chat and /health on the given FastAPI app."""

    @app.post("/chat")
    async def chat(request: ChatRequest, req: Request) -> EventSourceResponse:
        harness = req.app.state.harness

        async def _generate() -> AsyncIterator[str]:
            harness_stream = harness.astream_invoke(request.message)
            async for evt in map_harness_to_ag_ui(
                harness_stream, thread_id=harness.thread_id
            ):
                yield evt.model_dump_json()

        return EventSourceResponse(_generate())

    @app.get("/health")
    async def health(req: Request) -> dict:
        return {
            "persona": req.app.state.persona,
            "role": req.app.state.role,
            "harness": req.app.state.harness_name,
        }
