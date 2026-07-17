"""Deep Agents harness adapter."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from assistant.core.capabilities.model_bindings import (
    ModelCallDeniedError,
    bind_langchain,
)
from assistant.core.capabilities.models import (
    DEFAULT_HARNESS_MODELS,
    ModelRef,
    ModelRequest,
    ModelResolutionError,
)
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
from assistant.harnesses.tool_adapters import render_langchain_tools
from assistant.telemetry.decorators import traced_harness

if TYPE_CHECKING:
    from assistant.core.capabilities.credentials import CredentialProvider
    from assistant.core.capabilities.guardrails import GuardrailProvider
    from assistant.core.capabilities.memory import MemoryPolicy
    from assistant.core.capabilities.models import ModelProvider

#: Memory snippet limit — mirrors the MSAF harness's D27 default of 10.
#: Tests can override via the ``memory_snippet_limit`` constructor kwarg.
DEFAULT_MEMORY_SNIPPET_LIMIT: int = 10

#: Section heading prepended to the composed prompt when memory
#: snippets are present (memory-retrieval-activation — parity with the
#: MSAF harness's D27 prepend).
_MEMORY_SECTION_HEADING: str = "## Recent context"


class DeepAgentsHarness(SdkHarnessAdapter):
    # Span-default model id, sourced from the shared harness-default
    # table that also seeds the synthesized registry (P19 verdict #3 —
    # registry-only). ``create_agent`` overrides ``self._active_model``
    # with the resolved ref's id so spans report what actually drove
    # ``init_chat_model``.
    _DEFAULT_MODEL = DEFAULT_HARNESS_MODELS["deep_agents"]

    def __init__(
        self,
        persona: PersonaConfig,
        role: RoleConfig,
        *,
        memory_policy: MemoryPolicy | None = None,
        memory_snippet_limit: int = DEFAULT_MEMORY_SNIPPET_LIMIT,
        model_provider: ModelProvider | None = None,
        credential_provider: CredentialProvider | None = None,
        guardrail_provider: GuardrailProvider | None = None,
    ) -> None:
        super().__init__(persona, role)
        self._memory_policy = memory_policy
        self._memory_snippet_limit = memory_snippet_limit
        self._model_provider = model_provider
        self._credential_provider = credential_provider
        self._guardrail_provider = guardrail_provider
        self._active_model: str = self._DEFAULT_MODEL
        # Resolved ModelRef backing ``_active_model`` — read by
        # ``@traced_harness`` for cost attribution (P19: pricing
        # metadata rides the existing span labels).
        self._active_model_ref: ModelRef | None = None
        # Synthesize a UUID at construction so ``thread_id`` is non-empty
        # and STABLE for the lifetime of this adapter instance (spec:
        # "thread_id must persist for the lifetime of the adapter instance
        # across multiple invoke / astream_invoke calls"). ``create_agent``
        # MUST NOT reassign this — IMPL_REVIEW round-1 gemini #5.
        self._thread_id: str = str(uuid4())

    def name(self) -> str:
        return "deep_agents"

    # ── Memory consumption (memory-retrieval-activation) ─────────────

    def _resolve_memory_policy(self) -> MemoryPolicy:
        """Return the injected MemoryPolicy or resolve via CapabilityResolver.

        Mirrors ``MSAgentFrameworkHarness._resolve_memory_policy`` so
        both SDK harnesses consume the same persona-selected policy
        (``PostgresGraphitiMemoryPolicy`` when ``database_url`` is
        configured, ``FileMemoryPolicy`` otherwise).
        """
        injected = getattr(self, "_memory_policy", None)
        if injected is not None:
            return injected
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        return resolver.resolve(self.persona, "sdk", self.role).memory

    # ── Model resolution (model-provider-routing) ─────────────────────

    def _resolve_model_provider(self) -> ModelProvider:
        """Return the injected ModelProvider or resolve slot #6.

        Registry-only (P19 verdict #3): the resolver hands back a
        :class:`RegistryModelProvider` — persona-declared or
        synthesized-default — and the harness selects its model via
        the ``ModelRequest.consumer`` binding lookup; no per-harness
        re-binding step exists.
        """
        if self._model_provider is not None:
            return self._model_provider
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        provider = resolver.resolve(self.persona, "sdk", self.role).models
        assert provider is not None  # resolver always fills slot #6
        return provider

    def _resolve_credential_provider(self) -> CredentialProvider:
        if self._credential_provider is not None:
            return self._credential_provider
        # P13 security-hardening: prefer the persona-scoped provider
        # built at persona load (persona .env first, process env
        # fallback) so model credential_refs resolve per-persona.
        persona_credentials = getattr(self.persona, "credentials", None)
        if persona_credentials is not None:
            return persona_credentials
        from assistant.core.capabilities.credentials import EnvCredentialProvider

        return EnvCredentialProvider()

    def _resolve_guardrail_provider(self) -> GuardrailProvider:
        if self._guardrail_provider is not None:
            return self._guardrail_provider
        from assistant.core.capabilities.resolver import CapabilityResolver

        resolver = CapabilityResolver()
        return resolver.resolve(self.persona, "sdk", self.role).guardrails

    def _build_model(self) -> Any:
        """Resolve + bind the chat model through the ModelProvider seam.

        Walks the ordered fallback chain: the first ``ModelRef`` whose
        LangChain binding constructs successfully wins; a guardrail
        denial (:class:`ModelCallDeniedError`) is a policy stop, not a
        provider failure, and propagates without trying fallbacks. The
        module-level ``init_chat_model`` import is passed through so
        the established test patch point keeps working.
        """
        provider = self._resolve_model_provider()
        refs = provider.resolve(ModelRequest(consumer=self.name()))
        credentials = self._resolve_credential_provider()
        guardrails = self._resolve_guardrail_provider()

        last_exc: Exception | None = None
        for ref in refs:
            try:
                model = bind_langchain(
                    ref,
                    credentials=credentials,
                    guardrails=guardrails,
                    persona=self.persona.name,
                    role=self.role.name,
                    init_fn=init_chat_model,
                )
            except ModelCallDeniedError:
                raise
            except Exception as exc:
                last_exc = exc
                continue
            self._active_model = ref.model_id or ref.name
            self._active_model_ref = ref
            return model
        raise ModelResolutionError(
            f"Every ModelRef in the resolved chain failed to bind: "
            f"{[r.name for r in refs]}."
        ) from last_exc

    async def _compose_system_prompt(self) -> str:
        """Compose system prompt + optional memory snippet block.

        Parity with the MSAF harness's D27 prepend: snippets from
        ``MemoryPolicy.get_recent_snippets`` are awaited directly on
        the ``create_agent`` event loop (capability-protocols-v2 owner
        review verdict C8, 2026-07-16 — no sync bridge on the hot
        path) and prepended under ``## Recent context``; an empty
        snippet list leaves the prompt unchanged (no heading injected).
        """
        base = compose_system_prompt(self.persona, self.role)
        snippets = await self._resolve_memory_policy().get_recent_snippets(
            self.persona, self.role, limit=self._memory_snippet_limit
        )
        if not snippets:
            return base
        snippet_block = "\n\n".join(snippets)
        return f"{_MEMORY_SECTION_HEADING}\n\n{snippet_block}\n\n{base}"

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
        # Model construction flows through the ModelProvider seam
        # (model-provider-routing, registry-only per P19 verdict #3):
        # the consumer binding selects a registry entry — persona
        # ``models:`` when declared, synthesized defaults otherwise.
        # ``_build_model`` stashes ``_active_model`` /
        # ``_active_model_ref`` so spans report the real id + pricing
        # metadata.
        model = self._build_model()

        # Spec harness-adapter "create_agent uses only the provided tool
        # list": ``tools`` is the complete, already-aggregated ToolSpec
        # list produced by ``ToolPolicy.authorized_tools()`` (extension
        # + HTTP tools, telemetry-wrapped upstream). The harness renders
        # it to the LangChain shape via the per-harness adapter and MUST
        # NOT re-derive, re-aggregate, or re-wrap tools from
        # ``extensions`` (P17 tool-spec migration removed the former
        # second aggregation site here).
        rendered_tools = render_langchain_tools(tools)

        skills_dirs: list[str] = ["./src/assistant/skills"]
        if self.role.skills_dir:
            skills_dirs.append(self.role.skills_dir)

        system_prompt = await self._compose_system_prompt()

        return create_deep_agent(
            model=model,
            tools=rendered_tools,
            system_prompt=system_prompt,
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
        response = ""
        for msg in reversed(messages):
            role = _msg_role(msg)
            if role == "assistant":
                response = _msg_content(msg)
                break
        # Post-turn capture (memory-retrieval-activation): best-effort,
        # error-swallowed — see SdkHarnessAdapter._capture_interaction.
        await self._capture_interaction(message, response)
        return response

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

        Tool-call lifecycle correlation: a per-stream ``open_tool_calls``
        dict maps LangGraph's upstream ``run_id`` to the emitted ``call_id``
        so ``on_tool_start`` / ``on_tool_args`` / ``on_tool_end`` always
        share the same ``call_id`` — even when the upstream ``run_id`` is
        falsy on either event (IMPL_REVIEW round-1 gemini #2).

        The upstream LangGraph stream is wrapped in ``contextlib.aclosing``
        so client disconnects propagate down to the SDK iterator's
        finalization path rather than leaving it pending until GC
        (IMPL_REVIEW round-2 gemini-r2-3).

        Implements the D8 two-phase error contract:
          Phase 1 — yield ``RunFinished(error=ClassName)`` before generator exit.
          Phase 2 — re-raise the original exception unchanged.

        The ``@traced_harness`` decorator intercepts the exception (Phase 2)
        for observability and re-raises so the mapper layer can absorb it.
        """
        run_id = str(uuid4())
        # Accumulated assistant text for post-turn memory capture on the
        # success path (memory-retrieval-activation).
        captured_text: list[str] = []
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
            inner_stream = agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                version="v2",
                config={"configurable": {"thread_id": self._thread_id}},
            )
            # aclosing the inner LangGraph stream so a mid-stream client
            # disconnect (GeneratorExit) closes the upstream iterator
            # instead of leaving it pending until garbage collection.
            # IMPL_REVIEW round-2 gemini-r2-3.
            async with aclosing(inner_stream) as event_stream:
                async for event in event_stream:
                    event_name: str = event.get("event", "")
                    data: dict[str, Any] = event.get("data", {}) or {}
                    tool_run_id: str = event.get("run_id", "") or ""
                    tool_name: str = event.get("name", "") or ""

                    if event_name == "on_chat_model_stream":
                        chunk = data.get("chunk")
                        if chunk is None:
                            continue
                        # Derive a stable message_id from the chunk's id or
                        # the model run_id — both are stable within a single
                        # message.
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
                        captured_text.append(text)
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
                        # UUID only if the upstream run_id was missing on
                        # both start AND end (a degenerate LangGraph emission).
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

        # Post-turn capture BEFORE the terminal RunFinished yield: once
        # the consumer sees RunFinished it may close the generator, and
        # code after the final yield would be skipped by GeneratorExit.
        # Success path only — errors and disconnects are not captured.
        await self._capture_interaction(message, "".join(captured_text))

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
        sub = DeepAgentsHarness(
            self.persona,
            role,
            memory_policy=self._memory_policy,
            memory_snippet_limit=self._memory_snippet_limit,
            model_provider=self._model_provider,
            credential_provider=self._credential_provider,
            guardrail_provider=self._guardrail_provider,
        )
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

