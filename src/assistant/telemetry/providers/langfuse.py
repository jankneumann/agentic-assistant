"""LangfuseProvider — native Langfuse SDK adapter.

The provider lazy-imports ``langfuse`` inside :meth:`setup` so the
factory's level-2 degradation (``ImportError``) and level-3
degradation (init exception) paths can both be handled cleanly. The
factory wraps ``setup()`` in a try/except; if the import or init
raises, the factory falls back to :class:`NoopProvider` and emits a
single one-shot warning.

Sanitization runs at emission (D5): every ``trace_*`` method calls
:func:`sanitize_mapping` on its ``metadata`` argument before passing
it to the SDK so secrets never reach the backend even if a hook site
forgets to scrub. The ``messages`` argument to :meth:`trace_llm_call`
is NOT run through the sanitizer — it is the LLM conversation input
that operators expect to see verbatim in the Langfuse UI for span
diagnosis. The 15-pattern regex chain targets secret-shaped tokens
(``Bearer …``, ``sk-…``, etc.) which would still get redacted if they
appeared in conversation, but free-form prose stays unmodified per
req observability.7's "every string value in span attributes,
metadata dicts, and error messages" scoping (which excludes
LLM-input fields).

Resilience (req observability.2 — "MUST never crash"):

Every emission path goes through :meth:`_emit_observation`, which
wraps the SDK ctx-mgr + per-op flush in a single try/except. Any
SDK-side failure (network down, auth error, malformed payload) is
logged at WARNING and swallowed so the application never sees an
exception caused by telemetry. The same protection applies to the
top-level :meth:`flush` and :meth:`shutdown` methods.

Flush semantics (D6):

- ``LANGFUSE_FLUSH_MODE=shutdown`` (default) — no per-op flush;
  buffered events drain when the factory's atexit handler fires.
- ``LANGFUSE_FLUSH_MODE=per_op`` — every ``trace_*`` method calls
  ``self._client.flush()`` before returning. Higher latency, no
  buffer-on-crash loss.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from assistant.telemetry.providers.base import _validate_op, _validate_tool_kind
from assistant.telemetry.sanitize import sanitize, sanitize_mapping

if TYPE_CHECKING:
    from assistant.telemetry.config import TelemetryConfig

logger = logging.getLogger("assistant.telemetry")


class LangfuseProvider:
    """Native Langfuse SDK adapter (lazy import)."""

    name: str = "langfuse"

    def __init__(self, config: TelemetryConfig) -> None:
        self._config = config
        self._client: Any | None = None  # populated by setup()

    def setup(self, app: Any = None) -> None:
        """Lazy-import ``langfuse`` and construct the SDK client.

        ImportError or any other exception propagates so the factory's
        3-level degradation can return a NoopProvider in its place.
        Per Context7-verified Langfuse Python SDK v3 API, the client
        constructor takes ``base_url`` (not ``host``) for the API host.
        """
        from langfuse import Langfuse  # type: ignore[import-not-found, unused-ignore]

        self._client = Langfuse(
            public_key=self._config.public_key,
            secret_key=self._config.secret_key,
            base_url=self._config.host,
            environment=self._config.environment,
            sample_rate=self._config.sample_rate,
        )

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _sanitise_md(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        return sanitize_mapping(metadata)

    def _emit_observation(
        self,
        *,
        name: str,
        as_type: str,
        metadata: dict[str, Any],
        **extra: Any,
    ) -> None:
        """Open a Langfuse observation and (per-op mode) flush, safely.

        Per req observability.2, the application MUST NEVER crash due
        to telemetry. Any SDK-side exception (network down, auth
        failed, malformed payload, partial outage) is caught here,
        logged once at WARNING, and swallowed. The span is dropped on
        failure rather than partially emitted.

        ``metadata`` is set at observation creation time; we do NOT
        also call ``obs.update(metadata=...)`` inside the ctx-mgr
        because that is redundant — the same metadata dict was already
        attached by ``start_as_current_observation``.

        Caller contract: only invoke after checking ``self._client is
        not None`` — the trace_* methods all guard that. The local
        ``client`` rebind below makes the not-None invariant visible
        to type checkers.
        """
        client = self._client
        if client is None:
            return
        try:
            with client.start_as_current_observation(
                name=name,
                as_type=as_type,
                metadata=metadata,
                **extra,
            ):
                pass
            if self._config.flush_mode == "per_op":
                client.flush()
        except Exception as exc:
            logger.warning(
                "Telemetry: Langfuse emission for span %r failed "
                "(%s: %s); span dropped, continuing without raising.",
                name,
                type(exc).__name__,
                exc,
            )

    # ── Protocol methods ───────────────────────────────────────────

    def trace_llm_call(
        self,
        *,
        model: str,
        persona: str | None,
        role: str | None,
        messages: list[dict[str, Any]] | None,
        input_tokens: int | None,
        output_tokens: int | None,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._client is None:
            return None
        md = self._sanitise_md(metadata)
        md.update(
            {
                "persona": persona,
                "role": role,
                "duration_ms": duration_ms,
            }
        )
        usage: dict[str, int] = {}
        if input_tokens is not None:
            usage["prompt_tokens"] = int(input_tokens)
        if output_tokens is not None:
            usage["completion_tokens"] = int(output_tokens)
        if usage:
            usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                "completion_tokens", 0
            )

        self._emit_observation(
            name="llm_call",
            as_type="generation",
            metadata=md,
            model=model,
            input=messages,
            usage_details=usage or None,
        )
        return None

    def trace_delegation(
        self,
        *,
        parent_role: str | None,
        sub_role: str,
        task: str,
        persona: str | None,
        duration_ms: float,
        outcome: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._client is None:
            return None
        md = self._sanitise_md(metadata)
        md.update(
            {
                "parent_role": parent_role,
                "sub_role": sub_role,
                "persona": persona,
                "duration_ms": duration_ms,
                "outcome": outcome,
            }
        )
        self._emit_observation(
            name="delegation",
            as_type="agent",
            metadata=md,
            input={"task": sanitize(task)},
        )
        return None

    def trace_tool_call(
        self,
        *,
        tool_name: str,
        tool_kind: str,
        persona: str | None,
        role: str | None,
        duration_ms: float,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _validate_tool_kind(tool_kind)
        if self._client is None:
            return None
        md = self._sanitise_md(metadata)
        md.update(
            {
                "tool_name": tool_name,
                "tool_kind": tool_kind,
                "persona": persona,
                "role": role,
                "duration_ms": duration_ms,
            }
        )
        if error:
            md["error"] = error
        self._emit_observation(
            name=f"tool:{tool_name}",
            as_type="tool",
            metadata=md,
        )
        return None

    def trace_memory_op(
        self,
        *,
        op: str,
        target: str | None,
        persona: str | None,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        _validate_op(op)
        if self._client is None:
            return None
        md = self._sanitise_md(metadata)
        md.update(
            {
                "op": op,
                "persona": persona,
                "duration_ms": duration_ms,
            }
        )
        if target is not None:
            md["target"] = sanitize(target)
        self._emit_observation(
            name=f"memory:{op}",
            as_type="span",
            metadata=md,
        )
        return None

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        """Open an arbitrary named span (escape hatch).

        Unlike the four first-class ``trace_*`` methods this ctx-mgr
        yields the underlying observation to the caller and runs user
        code inside the ``with`` block. If the SDK enter fails we log
        and fall back to yielding ``None`` so the caller can continue.
        Exceptions from the user code itself propagate unchanged so
        callers can still react to their own failures.
        """
        if self._client is None:
            yield None
            return
        attrs = self._sanitise_md(attributes)
        try:
            cm = self._client.start_as_current_observation(
                name=name,
                as_type="span",
                metadata=attrs,
            )
            obs = cm.__enter__()
        except Exception as exc:
            logger.warning(
                "Telemetry: Langfuse start_span %r enter failed "
                "(%s: %s); yielding None as fallback.",
                name,
                type(exc).__name__,
                exc,
            )
            yield None
            return
        # Forward exception info to ``cm.__exit__`` so the Langfuse SDK
        # can mark the span as failed when the user's code inside the
        # ``with`` block raises. Iter-2 round-2 fix (claude #2): the
        # previous implementation always passed ``(None, None, None)``,
        # erasing the failure signal at the SDK boundary.
        exc_info: tuple[Any, Any, Any] = (None, None, None)
        try:
            yield obs
        except BaseException as e:
            exc_info = (type(e), e, e.__traceback__)
            raise
        finally:
            try:
                cm.__exit__(*exc_info)
            except Exception as exit_exc:
                logger.warning(
                    "Telemetry: Langfuse start_span %r exit failed "
                    "(%s: %s); ignored.",
                    name,
                    type(exit_exc).__name__,
                    exit_exc,
                )

    def flush(self) -> None:
        if self._client is None:
            return None
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning(
                "Telemetry: Langfuse flush failed (%s: %s); ignored.",
                type(exc).__name__,
                exc,
            )

    def shutdown(self) -> None:
        if self._client is None:
            return None
        try:
            self._client.shutdown()
        except Exception:
            # During interpreter shutdown the SDK may have already
            # released network resources; never let the atexit hook
            # propagate.
            logger.debug("LangfuseProvider.shutdown raised — ignoring")
