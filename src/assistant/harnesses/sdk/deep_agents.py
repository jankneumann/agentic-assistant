"""Deep Agents harness adapter."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from assistant.core.composition import compose_system_prompt
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import SdkHarnessAdapter
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

    def name(self) -> str:
        return "deep_agents"

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
        )

    @traced_harness
    async def invoke(self, agent: Any, message: str) -> str:
        # Token usage is captured by the ``@traced_harness`` decorator
        # via LangChain Core's ``get_usage_metadata_callback`` context
        # manager — no instance-level stash is required, which keeps
        # concurrent ``asyncio.gather`` invocations isolated and
        # prevents prior-turn tokens from being summed once a
        # checkpointer-backed agent re-uses the same harness.
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        messages = result.get("messages", [])
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

