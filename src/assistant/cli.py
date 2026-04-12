"""CLI: persona-by-role-by-harness selection with REPL + /role + /delegate."""

from __future__ import annotations

import asyncio
import logging
import sys

import click

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import HarnessAdapter
from assistant.harnesses.factory import create_harness as _default_create_harness

logger = logging.getLogger(__name__)

# Test seam: tests may monkeypatch this to inject a stub harness factory.
_create_harness = _default_create_harness


@click.command()
@click.option("--persona", "-p", type=str, default=None, help="Persona name.")
@click.option("--role", "-r", type=str, default=None, help="Role name.")
@click.option(
    "--harness",
    "-H",
    type=click.Choice(["deep_agents", "ms_agent_framework"]),
    default="deep_agents",
    help="Harness backend.",
)
@click.option(
    "--list-personas",
    is_flag=True,
    help="List initialized persona submodules and exit.",
)
@click.option(
    "--list-roles",
    is_flag=True,
    help="List roles available for the selected persona and exit.",
)
def main(
    persona: str | None,
    role: str | None,
    harness: str,
    list_personas: bool,
    list_roles: bool,
) -> None:
    """Start the agentic-assistant."""
    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

    if list_personas:
        for p in persona_reg.discover():
            click.echo(p)
        return

    if list_roles:
        if not persona:
            raise click.UsageError("--list-roles requires -p/--persona.")
        pc = _load_persona_or_fail(persona_reg, persona)
        for r in role_reg.available_for_persona(pc):
            click.echo(r)
        return

    if not persona:
        raise click.UsageError("-p/--persona is required.")

    pc = _load_persona_or_fail(persona_reg, persona)
    role_name = role or pc.default_role
    try:
        rc = role_reg.load(role_name, pc)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    try:
        adapter = _create_harness(pc, rc, harness)
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    except NotImplementedError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    asyncio.run(_run_repl(persona_reg, role_reg, pc, rc, harness, adapter))


def _load_persona_or_fail(
    persona_reg: PersonaRegistry, name: str
):  # -> PersonaConfig
    try:
        return persona_reg.load(name)
    except ValueError as e:
        raise click.UsageError(str(e)) from e


async def _run_repl(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    rc: RoleConfig,
    harness_name: str,
    adapter: HarnessAdapter,
) -> None:
    click.echo(f"Persona:  {pc.display_name}")
    click.echo(f"Role:     {rc.display_name}")
    click.echo(f"Harness:  {harness_name}")

    if any(src.get("base_url") for src in pc.tool_sources.values()):
        click.echo(
            "  Tools:  HTTP tool discovery is deferred to P2; "
            "passing empty tool list."
        )

    extensions = persona_reg.load_extensions(pc)
    ext_names = [getattr(e, "name", "?") for e in extensions]
    click.echo(
        f"  Extensions: {len(extensions)}"
        f"{' (' + ', '.join(ext_names) + ')' if ext_names else ''}"
    )

    try:
        agent = await adapter.create_agent(tools=[], extensions=extensions)
    except NotImplementedError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(
        "\nCommands: /roles  /role <name>  /delegate <role> <task>  quit\n"
    )

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ", default="")
        except (click.exceptions.Abort, EOFError):
            break
        if user_input.lower() in ("quit", "exit"):
            break

        if user_input == "/roles":
            for r in role_reg.available_for_persona(pc):
                marker = " ←" if r == rc.name else ""
                click.echo(f"  {r}{marker}")
            continue

        if user_input.startswith("/role "):
            new_role = user_input.split(" ", 1)[1].strip()
            try:
                new_rc = role_reg.load(new_role, pc)
                new_adapter = _create_harness(pc, new_rc, harness_name)
                new_agent = await new_adapter.create_agent(
                    tools=[], extensions=extensions
                )
            except (ValueError, NotImplementedError) as e:
                click.echo(f"Error: {e}\n")
                continue
            rc, adapter, agent = new_rc, new_adapter, new_agent
            click.echo(f"→ {rc.display_name}\n")
            continue

        if user_input.startswith("/delegate"):
            parts = user_input.split(" ", 2)
            if len(parts) < 3:
                click.echo("Usage: /delegate <role> <task>\n")
                continue
            spawner = DelegationSpawner(
                pc, rc, adapter, tools=[], extensions=extensions
            )
            try:
                result = await spawner.delegate(parts[1], parts[2])
                click.echo(f"\n[{parts[1]}]> {result}\n")
            except (ValueError, RuntimeError, NotImplementedError) as e:
                click.echo(f"Error: {e}\n")
            continue

        try:
            response = await adapter.invoke(agent, user_input)
        except NotImplementedError as e:
            click.echo(f"Error: {e}\n", err=True)
            break
        click.echo(f"\n[{rc.display_name}]> {response}\n")


if __name__ == "__main__":
    main()
