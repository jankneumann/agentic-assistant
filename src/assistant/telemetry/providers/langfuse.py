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
forgets to scrub.

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
from contextlib import AbstractContextManager, contextmanager
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
        from langfuse import Langfuse  # type: ignore[import-not-found]

        self._client = Langfuse(
            public_key=self._config.public_key,
            secret_key=self._config.secret_key,
            base_url=self._config.host,
            environment=self._config.environment,
            sample_rate=self._config.sample_rate,
        )

    # ── helpers ────────────────────────────────────────────────────

    def _maybe_flush(self) -> None:
        if self._config.flush_mode == "per_op" and self._client is not None:
            self._client.flush()

    @staticmethod
    def _sanitise_md(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        return sanitize_mapping(metadata)

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

        with self._client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=model,
            input=messages,
            metadata=md,
            usage_details=usage or None,
        ) as obs:
            # The duration is captured as metadata; the Langfuse SDK
            # will compute its own elapsed time from the ctx-manager
            # entry/exit, but we surface our measurement explicitly so
            # callers see the exact number we measured.
            obs.update(metadata=md)
        self._maybe_flush()
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
        with self._client.start_as_current_observation(
            name="delegation",
            as_type="agent",
            input={"task": sanitize(task)},
            metadata=md,
        ) as obs:
            obs.update(metadata=md)
        self._maybe_flush()
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
        with self._client.start_as_current_observation(
            name=f"tool:{tool_name}",
            as_type="tool",
            metadata=md,
        ) as obs:
            obs.update(metadata=md)
        self._maybe_flush()
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
        with self._client.start_as_current_observation(
            name=f"memory:{op}",
            as_type="span",
            metadata=md,
        ) as obs:
            obs.update(metadata=md)
        self._maybe_flush()
        return None

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        if self._client is None:
            yield None
            return
        attrs = self._sanitise_md(attributes)
        with self._client.start_as_current_observation(
            name=name,
            as_type="span",
            metadata=attrs,
        ) as obs:
            yield obs

    def flush(self) -> None:
        if self._client is None:
            return None
        self._client.flush()

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


def __getattr__(name: str) -> AbstractContextManager[Any]:  # pragma: no cover
    """Module-level placeholder so test imports succeed even before setup."""
    raise AttributeError(name)
