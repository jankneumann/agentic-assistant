"""Harness adapters: SDK (Deep Agents, MS Agent Framework) and Host (Claude Code).

Re-exports from sdk/ and host/ for backward compatibility during transition.
"""

from assistant.harnesses.base import (  # noqa: F401
    HarnessAdapter,
    HostHarnessAdapter,
    SdkHarnessAdapter,
)
from assistant.harnesses.sdk.deep_agents import DeepAgentsHarness  # noqa: F401
from assistant.harnesses.sdk.ms_agent_fw import MSAgentFrameworkHarness  # noqa: F401
