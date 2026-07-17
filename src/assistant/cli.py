"""CLI: persona-by-role-by-harness selection with REPL + /role + /delegate.

Supports three modes:
  - `run` (default): interactive REPL via SDK harness
  - `export`: generate host-harness integration artifacts
  - `daemon`: run the persona's scheduled jobs (P7 scheduler)
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
from assistant.harnesses.factory import select_harness as _default_select_harness
from assistant.http_tools import HttpToolRegistry
from assistant.http_tools.discovery import discover_tools
from assistant.telemetry import set_assistant_ctx

logger = logging.getLogger(__name__)

_create_harness = _default_create_harness
# Injectable seam mirroring ``_create_harness`` (tests stub it). P11
# harness-routing: resolves the ``auto`` sentinel; explicit -H names
# pass through unchanged.
_select_harness = _default_select_harness

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
    type=click.Choice(
        ["auto", "deep_agents", "ms_agent_framework", "claude_code"]
    ),
    default="auto",
    help=(
        "Harness backend. 'auto' (default) routes deterministically: "
        "persona harnesses.routing: rules first, then M365-tool roles "
        "to ms_agent_framework when enabled, else deep_agents. Host "
        "harnesses are never auto-selected."
    ),
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

    # P11 harness-routing: resolve the 'auto' sentinel (explicit names
    # pass through). The session keeps this harness across /role
    # switches — routing runs once at startup.
    try:
        harness = _select_harness(pc, rc, requested=harness)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

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
    default="auto",
    help=(
        "SDK harness backend (default: auto — deterministic routing "
        "via persona rules + role signals; explicit names bypass)."
    ),
)
@click.option("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
@click.option("--port", type=int, default=8765, help="Bind port (default: 8765).")
@click.option(
    "--a2a",
    "enable_a2a",
    is_flag=True,
    default=False,
    help=(
        "Also serve the A2A protocol surface: agent card at "
        "/.well-known/agent-card.json (+ legacy agent.json) and "
        "JSON-RPC POST /a2a/v1 (message/send, message/stream)."
    ),
)
@click.option(
    "--mcp",
    "enable_mcp",
    is_flag=True,
    default=False,
    help=(
        "Also serve the MCP surface: streamable-HTTP transport at "
        "/mcp exposing one ask_<role> tool per enabled role (plus a "
        "generic ask). Auth is deferred to P25 — keep the default "
        "loopback bind."
    ),
)
def serve(
    persona: str,
    role: str | None,
    harness: str,
    host: str,
    port: int,
    enable_a2a: bool,
    enable_mcp: bool,
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

    # P11 harness-routing: resolve 'auto' before validation so
    # make_app only ever sees a concrete harness name.
    try:
        harness = _select_harness(pc, rc, requested=harness)
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

    # Only pass the surface kwargs when a flag is set so the default
    # invocation keeps the exact legacy make_app(persona, role, harness)
    # call shape (and injected test fakes with that signature keep
    # working).
    surface_kwargs: dict = {}
    if enable_a2a:
        surface_kwargs.update(
            enable_a2a=True,
            a2a_base_url=f"http://{host}:{port}",
        )
        click.echo(
            f"A2A enabled: agent card at http://{host}:{port}"
            "/.well-known/agent-card.json"
        )
    if enable_mcp:
        surface_kwargs.update(enable_mcp=True)
        click.echo(
            f"MCP enabled: streamable HTTP at http://{host}:{port}/mcp"
        )

    try:
        app = make_app(persona, role_name, harness, **surface_kwargs)
        uvicorn.run(app, host=host, port=port)
    except KeyboardInterrupt:
        pass


@main.command()
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
@click.option(
    "--harness",
    "-H",
    type=str,
    default="auto",
    help=(
        "SDK harness backend for scheduled jobs (default: auto — "
        "resolved per job against the job's role; a job's harness: "
        "key overrides this value)."
    ),
)
@click.option(
    "--serve",
    "with_server",
    is_flag=True,
    help="Also start the AG-UI SSE server alongside the scheduler.",
)
@click.option("--host", type=str, default="127.0.0.1", help="AG-UI bind host (default: 127.0.0.1).")
@click.option("--port", type=int, default=8765, help="AG-UI bind port (default: 8765).")
def daemon(
    persona: str,
    harness: str,
    with_server: bool,
    host: str,
    port: int,
) -> None:
    """Run the persona's scheduled jobs (schedules:) until interrupted.

    Starts the P7 scheduler: one asyncio task per enabled job in the
    persona's ``schedules:`` section (cron / interval / calendar
    triggers), each run spawning a fresh SDK harness under the job's
    ``consumer`` model binding (default ``scheduler`` — bind it to a
    cheap/local entry in ``models:``). With ``--serve`` the AG-UI SSE
    server runs in the same process. For long-running daemons,
    configure ``guardrails.budgets.model_call.persist: file`` so
    budget ceilings survive restarts.
    """
    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

    pc = _load_persona_or_fail(persona_reg, persona)

    if not pc.schedules:
        raise click.UsageError(
            f"Persona '{persona}' declares no schedules: section — "
            "nothing to run. Add scheduled jobs to persona.yaml (see "
            "personas/_template/persona.yaml)."
        )
    enabled = pc.schedules.enabled_jobs()
    if not enabled:
        raise click.UsageError(
            f"Persona '{persona}' has schedules, but every job is "
            "enabled: false — nothing to run."
        )

    # Validate every job's role and effective harness up front —
    # failures here are configuration errors and must not surface as
    # mid-flight job failures at 7am. P11 harness-routing: each job's
    # effective harness is its own `harness:` key, falling back to the
    # daemon -H value; 'auto' resolves against the job's role.
    for job in enabled:
        try:
            rc = role_reg.load(job.role, pc)
        except ValueError as e:
            raise click.UsageError(
                f"Scheduled job '{job.name}': {e}"
            ) from e
        try:
            resolved = _select_harness(
                pc, rc, requested=job.harness or harness
            )
            adapter = _create_harness(pc, rc, resolved)
        except ValueError as e:
            raise click.UsageError(
                f"Scheduled job '{job.name}': {e}"
            ) from e
        if not isinstance(adapter, SdkHarnessAdapter):
            click.echo(
                f"Error: scheduled job '{job.name}': harness "
                f"'{resolved}' is a host harness, not an SDK harness. "
                "Scheduled jobs require an SDK harness.",
                err=True,
            )
            sys.exit(1)

    # Daemons should persist budget state: a memory-only ledger resets
    # every restart, silently re-arming daily/monthly ceilings.
    budget = pc.guardrails.model_call_budget if pc.guardrails else None
    if budget is not None and pc.guardrails.spend_file is None:
        click.echo(
            "Warning: guardrails.budgets.model_call uses the in-memory "
            "ledger; for a long-running daemon set persist: file so "
            "spend ceilings survive restarts.",
            err=True,
        )

    set_assistant_ctx(pc.name, pc.default_role)

    click.echo(f"Persona:  {pc.display_name}")
    click.echo(f"Harness:  {harness}")
    click.echo(f"Jobs:     {', '.join(job.name for job in enabled)}")

    try:
        asyncio.run(
            _run_daemon(
                persona_reg, role_reg, pc, harness, with_server, host, port
            )
        )
    except KeyboardInterrupt:
        pass


async def _run_daemon(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    harness_name: str,
    with_server: bool,
    host: str,
    port: int,
) -> None:
    """Async body of the daemon command.

    Mirrors ``_run_repl``'s structure: the HTTP-tool discovery client
    stays open for the daemon's lifetime (registered tools hold it),
    and extension ``shutdown()`` hooks run in the outer ``finally``
    (P10 extension-lifecycle).
    """
    try:
        if _has_configured_tool_sources(pc):
            async with _make_discovery_client() as client:
                registry = await discover_tools(
                    pc.tool_sources,
                    client=client,
                    credentials=getattr(pc, "credentials", None),
                )
                await _run_daemon_with_registry(
                    persona_reg, role_reg, pc, harness_name, registry,
                    with_server, host, port,
                )
        else:
            await _run_daemon_with_registry(
                persona_reg, role_reg, pc, harness_name, HttpToolRegistry(),
                with_server, host, port,
            )
    finally:
        await persona_reg.shutdown_extensions()


async def _run_daemon_with_registry(
    persona_reg: PersonaRegistry,
    role_reg: RoleRegistry,
    pc,
    harness_name: str,
    registry: HttpToolRegistry,
    with_server: bool,
    host: str,
    port: int,
) -> None:
    import signal as _signal

    from assistant.core.scheduler import (
        AssistantScheduler,
        CalendarTriggerSource,
        HarnessJobRunner,
    )

    # P20 local-inference-node: pre-warm endpoint health state so the
    # first scheduled runs skip a known-dead local entry. No-op when no
    # registry entry declares `health:`; failures never block startup.
    try:
        from assistant.core.capabilities.health import default_health_monitor

        registry_models = getattr(pc, "models", None)
        health_refs = [
            ref
            for ref in getattr(registry_models, "entries", {}).values()
            if ref.health is not None and ref.endpoint
        ]
        if health_refs:
            verdicts = await default_health_monitor().refresh(health_refs)
            for entry_name, ok in sorted(verdicts.items()):
                click.echo(
                    f"Endpoint health: {entry_name}: "
                    f"{'healthy' if ok else 'UNHEALTHY'}"
                )
    except Exception:  # pragma: no cover — defensive; never block startup
        logger.warning("endpoint health pre-warm failed", exc_info=True)

    extensions = await persona_reg.load_extensions_async(pc)
    runner = HarnessJobRunner(
        pc,
        harness_name=harness_name,
        role_registry=role_reg,
        http_tool_registry=registry,
        extensions=extensions,
        create_harness_fn=_create_harness,
    )
    calendar_sources = [
        ext for ext in extensions if isinstance(ext, CalendarTriggerSource)
    ]
    scheduler = AssistantScheduler(
        pc,
        pc.schedules,
        job_runner=runner,
        calendar_sources=calendar_sources,
    )

    server = None
    server_task: asyncio.Task | None = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            # Platforms/loops without signal handler support fall back
            # to the KeyboardInterrupt path in the click command.
            pass

    try:
        scheduler.start()
        if with_server:
            import uvicorn

            from assistant.web.app import make_app

            if host != "127.0.0.1" and not host.startswith("127."):
                click.echo(
                    f"Warning: binding to non-loopback host '{host}'. "
                    "This exposes the server beyond localhost.",
                    err=True,
                )
            # P11 harness-routing: make_app needs a concrete harness;
            # resolve 'auto' against the persona's default role.
            server_harness = harness_name
            if server_harness == "auto":
                rc_default = role_reg.load(pc.default_role, pc)
                server_harness = _select_harness(pc, rc_default)
            app = make_app(pc.name, pc.default_role, server_harness)
            server = uvicorn.Server(
                uvicorn.Config(app, host=host, port=port)
            )
            server_task = loop.create_task(server.serve())
            click.echo(f"AG-UI server: http://{host}:{port}")
        click.echo("Scheduler running. Ctrl-C to stop.")
        await stop.wait()
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            await server_task
        await scheduler.stop()


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
            registry = await discover_tools(
                pc.tool_sources,
                client=client,
                credentials=getattr(pc, "credentials", None),
            )
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
            # ToolSpec input_schema is a JSON-Schema object; its
            # ``properties`` keys are the argument names (P17
            # tool-spec migration replaced the Pydantic args_schema).
            properties = (tool.input_schema or {}).get("properties", {})
            field_names = sorted(properties.keys())
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

    try:
        if _has_configured_tool_sources(pc):
            async with _make_discovery_client() as client:
                registry = await discover_tools(
                    pc.tool_sources,
                    client=client,
                    credentials=getattr(pc, "credentials", None),
                )
                await _run_repl_with_registry(
                    persona_reg, role_reg, pc, rc, harness_name, adapter,
                    registry, method,
                )
        else:
            await _run_repl_with_registry(
                persona_reg, role_reg, pc, rc, harness_name, adapter,
                HttpToolRegistry(), method,
            )
    finally:
        # P10 extension-lifecycle: run extension shutdown() hooks on
        # REPL exit (including sys.exit / Ctrl-C paths). Idempotent —
        # the atexit handler that also covers this is then a no-op.
        await persona_reg.shutdown_extensions()


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

    # Async variant: the REPL runs inside the event loop, and the
    # extensions' initialize() hooks must be awaited (P10
    # extension-lifecycle). Shutdown is owned by _run_repl's finally.
    extensions = await persona_reg.load_extensions_async(pc)
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


@main.group(name="persona")
def persona_group() -> None:
    """Persona maintenance commands."""


@persona_group.command("hash-extensions")
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
def hash_extensions(persona: str) -> None:
    """Generate/update the extension integrity manifest for a persona.

    Hashes every ``*.py`` file in the persona's extensions directory
    (SHA-256) and writes ``manifest.yaml`` next to them. The persona
    registry verifies private extensions against this manifest before
    executing them (P13 security-hardening); rerun this command after
    every intentional extension edit.
    """
    from assistant.core.extension_integrity import (
        MANIFEST_FILENAME,
        generate_manifest,
    )

    persona_reg = PersonaRegistry()
    pc = _load_persona_or_fail(persona_reg, persona)

    extensions_dir = pc.extensions_dir
    if not extensions_dir.is_dir():
        click.echo(
            f"Error: extensions directory does not exist: {extensions_dir}",
            err=True,
        )
        sys.exit(1)

    hashes = generate_manifest(extensions_dir)
    if not hashes:
        click.echo(
            f"No *.py extension files found in {extensions_dir}; wrote an "
            f"empty {MANIFEST_FILENAME}."
        )
        return
    click.echo(f"Wrote {extensions_dir / MANIFEST_FILENAME}:")
    for filename, digest in sorted(hashes.items()):
        click.echo(f"  {filename}  {digest}")


@main.group(name="models")
def models_group() -> None:
    """Model registry maintenance commands (P20 local-inference-node)."""


@models_group.command("sync-catalog")
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
@click.option(
    "--url",
    type=str,
    default=None,
    help="Catalog endpoint override (default: OpenRouter /models).",
)
def sync_catalog(persona: str, url: str | None) -> None:
    """Sync the OpenRouter model catalog into the persona's cache.

    Fetches the OpenRouter ``/models`` catalog (API key: persona-scoped
    credential ``OPENROUTER_API_KEY``, optional) and writes the
    git-ignored persona-local cache file
    (``<persona_dir>/.cache/models/catalog.json``). On the next persona
    load, registry entries whose ``id`` matches a cached row inherit
    pricing / context_length / modalities for fields they left empty —
    declared values always win. Offline-safe: without network this
    command errors clearly and nothing else breaks.
    """
    from assistant.core.capabilities.catalog import (
        OPENROUTER_KEY_REF,
        OPENROUTER_MODELS_URL,
        CatalogSyncError,
        fetch_catalog,
        write_catalog_cache,
    )

    persona_reg = PersonaRegistry()
    pc = _load_persona_or_fail(persona_reg, persona)
    catalog_url = url or OPENROUTER_MODELS_URL
    api_key = pc.credentials.get_credential(OPENROUTER_KEY_REF)

    try:
        models = asyncio.run(fetch_catalog(catalog_url, api_key=api_key))
    except CatalogSyncError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    persona_dir = persona_reg.personas_dir / persona
    path = write_catalog_cache(persona_dir, models, url=catalog_url)
    click.echo(f"Synced {len(models)} catalog models to {path}")
    click.echo(
        "Registry entries with a matching `id` and empty pricing/"
        "context_length/modalities inherit the catalog values on the "
        "next persona load."
    )


@models_group.command("check-health")
@click.option("--persona", "-p", type=str, required=True, help="Persona name.")
def check_health(persona: str) -> None:
    """Probe every health-declaring registry entry and report verdicts.

    The documented verification command for a local inference node
    (GX10 / vLLM / Ollama / NIM — see docs/deployment/gx10-node.md).
    Also warms this process's shared health cache. Exits 1 when any
    probed endpoint is unhealthy.
    """
    from assistant.core.capabilities.health import (
        default_health_monitor,
        probe_url,
    )

    persona_reg = PersonaRegistry()
    pc = _load_persona_or_fail(persona_reg, persona)
    refs = [
        ref
        for ref in pc.models.entries.values()
        if ref.health is not None and ref.endpoint
    ]
    if not refs:
        click.echo(
            f"No models: entries of persona '{persona}' declare health "
            "checks — nothing to probe."
        )
        return

    monitor = default_health_monitor()
    verdicts = asyncio.run(monitor.refresh(refs))
    for ref in refs:
        ok = verdicts.get(ref.name, False)
        status = "healthy" if ok else "UNHEALTHY"
        click.echo(f"{ref.name}: {status} ({probe_url(ref)})")
    if not all(verdicts.values()):
        sys.exit(1)


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
