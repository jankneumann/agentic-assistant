"""Telemetry module for the assistant.

This module is **outbound-only**: it never exposes inbound HTTP, gRPC,
webhook, or message-queue interfaces. All communication with external
observability backends (currently Langfuse) is performed through the
backend vendor's own outbound HTTP SDK. See ``observability`` spec
requirement "No Inbound Interfaces" for the security rationale and
the constraints this places on future provider implementations.

Public surface:

- :func:`get_observability_provider` — lazily-initialised singleton
  that returns a noop provider when telemetry is disabled or
  unavailable (3-level graceful degradation, design D2).
- :class:`ObservabilityProvider` — Protocol every concrete provider
  satisfies (the ``noop`` provider ships in-tree; ``langfuse`` lives
  behind the optional ``[telemetry]`` extra).
- :func:`set_assistant_ctx` / :func:`get_assistant_ctx` /
  :func:`assistant_ctx` — ``contextvars``-backed helpers for
  propagating ``(persona, role)`` to span emission sites without
  threading them through every method signature (design D4).
"""

from __future__ import annotations

from assistant.telemetry.context import (
    assistant_ctx,
    get_assistant_ctx,
    set_assistant_ctx,
)
from assistant.telemetry.factory import get_observability_provider
from assistant.telemetry.providers.base import ObservabilityProvider

__all__ = [
    "ObservabilityProvider",
    "assistant_ctx",
    "get_assistant_ctx",
    "get_observability_provider",
    "set_assistant_ctx",
]
