"""CLI: persona-by-role-by-harness selection with REPL + /role + /delegate.

Supports two modes:
  - `run` (default): interactive REPL via SDK harness
  - `export`: generate host-harness integration artifacts
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
import httpx

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.delegation.spawner import DelegationSpawner
from assistant.harnesses.base import HostHarnessAdapter, SdkHarnessAdapter
from assistant.harnesses.factory import create_harness as _default_create_harness
from assistant.http_tools import HttpToolRegistry
from assistant.http_tools.discovery import discover_tools
from assistant.telemetry import set_assistant_ctx

logger = logging.getLogger(__name__)

_create_harness = _default_create_harness

def _list_role_skills(rc: RoleConfig) -> list[str]:
    """Return sorted skill names declared by the role's ``skills_dir``.

    Skills follow Deep Agents' Agent Skills layout: each skill is a
    subdirectory containing a ``SKILL.md`` file (with YAML
    frontmatter declaring ``name`` and ``description``). The skill's
    name is the subdirectory name. Empty list if the directory is
    missing, the role declares no ``skills_dir``, or no subdirectories
    contain a ``SKILL.md``.
    """
    if not rc.skills_dir:
        return []
    skills_path = Path(rc.skills_dir)
    if not skills_path.exists():
        return []
    return sorted(
        p.parent.name
        for p in skills_path.glob("*/SKILL.md")
        if p.is_file()
    )


def _build_help_line(rc: RoleConfig) -> str:
    """Render the REPL Commands help line for the active role.

    All session commands carry a ``/`` prefix; ``/quit`` is the
    canonical terminator (bare ``quit``/``exit`` remain accepted for
    REPL-muscle-memory compatibility but are not advertised).
    """
    commands = [
        "/roles",
        "/role <name>",
        "/delegate <role> <task>",
        "/quit",
    ]
    if rc.name == "teacher":
        commands.extend(["/methods", "/method <name>"])
    return "\nCommands: " + "  ".join(commands) + "\n"


def _method_directive(method: str, *, switching: bool) -> str:
    """Build a one-shot system-level directive for the next agent
    invocation when --method or /method is in play.

    - ``switching=False``: first-turn directive (from --method).
    - ``switching=True``: in-session switch directive (from /method).

    Sent ONCE on the turn immediately following the directive event.
    Subsequent turns rely on ``_method_reminder`` (called every turn)
    plus the prompt's method-persistence rules.
    """
    if switching:
        return (
            f"[system] From this turn forward, use the `{method}` "
            f"method. Summarize where we are in the current method's "
            f"loop in ≤3 sentences, announce the switch, then "
            f"enter Step 1 of the new method.\n\n"
        )
    return (
        f"[system] Use the `{method}` method. Begin Step 1 now for "
        f"the topic the user provides in their next message.\n\n"
    )


def _method_reminder(method: str) -> str:
    """Compact per-turn reminder that the named method is active.

    Re-injected on every user turn while ``active_method`` is set on
    the teacher role, so the agent doesn't drift back to method-
    negotiation between turns of a teaching loop. Keeps the directive
    state durable across multi-turn loops without requiring a harness
    rebuild or a system-prompt mutation.
    """
    return (
        f"[system] Active teaching method: `{method}`. Continue this "
        f"method's loop based on the conversation history; do NOT "
        f"re-offer method choice and do NOT re-ask for the topic if "
        f"it has already been named.\n\n"
    )


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
@click.option(
    "--method",
    "-m",
    type=str,
    default=None,
    help="Teaching method (skill) for the teacher role. Requires --role teacher.",
)
def run(
    persona: str | None,
    role: str | None,
    harness: str,
    list_personas: bool,
    list_roles: bool,
    list_tools: bool,
    method: str | None,
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

    # Validate --method against the effective role and skill files
    # before any harness work — failures here are UsageErrors.
    if method is not None:
        if rc.name != "teacher":
            raise click.UsageError(
                "--method/-m requires --role teacher "
                f"(active role is '{rc.name}')."
            )
        available = _list_role_skills(rc)
        if method not in available:
            raise click.UsageError(
                f"Unknown method '{method}'. "
                f"Available: {', '.join(available) if available else '(none)'}."
            )

    # Bind the assistant ContextVar (D4) so every span emitted during
    # this CLI run carries the right persona + role labels without
    # threading them through every method signature. Set once per CLI
    # invocation; the delegation decorator pushes a sub-role scope on
    # top of this when sub-agents are spawned.
    set_assistant_ctx(pc.name, rc.name)

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

    asyncio.run(
        _run_repl(persona_reg, role_reg, pc, rc, harness, adapter, method)
    )


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

    # Same ContextVar binding as the run command, so any tracing in
    # the export path (e.g. tool wraps in capabilities.tools) sees the
    # correct (persona, role) labels.
    set_assistant_ctx(pc.name, rc.name)

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


@main.command()
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
@click.option("--role", "-r", type=str, default=None, help="Role name.")
@click.option(
    "--harness",
    "-H",
    type=str,
    default="deep_agents",
    help="SDK harness backend (default: deep_agents).",
)
@click.option("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
@click.option("--port", type=int, default=8765, help="Bind port (default: 8765).")
def serve(
    persona: str,
    role: str | None,
    harness: str,
    host: str,
    port: int,
) -> None:
    """Start the AG-UI bridge HTTP server (SSE endpoint)."""
    try:
        import uvicorn

        from assistant.web.app import make_app
    except ImportError:
        click.echo("Error: uvicorn/fastapi not installed. Run `uv sync`.", err=True)
        sys.exit(1)

    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

    pc = _load_persona_or_fail(persona_reg, persona)
    role_name = role or pc.default_role
    if not role_name:
        raise click.UsageError(
            "No role specified and persona has no default_role. "
            "Supply -r/--role explicitly."
        )

    try:
        rc = role_reg.load(role_name, pc)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    # Validate harness before building the app.
    try:
        adapter = _create_harness(pc, rc, harness)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    if isinstance(adapter, HostHarnessAdapter):
        click.echo(
            f"Error: harness '{harness}' is a host harness, not an SDK harness. "
            "Use 'assistant export' for host harnesses.",
            err=True,
        )
        sys.exit(1)

    if host != "127.0.0.1" and not host.startswith("127."):
        click.echo(
            f"Warning: binding to non-loopback host '{host}'. "
            "This exposes the server beyond localhost.",
            err=True,
        )

    try:
        app = make_app(persona, role_name, harness)
        uvicorn.run(app, host=host, port=port)
    except KeyboardInterrupt:
        pass


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
    method: str | None = None,
) -> None:
    click.echo(f"Persona:  {pc.display_name}")
    click.echo(f"Role:     {rc.display_name}")
    click.echo(f"Harness:  {harness_name}")

    if _has_configured_tool_sources(pc):
        async with _make_discovery_client() as client:
            registry = await discover_tools(pc.tool_sources, client=client)
            await _run_repl_with_registry(
                persona_reg, role_reg, pc, rc, harness_name, adapter,
                registry, method,
            )
    else:
        await _run_repl_with_registry(
            persona_reg, role_reg, pc, rc, harness_name, adapter,
            HttpToolRegistry(), method,
        )


async def _run_repl_with_registry(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    rc: RoleConfig,
    harness_name: str,
    adapter: SdkHarnessAdapter,
    registry: HttpToolRegistry,
    method: str | None = None,
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

    # Teacher-role-only state. ``active_method`` tracks the currently
    # selected method (seeded from --method if present), and
    # ``pending_directive`` carries a system-level instruction to
    # prepend to the next user-turn (set by --method on startup and by
    # each /method switch).
    active_method: str | None = method if rc.name == "teacher" else None
    pending_directive: str | None = (
        _method_directive(active_method, switching=False)
        if active_method is not None
        else None
    )

    click.echo(_build_help_line(rc))

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ", default="")
        except (click.exceptions.Abort, EOFError):
            break
        # Accept bare ``quit``/``exit`` (decades of REPL muscle memory)
        # AND slash-prefixed ``/quit``/``/exit`` (matches the convention
        # of the other session commands). The help line advertises
        # ``/quit`` so the displayed command set is internally
        # consistent; the bare forms remain undocumented compatibility
        # aliases.
        if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
            break

        if user_input == "/roles":
            for r in role_reg.available_for_persona(pc):
                marker = " ←" if r == rc.name else ""
                click.echo(f"  {r}{marker}")
            continue

        if user_input == "/methods":
            if rc.name != "teacher":
                click.echo(
                    "`/methods` is only available when role is `teacher`.\n"
                )
                continue
            skills = _list_role_skills(rc)
            if not skills:
                click.echo(f"  (no skill files under {rc.skills_dir})\n")
                continue
            for s in skills:
                marker = " ←" if s == active_method else ""
                click.echo(f"  {s}{marker}")
            continue

        if user_input.strip() == "/method":
            if rc.name != "teacher":
                click.echo(
                    "`/method` is only available when role is `teacher`.\n"
                )
                continue
            skills = _list_role_skills(rc)
            click.echo(
                f"Usage: /method <name>  "
                f"(available: {', '.join(skills) if skills else '(none)'})\n"
            )
            continue

        if user_input.startswith("/method "):
            if rc.name != "teacher":
                click.echo(
                    "`/method` is only available when role is `teacher`.\n"
                )
                continue
            new_method = user_input.split(" ", 1)[1].strip()
            skills = _list_role_skills(rc)
            if not new_method:
                click.echo(
                    f"Usage: /method <name>  "
                    f"(available: {', '.join(skills) if skills else '(none)'})\n"
                )
                continue
            if new_method not in skills:
                click.echo(
                    f"Unknown method '{new_method}'. "
                    f"Available: {', '.join(skills) if skills else '(none)'}.\n"
                )
                continue
            # Prompt-level switch — do NOT rebuild the agent/harness.
            active_method = new_method
            pending_directive = _method_directive(new_method, switching=True)
            click.echo(f"→ method: {new_method}\n")
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
            authorized = new_authorized
            # /role rebuilds the agent (conversation lost), so always
            # reset method state. If the user wants method context on
            # the new agent, they re-issue /method <name>. Without
            # this reset, switching role A → teacher would preserve a
            # stale active_method from a prior teacher session and
            # render a phantom [Teacher:<method>]> badge on a fresh
            # agent that has no idea the method is active.
            active_method = None
            pending_directive = None
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

        message = user_input
        if pending_directive is not None:
            # First turn after --method or /method: send the full
            # setup directive (begin Step 1 / announce switch).
            message = pending_directive + user_input
            pending_directive = None
        elif rc.name == "teacher" and active_method is not None:
            # Subsequent turns while a method is active: prepend the
            # compact reminder so the model doesn't drift back to
            # method-negotiation between turns of the loop.
            message = _method_reminder(active_method) + user_input

        try:
            response = await adapter.invoke(agent, message)
        except NotImplementedError as e:
            click.echo(f"Error: {e}\n", err=True)
            break

        if rc.name == "teacher" and active_method is not None:
            prefix = f"{rc.display_name}:{active_method}"
        else:
            prefix = rc.display_name
        click.echo(f"\n[{prefix}]> {response}\n")


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


@main.command()
@click.option(
    "--fixtures",
    "-f",
    type=click.Path(file_okay=False),
    default="evaluation/simulation/sources",
    show_default=True,
    help="Fixtures root: one subdirectory per simulated source, each with "
    "a routes.yaml manifest (or a single-source dir containing routes.yaml).",
)
@click.option("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
@click.option("--port", type=int, default=8901, help="Bind port (default: 8901).")
def simulate(fixtures: str, host: str, port: int) -> None:
    """Serve fixture-backed simulated tool APIs (simulation personas).

    Starts a loopback FastAPI server whose per-source /openapi.json
    endpoints are consumed by the existing http_tools discovery, so a
    persona whose tool_sources point at the printed URLs runs the real
    agent stack against deterministic canned responses.
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("Error: uvicorn/fastapi not installed. Run `uv sync`.", err=True)
        sys.exit(1)

    from assistant.simulation.server import (
        discover_sources,
        env_var_for_source,
        make_simulator_app_from_sources,
    )

    fixtures_root = Path(fixtures)
    try:
        sources = discover_sources(fixtures_root)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    app = make_simulator_app_from_sources(sources)

    if host != "127.0.0.1" and not host.startswith("127."):
        click.echo(
            f"Warning: binding to non-loopback host '{host}'. "
            "This exposes the simulator beyond localhost.",
            err=True,
        )

    base = f"http://{host}:{port}"
    click.echo(f"Simulator: {base}  (health: {base}/health)")
    click.echo("Simulated tool sources:")
    for source in sources:
        click.echo(
            f"  export {env_var_for_source(source.name)}={base}/{source.name}"
            f"    # {len(source.routes)} operation(s)"
        )
    personas_dir = fixtures_root.parent / "personas"
    if personas_dir.is_dir():
        click.echo(f"  export ASSISTANT_PERSONAS_DIR={personas_dir}")
        click.echo(
            "\nThen, from another shell:  uv run assistant -p sim --list-tools"
        )

    try:
        uvicorn.run(app, host=host, port=port)
    except KeyboardInterrupt:
        pass


@main.command("export-eval-dataset")
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
@click.option(
    "--role",
    "-r",
    type=str,
    default=None,
    help="Only export interactions recorded under this role.",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="Maximum number of interactions to export (newest first).",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False),
    default="evaluation/datasets/exported",
    show_default=True,
    help="Directory for the generated scenario stub files (created if "
    "missing). Deliberately outside the gen-eval scenario_dirs — stubs "
    "need human completion before promotion into a suite.",
)
def export_eval_dataset(
    persona: str, role: str | None, limit: int, output_dir: str
) -> None:
    """Export stored interactions as gen-eval scenario YAML stubs.

    Offline-first trace→eval-dataset export (P27): reads the persona
    DB's interactions table via MemoryManager and writes one scenario
    stub per interaction. Production regressions become permanent
    tests once a human completes the stub's message + expectations.
    """
    persona_reg = PersonaRegistry()
    pc = _load_persona_or_fail(persona_reg, persona)

    if not pc.database_url:
        click.echo(
            f"Error: persona '{persona}' has no database_url configured — "
            "there are no stored interactions to export.",
            err=True,
        )
        sys.exit(1)

    from assistant.core.db import async_session_factory, create_async_engine
    from assistant.core.graphiti import create_graphiti_client
    from assistant.core.memory import MemoryManager
    from assistant.simulation.dataset import (
        dump_scenario_yaml,
        interactions_to_scenarios,
        scenario_filename,
    )

    engine = create_async_engine(pc)
    session_fac = async_session_factory(engine)
    graphiti = create_graphiti_client(pc)
    mgr = MemoryManager(session_fac, graphiti_client=graphiti)

    interactions = asyncio.run(
        mgr.list_interactions(pc.name, role=role, limit=limit)
    )
    if not interactions:
        click.echo("No stored interactions matched — nothing to export.")
        return

    scenarios = interactions_to_scenarios(pc.name, interactions)
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        out_path = out_root / scenario_filename(scenario)
        out_path.write_text(dump_scenario_yaml(scenario), encoding="utf-8")
        click.echo(f"  wrote {out_path}")
    click.echo(
        f"\nExported {len(scenarios)} scenario stub(s) to {out_root}. "
        "Complete each stub (message + expectations) before promoting it "
        "into a scenario suite."
    )


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
