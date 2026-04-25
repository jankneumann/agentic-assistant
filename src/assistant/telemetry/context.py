"""Persona/role propagation via ``contextvars`` (D4).

ContextVar is task-local per PEP 567, so the assistant context
naturally:

- propagates across ``await`` boundaries within the same task;
- is isolated across distinct ``asyncio.Task`` instances;
- avoids the brittleness of ``threading.local`` (which doesn't
  cross awaits) and the global-mutable-state hazards of a module-
  level variable.

The delegation decorator uses :func:`assistant_ctx` as a context
manager to push the sub-role for the duration of a sub-agent run; on
exit the parent context is restored automatically.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# (persona, role) — both fields independently nullable. The default
# is the all-None pair so spans emitted before any explicit set still
# yield a deterministic shape.
_CURRENT_ASSISTANT_CTX: ContextVar[tuple[str | None, str | None]] = ContextVar(
    "assistant_ctx",
    default=(None, None),
)


def set_assistant_ctx(persona: str | None, role: str | None) -> None:
    """Replace the current ``(persona, role)`` context.

    Used by the CLI startup hook (wp-hooks task 2.7) once the persona
    + role are resolved. Tests reset to ``(None, None)`` between
    cases to keep state hygienic.
    """
    _CURRENT_ASSISTANT_CTX.set((persona, role))


def get_assistant_ctx() -> tuple[str | None, str | None]:
    """Return the current ``(persona, role)`` tuple."""
    return _CURRENT_ASSISTANT_CTX.get()


@contextmanager
def assistant_ctx(
    persona: str | None,
    role: str | None,
) -> Iterator[tuple[str | None, str | None]]:
    """Push a new context for the duration of the ``with`` block.

    On exit (normal or exceptional), the previous context is restored
    via the token returned by ``set``. This is the mechanism the
    delegation decorator uses to stamp the sub-role onto every span
    emitted by the sub-agent.
    """
    token = _CURRENT_ASSISTANT_CTX.set((persona, role))
    try:
        yield (persona, role)
    finally:
        _CURRENT_ASSISTANT_CTX.reset(token)
