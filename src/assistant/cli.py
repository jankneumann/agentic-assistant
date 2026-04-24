"""CLI: persona-by-role-by-harness selection with REPL + /role + /delegate.

Supports two modes:
  - `run` (default): interactive REPL via SDK harness
  - `export`: generate host-harness integration artifacts
"""

from __future__ import annotations

import asyncio
import logging
import sys

import click
import httpx

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import HostHarnessAdapter, SdkHarnessAdapter
from assistant.harnesses.factory import create_harness as _default_create_harness
from assistant.http_tools import HttpToolRegistry
from assistant.http_tools.discovery import discover_tools

logger = logging.getLogger(__name__)

_create_harness = _default_create_harness


class _DefaultGroup(click.Group):
    """Click group that defaults to 'run' when no subcommand is given."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            pass
        elif not args or args[0].startswith("-"):
            args = ["run", *args]
        return super().parse_args(ctx, args)


@click.group(cls=_DefaultGroup, invoke_without_command=True)
def main() -> None:
    """Start the agentic-assistant."""


@main.command()
@click.option("--persona", "-p", type=str, default=None, help="Persona name.")
@click.option("--role", "-r", type=str, default=None, help="Role name.")
@click.option(
    "--harness",
    "-H",
    type=click.Choice(["deep_agents", "ms_agent_framework", "claude_code"]),
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
@click.option(
    "--list-tools",
    is_flag=True,
    help="List HTTP tools discovered from the persona's tool_sources and exit.",
)
def run(
    persona: str | None,
    role: str | None,
    harness: str,
    list_personas: bool,
    list_roles: bool,
    list_tools: bool,
) -> None:
    """Start the interactive REPL."""
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

    if list_tools:
        if not persona:
            raise click.UsageError("--list-tools requires -p/--persona.")
        pc = _load_persona_or_fail(persona_reg, persona)
        exit_code = asyncio.run(_print_tool_catalog(pc))
        sys.exit(exit_code)

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

    if not isinstance(adapter, SdkHarnessAdapter):
        click.echo(
            f"Error: harness '{harness}' is a host harness, not an SDK harness. "
            f"Use 'assistant export' instead.",
            err=True,
        )
        sys.exit(1)

    asyncio.run(_run_repl(persona_reg, role_reg, pc, rc, harness, adapter))


@main.command()
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
@click.option("--role", "-r", type=str, default=None, help="Role name.")
@click.option(
    "--harness",
    "-H",
    type=str,
    required=True,
    help="Host harness name (e.g., claude_code).",
)
def export(persona: str, role: str | None, harness: str) -> None:
    """Generate host-harness integration artifacts."""
    from assistant.core.capabilities.resolver import CapabilityResolver

    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

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

    if not isinstance(adapter, HostHarnessAdapter):
        click.echo(
            f"Error: '{harness}' is an SDK harness, not a host harness. "
            f"Use 'assistant run' instead.",
            err=True,
        )
        sys.exit(1)

    resolver = CapabilityResolver()
    capabilities = resolver.resolve(pc, "host", rc)

    context = adapter.export_context(capabilities)
    click.echo(context.get("system_prompt", ""))


def _load_persona_or_fail(
    persona_reg: PersonaRegistry, name: str
):  # -> PersonaConfig
    try:
        return persona_reg.load(name)
    except ValueError as e:
        raise click.UsageError(str(e)) from e


def _make_discovery_client() -> httpx.AsyncClient:
    """Shared httpx.AsyncClient with the D9 security posture.

    - 10s read / 5s connect timeouts
    - ``follow_redirects=False`` (credentials must not leak to
      attacker-controlled hosts)
    - TLS verification on
    - Small connection pool scoped to session lifetime
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
        verify=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    )


def _has_configured_tool_sources(pc) -> bool:
    return any(src.get("base_url") for src in pc.tool_sources.values())


async def _print_tool_catalog(pc) -> int:
    """Implement ``assistant --list-tools`` short-circuit behavior.

    Returns the exit code: 0 if all configured sources discovered
    successfully (or there were none), 1 if any source failed.

    Success/failure is decided by the registry's contents: a source that
    ended up with at least one tool is considered successful, even if
    an intermediate warning was emitted (e.g. ``/openapi.json`` returned
    500 and ``/help`` succeeded). Warnings are still surfaced to the
    user as diagnostic context when at least one source failed.
    """
    if not pc.tool_sources:
        click.echo("No tool_sources configured.")
        return 0

    configured = sorted(
        name for name, src in pc.tool_sources.items() if src.get("base_url")
    )
    if not configured:
        click.echo("No tool_sources configured.")
        return 0

    # Capture WARNING records from discovery so failed sources can be
    # diagnosed — but do NOT key the exit code off the warning count.
    captured: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                captured.append(record)

    handler = _Handler()
    discovery_logger = logging.getLogger("assistant.http_tools.discovery")
    discovery_logger.addHandler(handler)
    try:
        async with _make_discovery_client() as client:
            registry = await discover_tools(pc.tool_sources, client=client)
    finally:
        discovery_logger.removeHandler(handler)

    failed_sources: list[str] = []
    for source_name in configured:
        tools = registry.by_source(source_name)
        click.echo(f"\n[{source_name}]")
        if not tools:
            click.echo("  (no tools — see warning logs)")
            failed_sources.append(source_name)
            continue
        for tool in tools:
            desc = (tool.description or "").split("\n", 1)[0]
            click.echo(f"  {tool.name}  — {desc}")
            args_schema = tool.args_schema
            if args_schema is not None and hasattr(args_schema, "model_fields"):
                field_names = sorted(args_schema.model_fields.keys())
                if field_names:
                    click.echo(f"    args: {', '.join(field_names)}")

    if failed_sources:
        click.echo("\nFailures:", err=True)
        # Only surface warnings whose message names a failed source, so
        # intermediate warnings for sources that ultimately succeeded
        # don't pollute the Failures section.
        for record in captured:
            msg = record.getMessage()
            if any(name in msg for name in failed_sources):
                click.echo(f"  {msg}", err=True)
        return 1
    return 0


async def _run_repl(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    rc: RoleConfig,
    harness_name: str,
    adapter: SdkHarnessAdapter,
) -> None:
    click.echo(f"Persona:  {pc.display_name}")
    click.echo(f"Role:     {rc.display_name}")
    click.echo(f"Harness:  {harness_name}")

    if _has_configured_tool_sources(pc):
        async with _make_discovery_client() as client:
            registry = await discover_tools(pc.tool_sources, client=client)
            await _run_repl_with_registry(
                persona_reg, role_reg, pc, rc, harness_name, adapter, registry,
            )
    else:
        await _run_repl_with_registry(
            persona_reg, role_reg, pc, rc, harness_name, adapter,
            HttpToolRegistry(),
        )


async def _run_repl_with_registry(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    rc: RoleConfig,
    harness_name: str,
    adapter: SdkHarnessAdapter,
    registry: HttpToolRegistry,
) -> None:
    from assistant.core.capabilities.resolver import CapabilityResolver

    click.echo(f"  HTTP tools: {len(registry)}")

    extensions = persona_reg.load_extensions(pc)
    ext_names = [getattr(e, "name", "?") for e in extensions]
    click.echo(
        f"  Extensions: {len(extensions)}"
        f"{' (' + ', '.join(ext_names) + ')' if ext_names else ''}"
    )

    # Route tools through CapabilityResolver → DefaultToolPolicy so
    # role.preferred_tools filtering applies uniformly to extension
    # tools + HTTP tools (spec: tool-policy / DefaultToolPolicy
    # Implementation).
    resolver = CapabilityResolver(http_tool_registry=registry)
    capabilities = resolver.resolve(pc, "sdk", rc)
    authorized = capabilities.tools.authorized_tools(
        pc, rc, loaded_extensions=extensions,
    )

    try:
        agent = await adapter.create_agent(tools=authorized, extensions=extensions)
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
                new_adapter_raw = _create_harness(pc, new_rc, harness_name)
                if not isinstance(new_adapter_raw, SdkHarnessAdapter):
                    click.echo("Error: harness is not SDK-based\n")
                    continue
                new_resolver = CapabilityResolver(http_tool_registry=registry)
                new_caps = new_resolver.resolve(pc, "sdk", new_rc)
                new_authorized = new_caps.tools.authorized_tools(
                    pc, new_rc, loaded_extensions=extensions,
                )
                new_agent = await new_adapter_raw.create_agent(
                    tools=new_authorized, extensions=extensions,
                )
            except (ValueError, NotImplementedError) as e:
                click.echo(f"Error: {e}\n")
                continue
            rc, adapter, agent = new_rc, new_adapter_raw, new_agent
            click.echo(f"→ {rc.display_name}\n")
            continue

        if user_input.startswith("/delegate"):
            parts = user_input.split(" ", 2)
            if len(parts) < 3:
                click.echo("Usage: /delegate <role> <task>\n")
                continue
            spawner = DelegationSpawner(
                pc, rc, adapter, tools=authorized, extensions=extensions,
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


@main.group()
def db() -> None:
    """Database migration commands."""


@db.command()
def upgrade() -> None:
    """Run all pending Alembic migrations to head."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    ini_path = (
        Path(__file__).resolve().parent / "migrations" / "alembic.ini"
    )
    try:
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(ini_path.parent))
        command.upgrade(cfg, "head")
        click.echo("Migrations applied successfully.")
    except Exception as e:
        click.echo(f"Error running migrations: {e}", err=True)
        sys.exit(1)


@db.command()
@click.argument("revision")
def downgrade(revision: str) -> None:
    """Roll back database to a specific REVISION."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    ini_path = (
        Path(__file__).resolve().parent / "migrations" / "alembic.ini"
    )
    try:
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(ini_path.parent))
        command.downgrade(cfg, revision)
        click.echo(f"Downgraded to revision {revision}.")
    except Exception as e:
        click.echo(f"Error running downgrade: {e}", err=True)
        sys.exit(1)


@main.command("export-memory")
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
def export_memory(persona: str) -> None:
    """Generate memory.md content from Postgres + Graphiti."""
    persona_reg = PersonaRegistry()
    pc = _load_persona_or_fail(persona_reg, persona)

    if not pc.database_url:
        click.echo(
            f"Error: persona '{persona}' has no database_url configured.",
            err=True,
        )
        sys.exit(1)

    from assistant.core.db import async_session_factory, create_async_engine
    from assistant.core.graphiti import create_graphiti_client
    from assistant.core.memory import MemoryManager

    engine = create_async_engine(pc)
    session_fac = async_session_factory(engine)
    graphiti = create_graphiti_client(pc)
    mgr = MemoryManager(session_fac, graphiti_client=graphiti)

    output = asyncio.run(mgr.export_memory(pc.name))
    click.echo(output, nl=False)


if __name__ == "__main__":
    main()
