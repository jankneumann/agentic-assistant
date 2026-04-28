"""Hook-integration decorators (D3 + D4).

This module is owned by ``wp-hooks``. It lives under
``assistant.telemetry`` for import clarity (so call sites can write
``from assistant.telemetry.decorators import traced_harness``), but
the wrapping logic is hook-specific and intentionally separate from
the ``wp-contracts`` module surface (``providers/``, ``factory``,
``config``, ``sanitize``, ``context``, ``flush_hook``).

Two public decorators:

- :func:`traced_harness` — wraps an ``async def invoke(self, agent,
  message)`` method on a concrete :class:`SdkHarnessAdapter` subclass.
  Emits exactly one ``trace_llm_call`` per invocation, after the
  awaited call completes (success or exception). The ``duration_ms``
  is measured around the ``await``. On exception, ``metadata={"error":
  type(exc).__name__}`` is recorded before re-raising — never both a
  pre- and post-call span.

- :func:`traced_delegation` — wraps an ``async def delegate(self,
  sub_role_name, task)`` method on :class:`DelegationSpawner`. Emits
  ``trace_delegation`` once per call with ``outcome="success"`` or
  ``outcome="error"``. Long ``task`` strings (> 256 chars) are
  replaced with ``"sha256:<16-char hex>"`` before emission. While the
  awaited body runs, ``assistant_ctx(persona, sub_role)`` is pushed so
  spans emitted by the sub-agent report the sub-role rather than the
  parent role. Concurrent delegations spawned via ``asyncio.gather``
  observe their own sub-role per PEP 567 task-local ``ContextVar``
  semantics.

Both decorators are safe under :class:`NoopProvider` — the provider's
methods are zero-allocation no-ops, so the only overhead is the
``time.perf_counter()`` pair plus the trace-method dispatch.
"""

from __future__ import annotations

import functools
import hashlib
import time
from collections.abc import Callable, Coroutine
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback

from assistant.telemetry.context import assistant_ctx, get_assistant_ctx
from assistant.telemetry.factory import get_observability_provider

# Spec: delegation-spawner — task hashing threshold is exactly 256.
_TASK_HASH_THRESHOLD = 256


def _hash_task(task: str) -> str:
    """Return ``"sha256:<16-char hex>"`` for tasks beyond the threshold.

    Tasks of 256 chars or fewer pass through unchanged.
    """
    if len(task) <= _TASK_HASH_THRESHOLD:
        return task
    digest = hashlib.sha256(task.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _resolve_persona_role(self_obj: Any) -> tuple[str | None, str | None]:
    """Best-effort persona/role resolution.

    Order:
    1. ``self.persona.name`` + (``self.role.name`` or ``self.parent_role.name``)
       if those attrs exist. ``DelegationSpawner`` uses ``parent_role`` rather
       than ``role`` so the harness decorator and the delegation decorator
       can share this helper.
    2. Fall back to the assistant ``ContextVar`` (D4) — this is the
       path used by tools and other call sites that aren't bound to a
       harness/spawner instance.
    """
    persona: str | None = None
    role: str | None = None
    p_obj = getattr(self_obj, "persona", None)
    r_obj = getattr(self_obj, "role", None)
    if r_obj is None:
        r_obj = getattr(self_obj, "parent_role", None)
    if p_obj is not None:
        persona = getattr(p_obj, "name", None)
    if r_obj is not None:
        role = getattr(r_obj, "name", None)
    if persona is None or role is None:
        ctx_persona, ctx_role = get_assistant_ctx()
        if persona is None:
            persona = ctx_persona
        if role is None:
            role = ctx_role
    return persona, role


def _resolve_model(self_obj: Any) -> str:
    """Pull the harness-configured model id from ``self.persona.harnesses``.

    Mirrors the lookup in :class:`DeepAgentsHarness.create_agent`.
    Resolution order:
    1. ``self._active_model`` — the harness's own active model id, set by
       concrete adapters at ``create_agent`` time so spans report the
       real default even when the persona omits a model override
       (Iter-2 round-2 fix gemini #5).
    2. ``self.persona.harnesses[<harness_name>].model`` — explicit
       per-persona override.
    3. ``"unknown"`` — final fallback so span emission never raises.
    """
    active = getattr(self_obj, "_active_model", None)
    if isinstance(active, str) and active:
        return active
    persona = getattr(self_obj, "persona", None)
    if persona is None:
        return "unknown"
    harnesses = getattr(persona, "harnesses", None) or {}
    if not isinstance(harnesses, dict):
        return "unknown"
    # Prefer the harness's own ``name()`` if available, else first
    # configured entry.
    harness_name_fn = getattr(self_obj, "name", None)
    candidates: list[str] = []
    if callable(harness_name_fn):
        try:
            candidates.append(harness_name_fn())
        except Exception:
            pass
    candidates.extend(harnesses.keys())
    for key in candidates:
        cfg = harnesses.get(key) or {}
        if isinstance(cfg, dict):
            model = cfg.get("model")
            if isinstance(model, str) and model:
                return model
    return "unknown"


def _sum_usage_metadata(usage_metadata: dict[str, Any]) -> tuple[int, int]:
    """Aggregate input/output tokens across every model entry in ``cb.usage_metadata``.

    LangChain Core's :func:`get_usage_metadata_callback` yields a
    callback whose ``usage_metadata`` is keyed by model name with
    per-model dicts of the form ``{"input_tokens": int,
    "output_tokens": int, "total_tokens": int, ...}``. A single deep-
    agents invocation may fan out across multiple model entries (tool
    sub-models, planner vs executor splits) so we sum across all keys
    to satisfy req observability.3 ("MUST include input_tokens,
    output_tokens"). Returns ``(0, 0)`` when no LLM call fired during
    the awaited block.
    """
    in_tok = 0
    out_tok = 0
    for entry in usage_metadata.values():
        if isinstance(entry, dict):
            in_tok += int(entry.get("input_tokens") or 0)
            out_tok += int(entry.get("output_tokens") or 0)
    return in_tok, out_tok


def traced_harness[R](
    fn: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Wrap a concrete ``SdkHarnessAdapter.invoke`` with one ``trace_llm_call``.

    Per the harness-adapter spec, this decorator MUST be applied to
    each concrete subclass — applying it to the abstract base is dead
    code because subclasses override ``invoke`` without ``super()``.

    Token usage is captured via LangChain Core's
    :func:`get_usage_metadata_callback` context manager. The callback
    is task-local (PEP 567 ``ContextVar`` semantics) so concurrent
    invocations spawned via ``asyncio.gather`` see independent counts,
    and only LLM calls fired *inside* the awaited body are counted —
    so once a checkpointer-backed agent re-uses the same harness
    instance across turns, prior-turn tokens are NOT double-counted
    (Iter-2 round-2 fix: gemini #2 race-condition + claude #1 multi-
    turn over-counting, both addressed by this single refactor).
    """

    @functools.wraps(fn)
    async def wrapper(self_obj: Any, *args: Any, **kwargs: Any) -> R:
        persona, role = _resolve_persona_role(self_obj)
        model = _resolve_model(self_obj)
        provider = get_observability_provider()
        in_tok = 0
        out_tok = 0
        start = time.perf_counter()
        try:
            with get_usage_metadata_callback() as cb:
                try:
                    result = await fn(self_obj, *args, **kwargs)
                finally:
                    # Read usage *before* the ctx-mgr exits; on the
                    # exception path this captures whatever LLM calls
                    # completed before the failure (best-effort).
                    in_tok, out_tok = _sum_usage_metadata(cb.usage_metadata)
        except BaseException as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            provider.trace_llm_call(
                model=model,
                persona=persona,
                role=role,
                messages=None,
                input_tokens=in_tok,
                output_tokens=out_tok,
                duration_ms=duration_ms,
                metadata={"error": type(exc).__name__},
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        provider.trace_llm_call(
            model=model,
            persona=persona,
            role=role,
            messages=None,
            input_tokens=in_tok,
            output_tokens=out_tok,
            duration_ms=duration_ms,
            metadata=None,
        )
        return result

    return wrapper


def traced_delegation[R](
    fn: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Wrap ``DelegationSpawner.delegate`` with one ``trace_delegation``.

    The decorator pushes ``assistant_ctx(persona, sub_role)`` for the
    duration of the awaited body so any span emitted *inside* the
    sub-agent reports ``role=sub_role``. After the body returns
    (success or exception) the parent context is restored via the
    context-manager's exit.
    """

    @functools.wraps(fn)
    async def wrapper(self_obj: Any, sub_role_name: str, task: str) -> R:
        persona, parent_role = _resolve_persona_role(self_obj)
        provider = get_observability_provider()
        emitted_task = _hash_task(task)
        start = time.perf_counter()
        try:
            with assistant_ctx(persona, sub_role_name):
                result = await fn(self_obj, sub_role_name, task)
        except BaseException as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            provider.trace_delegation(
                parent_role=parent_role,
                sub_role=sub_role_name,
                task=emitted_task,
                persona=persona,
                duration_ms=duration_ms,
                outcome="error",
                metadata={"error": type(exc).__name__},
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        provider.trace_delegation(
            parent_role=parent_role,
            sub_role=sub_role_name,
            task=emitted_task,
            persona=persona,
            duration_ms=duration_ms,
            outcome="success",
            metadata=None,
        )
        return result

    return wrapper


def trace_memory_op[R](
    op: str,
) -> Callable[[Callable[..., Coroutine[Any, Any, R]]], Callable[..., Coroutine[Any, Any, R]]]:
    """Decorator factory for instrumenting ``MemoryManager`` methods.

    Used in tasks 3.2/3.3 to apply one ``trace_memory_op`` per public
    method on :class:`MemoryManager` at ``src/assistant/core/memory.py``.

    The decorated method's first positional argument (after ``self``)
    is treated as the ``target`` (persona name for context/episode/
    interaction/export, key for fact_write, query for search). Targets
    longer than 256 chars are hashed via the same ``sha256:<16-char
    hex>`` convention used for delegation tasks.

    Per req observability.6 the span MUST be emitted exactly once even
    when the method internally invokes graphiti — graphiti calls are
    NOT separately instrumented.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, R]],
    ) -> Callable[..., Coroutine[Any, Any, R]]:
        @functools.wraps(fn)
        async def wrapper(self_obj: Any, *args: Any, **kwargs: Any) -> R:
            persona = args[0] if args else kwargs.get("persona")
            target_raw: Any
            if op == "fact_write":
                # store_fact(persona, key, value): target = key
                target_raw = args[1] if len(args) > 1 else kwargs.get("key")
            elif op == "search":
                # search(persona, query, ...): target = query
                target_raw = args[1] if len(args) > 1 else kwargs.get("query")
            else:
                # context / interaction_write / episode_write / export:
                # target = persona
                target_raw = persona

            target = _hash_task(str(target_raw)) if target_raw is not None else None
            provider = get_observability_provider()
            start = time.perf_counter()
            try:
                result = await fn(self_obj, *args, **kwargs)
            except BaseException as exc:
                duration_ms = (time.perf_counter() - start) * 1000.0
                provider.trace_memory_op(
                    op=op,
                    target=target,
                    persona=persona,
                    duration_ms=duration_ms,
                    metadata={"error": type(exc).__name__},
                )
                raise
            duration_ms = (time.perf_counter() - start) * 1000.0
            provider.trace_memory_op(
                op=op,
                target=target,
                persona=persona,
                duration_ms=duration_ms,
                metadata=None,
            )
            return result

        return wrapper

    return decorator


__all__ = ["trace_memory_op", "traced_delegation", "traced_harness"]
