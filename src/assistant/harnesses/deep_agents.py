"""Deep Agents harness adapter."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from assistant.core.composition import compose_system_prompt
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter


class DeepAgentsHarness(HarnessAdapter):
    def name(self) -> str:
        return "deep_agents"

    async def create_agent(
        self, tools: list[Any], extensions: list[Any]
    ) -> Any:
        cfg = self.persona.harnesses.get("deep_agents", {}) or {}
        model_id = cfg.get("model", "anthropic:claude-sonnet-4-20250514")

        ext_tools: list[Any] = []
        for ext in extensions:
            ext_tools.extend(ext.as_langchain_tools())

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

    async def invoke(self, agent: Any, message: str) -> str:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        for msg in reversed(result.get("messages", [])):
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
