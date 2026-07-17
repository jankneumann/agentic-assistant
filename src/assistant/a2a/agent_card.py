"""AgentCard builder — persona + roles → A2A agent card.

One A2A skill per role enabled for the persona (``RoleRegistry.
available_for_persona``): skill ``id`` is the role name, skill ``name``
the role's display name, description straight from ``role.yaml``. The
card advertises ``capabilities.streaming=true`` (message/stream is
implemented) and JSONRPC as the preferred transport at ``{base_url}/a2a/v1``.

Auth: no ``securitySchemes`` yet — the server binds loopback-only by
default (web-server posture); agent-card auth declarations arrive with
P25 ``agent-iam``.
"""

from __future__ import annotations

from importlib import metadata

from assistant.a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig

# JSON-RPC endpoint mount point, relative to the served base URL.
A2A_RPC_MOUNT = "/a2a/v1"


def _package_version() -> str:
    try:
        return metadata.version("assistant")
    except metadata.PackageNotFoundError:  # pragma: no cover - editable envs
        return "0.0.0"


def build_agent_card(
    persona: PersonaConfig,
    roles: list[RoleConfig],
    *,
    base_url: str,
    version: str | None = None,
    streaming: bool = True,
) -> AgentCard:
    """Build the A2A agent card for a persona and its enabled roles.

    Args:
        persona: The bound persona (execution boundary).
        roles: Role configs enabled for the persona — one A2A skill each.
        base_url: Externally reachable server base (e.g.
            ``http://127.0.0.1:8765``); the card's ``url`` appends the
            JSON-RPC mount ``/a2a/v1``.
        version: Overrides the package version string when given.
        streaming: Advertised ``capabilities.streaming`` value.
    """
    display = persona.display_name or persona.name
    skills = [
        AgentSkill(
            id=role.name,
            name=role.display_name or role.name,
            description=role.description,
            tags=["role"],
        )
        for role in roles
    ]
    return AgentCard(
        name=display,
        description=(
            f"agentic-assistant persona '{persona.name}' — roles are "
            "exposed as A2A skills; delegate tasks via message/send or "
            "message/stream."
        ),
        url=base_url.rstrip("/") + A2A_RPC_MOUNT,
        version=version or _package_version(),
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=False,
            state_transition_history=False,
        ),
        skills=skills,
    )
