"""Capability type definitions — Task 1.2.

Dataclasses for capability protocol inputs, outputs, and the assembled
CapabilitySet that harnesses receive.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from assistant.core.capabilities.context import ContextProvider
    from assistant.core.capabilities.guardrails import GuardrailProvider
    from assistant.core.capabilities.memory import MemoryPolicy
    from assistant.core.capabilities.sandbox import SandboxProvider
    from assistant.core.capabilities.tools import ToolPolicy


class RiskLevel(enum.IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ActionRequest:
    action_type: str
    resource: str
    persona: str
    role: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionDecision:
    allowed: bool
    reason: str = ""
    require_confirmation: bool = False


@dataclass
class SandboxConfig:
    isolation_type: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    work_dir: Path
    isolation_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryScoping:
    per_persona: bool = True
    per_role: bool = False
    per_session: bool = False


@dataclass
class MemoryConfig:
    backend_type: str
    config: dict[str, Any] = field(default_factory=dict)
    scoping: MemoryScoping = field(default_factory=MemoryScoping)


@dataclass
class CapabilitySet:
    guardrails: GuardrailProvider
    sandbox: SandboxProvider
    memory: MemoryPolicy
    tools: ToolPolicy
    context: ContextProvider | None = None
