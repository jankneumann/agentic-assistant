"""Deep Agents harness adapter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from assistant.core.composition import compose_system_prompt
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.harnesses.sdk.events import (
    HarnessEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallStart,
)
from assistant.telemetry.decorators import traced_harness
from assistant.telemetry.tool_wrap import wrap_extension_tools


class DeepAgentsHarness(SdkHarnessAdapter):
    # Class-level default surfaces through ``_resolve_model`` so spans
    # report the real model id even when the persona omits a harness
    # ``model`` override (Iter-2 round-2 fix gemini #5). Concrete
    # ``create_agent`` overrides ``self._active_model`` with the value
    # that actually drove ``init_chat_model`` so the resolution order
    # is: instance attr (most specific) → persona config → "unknown".
    _DEFAULT_MODEL = "anthropic:claude-sonnet-4-20250514"

    def __init__(self, persona: PersonaConfig, role: RoleConfig) -> None:
        super().__init__(persona, role)
        self._active_model: str = self._DEFAULT_MODEL
        # Synthesize a UUID at construction so ``thread_id`` is non-empty
        # and STABLE for the lifetime of this adapter instance (spec:
        # "thread_id must persist for the lifetime of the adapter instance
        # across multiple invoke / astream_invoke calls"). ``create_agent``
        # MUST NOT reassign this — IMPL_REVIEW round-1 gemini #5.
        self._thread_id: str = str(uuid4())

    def name(self) -> str:
        return "deep_agents"

    @property
    def thread_id(self) -> str:
        """Stable conversation-thread identifier for this adapter instance.

        Synthesized once at ``__init__`` and never reassigned for the
        lifetime of this harness instance — the same value is used for every
        ``invoke`` and ``astream_invoke`` call so prior turns remain visible
        to the model via the InMemorySaver checkpointer (spec D4 / D3).
        """
        return self._thread_id

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        cfg = self.persona.harnesses.get("deep_agents", {}) or {}
        model_id = cfg.get("model", self._DEFAULT_MODEL)
        # Stash so ``_resolve_model`` reports the real id regardless of
        # whether the persona supplied a ``model`` override.
        self._active_model = model_id

        ext_tools: list[Any] = []
        for ext in extensions:
            # Wrap each extension's StructuredTools so they emit
            # ``trace_tool_call(tool_kind="extension", ...)`` per spec
            # capability-resolver "Aggregated Extension Tools Are Traced".
            ext_tools.extend(wrap_extension_tools(ext))

        skills_dirs: list[str] = ["./src/assistant/skills"]
        if self.role.skills_dir:
            skills_dirs.append(self.role.skills_dir)

        return create_deep_agent(
            model=init_chat_model(model_id),
            tools=[*tools, *ext_tools],
            system_prompt=compose_system_prompt(self.persona, self.role),
            memory=cfg.get("memory_files") or ["./AGENTS.md"],
            skills=skills_dirs,
            checkpointer=InMemorySaver(),
        )

    @traced_harness
    async def invoke(self, agent: Any, message: str) -> str:
        # The agent is constructed with an ``InMemorySaver`` checkpointer
        # in ``create_agent``; passing ``thread_id`` in ``configurable``
        # binds this invocation to the harness-lifetime conversation
        # thread so prior turns are visible to the model. Token usage is
        # captured by the ``@traced_harness`` decorator via LangChain
        # Core's ``get_usage_metadata_callback`` context manager, which
        # keeps concurrent invocations isolated and prevents prior-turn
        # tokens from being summed across the shared thread.
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": self._thread_id}},
        )
        messages = result.get("messages", [])
        for msg in reversed(messages):
            role = _msg_role(msg)
            if role == "assistant":
                return _msg_content(msg)
        return ""

    @traced_harness
    async def astream_invoke(
        self, agent: Any, message: str
    ) -> AsyncIterator[HarnessEvent]:
        """Stream a harness invocation as a sequence of HarnessEvent instances.

        Consumes ``agent.astream_events(version="v2")`` and translates
        LangChain event dicts into the harness-agnostic ``HarnessEvent``
        discriminated union per the D1 / D11 mapping table:

        - ``on_chat_model_stream`` → ``TextDelta``
        - ``on_tool_start``        → ``ToolCallStart`` + ``ToolCallArgs``
          (args serialized as JSON in a single chunk)
        - ``on_tool_end``          → ``ToolCallEnd``

        The ``run_id`` of the ``on_tool_start`` event is used as the
        ``call_id`` for the tool-call lifecycle events so all three variants
        share the same identifier without extra bookkeeping.

        Implements the D8 two-phase error contract:
          Phase 1 — yield ``RunFinished(error=ClassName)`` before generator exit.
          Phase 2 — re-raise the original exception unchanged.

        The ``@traced_harness`` decorator intercepts the exception (Phase 2)
        for observability and re-raises so the mapper layer can absorb it.
        """
        run_id = str(uuid4())
        # Per-stream mapping from LangGraph upstream run_id → our call_id.
        # Lets on_tool_end correlate with the call_id we emitted on the
        # matching on_tool_start, including when the upstream run_id is
        # empty for both events (then on_tool_start's synthesized UUID is
        # not stored but the upstream-consistent path still works for the
        # vast majority of LangGraph emissions). IMPL_REVIEW round-1 gemini #2.
        open_tool_calls: dict[str, str] = {}
        yield RunStarted(
            run_id=run_id,
            started_at=datetime.now(UTC).isoformat(),
        )
        try:
            async for event in agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                version="v2",
                config={"configurable": {"thread_id": self._thread_id}},
            ):
                event_name: str = event.get("event", "")
                data: dict[str, Any] = event.get("data", {}) or {}
                tool_run_id: str = event.get("run_id", "") or ""
                tool_name: str = event.get("name", "") or ""

                if event_name == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk is None:
                        continue
                    # Derive a stable message_id from the chunk's id or the
                    # model run_id — both are stable within a single message.
                    message_id: str = (
                        getattr(chunk, "id", None)
                        or tool_run_id
                        or "msg-unknown"
                    )
                    # content may be a str or a list of content blocks
                    raw_content = getattr(chunk, "content", "")
                    if isinstance(raw_content, list):
                        # Extract text from content blocks (ignore tool-use blocks)
                        text = "".join(
                            b.get("text", "") if isinstance(b, dict) else ""
                            for b in raw_content
                        )
                    else:
                        text = raw_content or ""
                    yield TextDelta(message_id=message_id, text=text)

                elif event_name == "on_tool_start":
                    call_id = tool_run_id or str(uuid4())
                    if tool_run_id:
                        # Remember the call_id so on_tool_end can correlate.
                        open_tool_calls[tool_run_id] = call_id
                    yield ToolCallStart(call_id=call_id, tool_name=tool_name)
                    # Serialize input args as a single JSON chunk per ToolCallArgs.
                    tool_input = data.get("input") or {}
                    yield ToolCallArgs(
                        call_id=call_id,
                        args_chunk=json.dumps(tool_input),
                    )

                elif event_name == "on_tool_end":
                    # Look up the start's call_id; fall back to a fresh
                    # UUID only if the upstream run_id was missing on both
                    # start AND end (a degenerate LangGraph emission).
                    if tool_run_id and tool_run_id in open_tool_calls:
                        call_id = open_tool_calls.pop(tool_run_id)
                    else:
                        call_id = str(uuid4())
                    output = data.get("output")
                    yield ToolCallEnd(call_id=call_id, result=output)

        except GeneratorExit:
            # Client disconnected mid-stream. Propagate unchanged so async
            # generator finalization (PEP 525) is honored. DO NOT synthesize
            # a terminal RunFinished here — yielding while handling
            # GeneratorExit raises RuntimeError per Python's generator
            # contract. IMPL_REVIEW round-1 claude #1.
            raise
        except Exception as exc:
            # Phase 1: yield terminal RunFinished with error class name only
            # (D8 redaction rule — no message body, no traceback). Catches
            # Exception (NOT BaseException) so GeneratorExit / CancelledError
            # / KeyboardInterrupt / SystemExit propagate without being
            # mis-mapped to a Phase-1 RunFinished(error=...).
            yield RunFinished(
                run_id=run_id,
                finished_at=datetime.now(UTC).isoformat(),
                error=type(exc).__name__,
            )
            # Phase 2: re-raise so @traced_harness can record the failure.
            raise

        yield RunFinished(
            run_id=run_id,
            finished_at=datetime.now(UTC).isoformat(),
        )

    async def spawn_sub_agent(
        self,
        role: RoleConfig,
        task: str,
        tools: list[Any],
        extensions: list[Any],
    ) -> str:
        sub = DeepAgentsHarness(self.persona, role)
        agent = await sub.create_agent(tools, extensions)
        return await sub.invoke(agent, task)


_LANGCHAIN_TO_CANONICAL_ROLE = {"ai": "assistant", "human": "user"}


def _msg_role(msg: Any) -> str:
    """Normalize message role across LangChain BaseMessage objects and
    raw dicts. LangChain ``AIMessage`` exposes ``type='ai'`` (no
    ``role`` attribute); Anthropic-style dicts expose ``role='assistant'``.
    Return the canonical Anthropic/OpenAI role name in both cases so
    downstream matching against ``"assistant"`` works regardless of
    upstream shape.
    """
    if isinstance(msg, dict):
        raw = msg.get("role") or msg.get("type") or ""
    else:
        raw = getattr(msg, "role", None) or getattr(msg, "type", "") or ""
    return _LANGCHAIN_TO_CANONICAL_ROLE.get(raw, raw)


def _msg_content(msg: Any) -> str:
    """Extract text content from a message. Anthropic models emit
    ``content`` as either a plain string OR a list of content blocks
    (``[{"type": "text", "text": ...}, {"type": "tool_use", ...}]``)
    when tool calls are interleaved with text. Concatenate text blocks
    in the list case so the REPL renders prose rather than a raw list
    repr.
    """
    raw = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(raw)

