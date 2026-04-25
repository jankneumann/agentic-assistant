"""Deep Agents harness adapter."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from assistant.core.composition import compose_system_prompt
from assistant.core.role import RoleConfig
from assistant.harnesses.base import SdkHarnessAdapter
from assistant.telemetry.decorators import traced_harness
from assistant.telemetry.tool_wrap import wrap_extension_tools


class DeepAgentsHarness(SdkHarnessAdapter):
    def name(self) -> str:
        return "deep_agents"

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        cfg = self.persona.harnesses.get("deep_agents", {}) or {}
        model_id = cfg.get("model", "anthropic:claude-sonnet-4-20250514")

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
        )

    @traced_harness
    async def invoke(self, agent: Any, message: str) -> str:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        messages = result.get("messages", [])
        # Stash usage so the @traced_harness decorator can include token
        # counts in trace_llm_call (req observability.3 — "MUST include
        # input_tokens, output_tokens"). Records (0, 0) when the SDK does
        # not expose usage metadata so the decorator never has to pass
        # None for the spec-required fields.
        self._last_usage = _extract_usage(messages)
        for msg in reversed(messages):
            role = _msg_role(msg)
            if role == "assistant":
                return _msg_content(msg)
        return ""

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


def _msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "role", "") or ""


def _msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "") or ""


def _extract_usage(messages: list[Any]) -> tuple[int, int]:
    """Sum input/output token counts across all messages in the result.

    Walks every message and pulls token usage from whichever LangChain
    field carries it. Recent LangChain Core versions expose
    ``usage_metadata`` on ``AIMessage``; older releases stash usage
    under ``response_metadata.token_usage`` with the OpenAI-style
    ``prompt_tokens`` / ``completion_tokens`` keys. Returns ``(0, 0)``
    when no usage info is present so the harness can record a
    deterministic int pair regardless of SDK version (avoids passing
    ``None`` for the spec-required token fields per req
    observability.3).
    """
    in_tokens = 0
    out_tokens = 0
    for msg in messages:
        usage_meta = getattr(msg, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            in_tokens += int(usage_meta.get("input_tokens") or 0)
            out_tokens += int(usage_meta.get("output_tokens") or 0)
            continue
        resp_meta = getattr(msg, "response_metadata", None)
        if isinstance(resp_meta, dict):
            tu = resp_meta.get("token_usage") or {}
            if isinstance(tu, dict):
                in_tokens += int(tu.get("prompt_tokens") or 0)
                out_tokens += int(tu.get("completion_tokens") or 0)
    return in_tokens, out_tokens
