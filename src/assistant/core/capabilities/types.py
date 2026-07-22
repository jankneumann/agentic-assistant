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
    from assistant.core.capabilities.identity import AgentIdentity
    from assistant.core.capabilities.memory import MemoryPolicy
    from assistant.core.capabilities.models import ModelProvider
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
    # P25 agent-iam: the acting principal, when the call site knows it.
    # Optional with default None so every pre-P25 construction site
    # keeps working unchanged. When present, guardrail decisions become
    # attributable (identity-aware policies + audit records).
    identity: AgentIdentity | None = None


@dataclass
class ActionDecision:
    allowed: bool
    reason: str = ""
    require_confirmation: bool = False


#: Codex policy vocabulary for the filesystem plane (protocol-standards
#: matrix 2026-07-16: adopt Codex's named levels — proven, human-legible).
FILESYSTEM_LEVELS = ("read-only", "workspace-write", "full-access")


@dataclass(frozen=True)
class SandboxMount:
    """One explicit filesystem mount declared on the filesystem plane."""

    host_path: str
    sandbox_path: str
    writable: bool = False


@dataclass(frozen=True)
class FilesystemPlane:
    """Filesystem plane — named access level + explicit mounts.

    ``workspace-write`` grants writes only inside the execution
    context's ``work_dir`` and declared writable mounts (sandbox-
    provider spec, SandboxConfig v2).
    """

    level: str = "full-access"
    mounts: tuple[SandboxMount, ...] = ()

    def __post_init__(self) -> None:
        if self.level not in FILESYSTEM_LEVELS:
            raise ValueError(
                f"filesystem plane: level {self.level!r} is not one of "
                f"{list(FILESYSTEM_LEVELS)}."
            )


@dataclass(frozen=True)
class NetworkPlane:
    """Network plane — deny-by-default egress with an explicit allow-list.

    An empty ``allow`` list means no network at all. ``proxy`` is an
    optional endpoint through which allowed egress is routed.
    """

    allow: tuple[str, ...] = ()
    proxy: str | None = None


@dataclass(frozen=True)
class CredentialsPlane:
    """Credentials plane — explicit secret visibility set.

    Only the listed ``CredentialProvider`` refs are observable inside
    the sandbox; there is no ambient environment inheritance.
    """

    visible: tuple[str, ...] = ()


@dataclass
class SandboxConfig:
    """Sandbox posture — legacy fields + the v2 three planes.

    Omitted planes (``None``) default to the permissive legacy
    behavior so pre-v2 configurations remain valid (sandbox-provider
    spec, "Omitted planes preserve legacy behavior").
    """

    isolation_type: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)
    filesystem: FilesystemPlane | None = None
    network: NetworkPlane | None = None
    credentials: CredentialsPlane | None = None

    def declared_planes(self) -> dict[str, Any]:
        """JSON-ish summary of the declared planes (for observability).

        Consumed by ``PassthroughSandbox`` (carry-without-enforce) and
        ``ContainerSandboxProvider`` (context metadata).
        """
        planes: dict[str, Any] = {}
        if self.filesystem is not None:
            planes["filesystem"] = {
                "level": self.filesystem.level,
                "mounts": [
                    {
                        "host_path": m.host_path,
                        "sandbox_path": m.sandbox_path,
                        "writable": m.writable,
                    }
                    for m in self.filesystem.mounts
                ],
            }
        if self.network is not None:
            planes["network"] = {
                "allow": list(self.network.allow),
                "proxy": self.network.proxy,
            }
        if self.credentials is not None:
            planes["credentials"] = {
                "visible": list(self.credentials.visible),
            }
        return planes


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
    # Capability slot #6 (capability-resolver spec / P19
    # model-provider-routing). ``None`` only when a CapabilitySet is
    # hand-assembled outside the resolver; the resolver always fills it.
    models: ModelProvider | None = None
