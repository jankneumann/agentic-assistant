"""Atexit shutdown helper + per-op flush mode detection.

The factory normally registers the active provider's ``shutdown``
method directly with :mod:`atexit` once, on first build (D6). This
module exposes a small helper layer for callers that want to register
additional shutdown callables (or that prefer to go through a single
named entry point) and a convenience ``is_per_op_mode()`` predicate
for callers that want to read the flush-mode env var without parsing
``LANGFUSE_FLUSH_MODE`` themselves.

Crash-time delivery (spec req observability.13):

The default ``shutdown`` flush mode loses buffered events if the
process is terminated by a signal that bypasses Python's :mod:`atexit`
machinery — SIGKILL, an uncatchable interpreter crash, or an
out-of-memory kill from the kernel. Users who require guaranteed
delivery SHALL set ``LANGFUSE_FLUSH_MODE=per_op`` and accept the
per-operation latency cost (every ``trace_*`` call performs a network
flush before returning). This tradeoff is also documented in
``docs/observability.md`` so operators can make an informed choice.
"""

from __future__ import annotations

import atexit
import os
from collections.abc import Callable

# Set of callables already passed to atexit.register, used to make
# register_shutdown_hook idempotent for the same callable. atexit
# itself does not deduplicate, so without this guard a caller that
# re-runs initialisation (in tests, in serverless cold-warm, etc.)
# would queue multiple shutdown invocations.
_registered_callables: set[Callable[[], None]] = set()


def register_shutdown_hook(fn: Callable[[], None]) -> None:
    """Register ``fn`` to run at process exit; idempotent per callable.

    This is a thin wrapper over :func:`atexit.register` that tracks
    the set of registered callables so the same one cannot be queued
    twice. The factory uses :func:`atexit.register` directly with the
    provider's ``shutdown`` method via its own singleton guard; this
    helper exists for callers that want a higher-level handle.
    """
    if fn in _registered_callables:
        return
    _registered_callables.add(fn)
    atexit.register(fn)


def is_per_op_mode() -> bool:
    """Return ``True`` iff ``LANGFUSE_FLUSH_MODE=per_op``.

    Used by ``LangfuseProvider`` to decide whether to call
    ``self._client.flush()`` after every ``trace_*`` invocation.
    Whitespace and case are ignored so ``  Per_Op  `` matches.
    """
    return os.environ.get("LANGFUSE_FLUSH_MODE", "").strip().lower() == "per_op"
