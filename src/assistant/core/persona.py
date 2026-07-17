"""Persona registry — discovers submodule-mounted persona configs."""

from __future__ import annotations

import asyncio
import atexit
import importlib.util
import inspect
import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

from assistant.core.capabilities.catalog import (
    apply_catalog_metadata,
    load_catalog_cache,
)
from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
)
from assistant.core.capabilities.guardrails import (
    GuardrailConfig,
    GuardrailConfigError,
    parse_guardrail_config,
)
from assistant.core.capabilities.models import (
    ModelRegistry,
    ModelRegistryError,
    parse_model_registry,
)
from assistant.core.capabilities.openbao import (
    CredentialsConfigError,
    build_credential_provider,
    parse_credentials_config,
)
from assistant.core.cleanroom import (
    CleanRoomConfig,
    CleanRoomConfigError,
    parse_clean_room_config,
)
from assistant.core.extension_integrity import (
    IntegrityVerdict,
    check_extension_integrity,
)
from assistant.core.scheduler import (
    ScheduleConfig,
    ScheduleConfigError,
    parse_schedule_config,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class A2AAuthConfig:
    """Parsed ``auth.a2a`` served-surface auth declaration (P25 agent-iam).

    ``token_env`` is a CredentialProvider ref (env-var name today,
    vault path under the OpenBao backend) — never the token value
    itself. The only supported ``type`` is ``bearer``.
    """

    type: str
    token_env: str


def parse_a2a_auth(raw: Any) -> A2AAuthConfig | None:
    """Validate an ``auth.a2a`` mapping; ``None`` when undeclared.

    Actionable-error posture: unknown keys, unsupported types, and a
    missing/empty ``token_env`` fail with a ``ValueError`` naming the
    offender so persona load surfaces it directly.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"auth.a2a: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"type", "token_env"})
    if unknown:
        raise ValueError(
            f"auth.a2a: unknown keys {unknown}. Expected 'type: bearer' "
            f"and 'token_env: <ref>'."
        )
    auth_type = raw.get("type", "bearer")
    if auth_type != "bearer":
        raise ValueError(
            f"auth.a2a: type {auth_type!r} is not supported; only "
            f"'bearer' exists today."
        )
    token_env = raw.get("token_env")
    if not isinstance(token_env, str) or not token_env:
        raise ValueError(
            "auth.a2a: requires a non-empty 'token_env' naming the "
            "credential ref that holds the expected bearer token."
        )
    return A2AAuthConfig(type=auth_type, token_env=token_env)


@dataclass
class PersonaConfig:
    name: str
    display_name: str
    database_url: str
    graphiti_url: str
    auth_provider: str
    auth_config: dict[str, str]
    harnesses: dict[str, dict[str, Any]]
    # ``tool_sources`` entry shape:
    #   {
    #     "base_url":      str,                 # eagerly resolved env var
    #     "auth_header":   dict | None,         # structured, env var NAME only
    #     "allowed_tools": list[str],
    #   }
    # ``auth_header`` is either ``None`` or a dict
    # ``{"type": str, "env": str, "header"?: str}`` where ``env`` is the
    # name of the environment variable that holds the credential — NOT
    # the resolved value. ``resolve_auth_header()`` reads the env var at
    # discovery time so a late-arriving credential (e.g. via bao/vault)
    # is picked up without reloading the persona.
    tool_sources: dict[str, dict[str, Any]]
    extensions: list[dict[str, Any]]
    extensions_dir: Path
    default_role: str = "chief_of_staff"
    disabled_roles: list[str] = field(default_factory=list)
    prompt_augmentation: str = ""
    memory_content: str = ""
    # Parsed + validated ``models:`` registry (model-provider spec /
    # P19 model-provider-routing) — the only model-selection mechanism.
    # Empty when the persona declares no registry; the resolver then
    # synthesizes one from the known harness defaults
    # (``default_model_registry``).
    models: ModelRegistry = field(default_factory=ModelRegistry)
    # Parsed + validated ``guardrails:`` section (guardrail-provider
    # spec / P13 security-hardening). Falsy when the persona declares
    # no guardrails — the resolver then selects AllowAllGuardrails.
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    # Parsed + validated ``schedules:`` section (scheduler spec / P7).
    # Falsy when the persona declares no scheduled jobs — the daemon
    # CLI refuses to start without them.
    schedules: ScheduleConfig = field(default_factory=ScheduleConfig)
    # Persona-scoped credential provider (credential-provider spec /
    # P13): persona ``.env`` values first, process env fallback.
    # Since P25 agent-iam a persona ``credentials: {backend: openbao}``
    # section selects the OpenBao backend layered over the same env
    # tiers. ``repr=False`` — the scoped namespace holds secret values.
    credentials: CredentialProvider = field(
        default_factory=EnvCredentialProvider, repr=False
    )
    # Parsed ``auth.a2a`` served-surface auth (P25 agent-iam). ``None``
    # keeps the pre-P25 loopback-unauthenticated posture (the A2A
    # server warns at startup).
    a2a_auth: A2AAuthConfig | None = None
    # Parsed + validated ``clean_room:`` section (clean-room spec /
    # P26 knowledge-clean-room). Falsy when the persona declares no
    # clean-room rules — the declassification gateway then refuses
    # every export AND import (total persona isolation, the default).
    clean_room: CleanRoomConfig = field(default_factory=CleanRoomConfig)
    raw: dict[str, Any] = field(default_factory=dict)


_DEFAULT_PERSONAS_DIR = Path("personas")


class PersonaRegistry:
    """Discover and load personas from submodule-mounted directories.

    The root is resolved (in order): explicit ``personas_dir`` arg, the
    ``ASSISTANT_PERSONAS_DIR`` environment variable, then ``Path("personas")``.
    The env-var path lets tests and alternative harnesses redirect the
    registry away from the production submodule mount without touching
    callers — see docs/gotchas.md G6 for the privacy-boundary rationale.
    """

    def __init__(
        self,
        personas_dir: Path | str | None = None,
        *,
        credential_provider_factory: (
            Callable[[str, Path], CredentialProvider] | None
        ) = None,
    ) -> None:
        if personas_dir is None:
            env = os.environ.get("ASSISTANT_PERSONAS_DIR")
            personas_dir = Path(env) if env else _DEFAULT_PERSONAS_DIR
        self.personas_dir = Path(personas_dir)
        # P13 security-hardening: injection point for a custom
        # CredentialProvider backend (e.g. OpenBao in P25). The factory
        # receives ``(persona_name, persona_dir)``; the default builds
        # the persona-scoped env provider (persona ``.env`` first,
        # process env fallback).
        self._credential_provider_factory = credential_provider_factory
        self._cache: dict[str, PersonaConfig] = {}
        # P10 extension-lifecycle: extensions that completed
        # ``initialize()`` and are awaiting ``shutdown()``, in
        # activation order. Drained by ``shutdown_extensions()``.
        self._active_extensions: list[Any] = []
        self._atexit_registered = False

    def discover(self) -> list[str]:
        if not self.personas_dir.exists():
            return []
        return sorted(
            p.name
            for p in self.personas_dir.iterdir()
            if p.is_dir()
            and (p / "persona.yaml").exists()
            and not p.name.startswith("_")
        )

    def load(self, name: str) -> PersonaConfig:
        if name in self._cache:
            return self._cache[name]

        persona_dir = self.personas_dir / name
        config_path = persona_dir / "persona.yaml"
        if not config_path.exists():
            available = self.discover()
            hint = (
                f" Initialize with: git submodule update --init "
                f"personas/{name}"
            )
            raise ValueError(
                f"Persona '{name}' not found or not initialized. "
                f"Available: {available}.{hint}"
            )

        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        if "name" not in raw:
            raise ValueError(
                f"Persona config at {config_path} is missing required field 'name'."
            )

        auth_cfg_raw = (raw.get("auth") or {}).get("config") or {}
        tool_sources_raw = raw.get("tool_sources") or {}

        try:
            models = parse_model_registry(raw.get("models") or {})
        except ModelRegistryError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"models: registry — {exc}"
            ) from exc

        # P20 local-inference-node: entries whose `id` matches a row in
        # the persona-local catalog cache (written by `assistant models
        # sync-catalog`) inherit pricing / context_length / modalities
        # for fields they left empty — declared values always win, and
        # a missing cache is a silent no-op (offline-safe, no network).
        if models:
            updated = apply_catalog_metadata(
                models, load_catalog_cache(persona_dir)
            )
            if updated:
                logger.debug(
                    "persona '%s': catalog cache filled metadata for %s",
                    raw["name"],
                    updated,
                )

        try:
            guardrails = parse_guardrail_config(
                raw.get("guardrails") or {}, persona_dir=persona_dir
            )
        except GuardrailConfigError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"guardrails: section — {exc}"
            ) from exc

        try:
            schedules = parse_schedule_config(raw.get("schedules") or {})
        except ScheduleConfigError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"schedules: section — {exc}"
            ) from exc

        try:
            a2a_auth = parse_a2a_auth((raw.get("auth") or {}).get("a2a"))
        except ValueError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"auth.a2a: section — {exc}"
            ) from exc

        try:
            clean_room = parse_clean_room_config(raw.get("clean_room"))
        except CleanRoomConfigError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"clean_room: section — {exc}"
            ) from exc

        # P13 security-hardening: every persona-config secret read goes
        # through the persona-scoped CredentialProvider (persona .env
        # values first, process env fallback) — never through a direct
        # os.environ read. P25 agent-iam: an injected factory still
        # wins; otherwise a persona ``credentials: {backend: openbao}``
        # section selects the OpenBao backend layered over the env
        # tiers (unconfigured/unreachable degrades to env, never fatal).
        try:
            credentials_config = parse_credentials_config(
                raw.get("credentials")
            )
        except CredentialsConfigError as exc:
            raise ValueError(
                f"Persona '{raw['name']}' ({config_path}): invalid "
                f"credentials: section — {exc}"
            ) from exc
        credentials = (
            self._credential_provider_factory(raw["name"], persona_dir)
            if self._credential_provider_factory is not None
            else build_credential_provider(
                raw["name"], persona_dir, credentials_config
            )
        )

        def _cred(ref: Any) -> str:
            return credentials.get_credential(str(ref)) if ref else ""

        config = PersonaConfig(
            name=raw["name"],
            display_name=raw.get("display_name", raw["name"]),
            database_url=_cred((raw.get("database") or {}).get("url_env", "")),
            graphiti_url=_cred((raw.get("graphiti") or {}).get("url_env", "")),
            auth_provider=(raw.get("auth") or {}).get("provider", "custom"),
            auth_config={k: _cred(v) for k, v in auth_cfg_raw.items()},
            harnesses=raw.get("harnesses", {}) or {},
            tool_sources={
                src_name: {
                    "base_url": _cred(src.get("base_url_env", "")),
                    "auth_header": _normalize_auth_header(src),
                    "allowed_tools": src.get("allowed_tools", []) or [],
                }
                for src_name, src in tool_sources_raw.items()
            },
            extensions=raw.get("extensions", []) or [],
            extensions_dir=Path(
                raw.get("extensions_dir", persona_dir / "extensions")
            ),
            default_role=raw.get("default_role", "chief_of_staff"),
            disabled_roles=raw.get("disabled_roles", []) or [],
            models=models,
            guardrails=guardrails,
            schedules=schedules,
            credentials=credentials,
            a2a_auth=a2a_auth,
            clean_room=clean_room,
            raw=raw,
        )

        prompt_path = persona_dir / "prompt.md"
        if prompt_path.exists():
            config.prompt_augmentation = prompt_path.read_text()

        memory_path = persona_dir / "memory.md"
        if memory_path.exists():
            config.memory_content = memory_path.read_text()

        self._cache[name] = config
        return config

    def load_extensions(self, config: PersonaConfig) -> list[Any]:
        """Load, initialize, and register the persona's extensions (sync).

        Thin wrapper over :meth:`load_extensions_async` for callers
        outside an event loop (scripts, sync tests). Callers already
        running inside a loop MUST use the async variant — a sync call
        cannot await the extensions' ``initialize()`` hooks, and
        running them on a throwaway worker-thread loop would bind
        extension resources (e.g. httpx pools) to a dead loop
        (extension-lifecycle design D4).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.load_extensions_async(config))
        raise RuntimeError(
            "PersonaRegistry.load_extensions() cannot be called while an "
            "event loop is running; use "
            "`await registry.load_extensions_async(config)` instead."
        )

    async def load_extensions_async(self, config: PersonaConfig) -> list[Any]:
        """Load extensions, run ``initialize()`` hooks, register shutdown.

        Per the persona-registry requirement "Extension Initialization
        and Shutdown Lifecycle": each loaded extension's optional
        ``initialize()`` hook runs in declaration order immediately
        post-load; a failing hook disables that extension (WARNING +
        best-effort ``shutdown()``) without failing persona load.
        Extensions that survive are tracked for
        :meth:`shutdown_extensions` and a once-per-registry ``atexit``
        handler.
        """
        extensions: list[Any] = []
        for ext in self._load_extension_instances(config):
            if not await self._initialize_extension(ext):
                continue
            extensions.append(ext)
        if extensions:
            self._active_extensions.extend(extensions)
            self._register_atexit_handler()
        return extensions

    async def shutdown_extensions(self) -> None:
        """Run ``shutdown()`` hooks on all active extensions.

        Reverse activation order; per-extension errors are swallowed
        with a WARNING. Idempotent — the active list is drained first,
        so a second call (e.g. explicit daemon teardown followed by
        the ``atexit`` handler) is a no-op.
        """
        extensions, self._active_extensions = self._active_extensions, []
        for ext in reversed(extensions):
            try:
                await _call_optional_hook(ext, "shutdown")
            except Exception as exc:
                logger.warning(
                    "Extension %r: shutdown() failed (continuing): %s",
                    getattr(ext, "name", "<unknown>"),
                    exc,
                )

    def _register_atexit_handler(self) -> None:
        if self._atexit_registered:
            return
        self._atexit_registered = True
        atexit.register(self._atexit_shutdown)

    def _atexit_shutdown(self) -> None:
        """Best-effort interpreter-exit bridge to ``shutdown_extensions``.

        No event loop runs at ``atexit`` time, so ``asyncio.run`` is
        safe. All errors are swallowed — the interpreter is exiting
        and there is nothing actionable left to do.
        """
        if not self._active_extensions:
            return
        try:
            asyncio.run(self.shutdown_extensions())
        except Exception:  # pragma: no cover — interpreter teardown
            logger.debug("atexit extension shutdown failed", exc_info=True)

    async def _initialize_extension(self, ext: Any) -> bool:
        """Run an extension's optional ``initialize()`` hook.

        Returns ``True`` when the extension is usable (hook absent or
        succeeded). On failure: WARNING, best-effort ``shutdown()`` of
        the partially-initialized instance, and ``False`` so the
        caller disables exactly this extension (design D3).
        """
        try:
            await _call_optional_hook(ext, "initialize")
        except Exception as exc:
            logger.warning(
                "Extension %r: initialize() failed; disabling this "
                "extension (its tools will not be exposed): %s",
                getattr(ext, "name", "<unknown>"),
                exc,
            )
            try:
                await _call_optional_hook(ext, "shutdown")
            except Exception:
                logger.debug(
                    "Extension %r: best-effort shutdown after failed "
                    "initialize also failed",
                    getattr(ext, "name", "<unknown>"),
                    exc_info=True,
                )
            return False
        return True

    def _load_extension_instances(self, config: PersonaConfig) -> list[Any]:
        extensions: list[Any] = []
        for ext_def in config.extensions:
            module_name = ext_def["module"]
            ext = None

            private_path = config.extensions_dir / f"{module_name}.py"
            if private_path.exists():
                # P13 security-hardening: verify the private file against
                # the optional extensions-dir manifest BEFORE any code in
                # it executes. A blocked file is disabled entirely — no
                # fallback to a same-named public module, so tampering
                # can never silently swap implementations.
                integrity = check_extension_integrity(
                    config.extensions_dir, private_path
                )
                if integrity.blocked:
                    logger.error(
                        "Extension %r: integrity verification failed "
                        "(%s); NOT executing %s — extension disabled. "
                        "If this change is intentional, regenerate the "
                        "manifest with `assistant persona hash-extensions "
                        "-p %s`.",
                        module_name,
                        integrity.detail,
                        private_path,
                        config.name,
                    )
                    continue
                if integrity.verdict is IntegrityVerdict.UNVERIFIED:
                    logger.warning(
                        "Extension %r: %s — loading UNVERIFIED private "
                        "extension. Generate a manifest with `assistant "
                        "persona hash-extensions -p %s`.",
                        module_name,
                        integrity.detail,
                        config.name,
                    )
                ext = _load_private_extension(
                    config.name,
                    module_name,
                    private_path,
                    ext_def.get("config") or {},
                    persona=config,
                )

            if ext is None:
                try:
                    mod = import_module(f"assistant.extensions.{module_name}")
                except ImportError as e:
                    logger.warning(
                        "Extension %r not found (public or private): %s",
                        module_name,
                        e,
                    )
                    continue
                ext = _call_create_extension(
                    mod, module_name, ext_def.get("config") or {}, persona=config
                )

            # P9 error-resilience D11: install a one-shot runtime guard so
            # the first call to health_check() validates the return type
            # is HealthStatus. Catches private-submodule extensions that
            # were not migrated when health_check() was widened from bool.
            _install_health_check_conformance_guard(ext)
            extensions.append(ext)
        return extensions


def _load_private_extension(
    persona_name: str,
    module_name: str,
    path: Path,
    config: dict[str, Any],
    *,
    persona: PersonaConfig,
) -> Any:
    # Defense in depth: reject path-traversal-y module names even though the
    # private repo is trusted — cheap guard, avoids loading from outside
    # the declared extensions_dir if YAML is ever machine-generated.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module_name):
        raise ValueError(
            f"Invalid extension module name: {module_name!r}"
        )
    mod_key = f"persona_ext_{persona_name}_{module_name}"
    spec = importlib.util.spec_from_file_location(mod_key, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load private extension at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # Don't leave a partially-initialized module shadowing future imports
        sys.modules.pop(mod_key, None)
        raise
    return _call_create_extension(mod, module_name, config, persona=persona)


def _call_create_extension(
    mod: Any,
    module_name: str,
    config: dict[str, Any],
    *,
    persona: PersonaConfig,
) -> Any:
    """Invoke an extension's ``create_extension`` factory with the persona kwarg.

    Per ms-graph-extension extension-registry MODIFIED: the factory
    contract is ``create_extension(config, *, persona)``. Stubs accept
    and ignore; real factories use ``persona`` to construct their MSAL
    strategy and per-extension GraphClient. Legacy out-of-tree factories
    that do NOT accept ``persona`` MUST surface as an actionable
    ``TypeError`` at load time so the operator can migrate the third-
    party extension rather than discovering the breakage at first
    Graph call.
    """
    factory = getattr(mod, "create_extension", None)
    if factory is None:
        raise ImportError(
            f"Extension module {module_name!r} does not define "
            f"create_extension(config, *, persona)."
        )
    try:
        return factory(config, persona=persona)
    except TypeError as exc:
        msg = str(exc)
        legacy_signal = (
            "unexpected keyword argument 'persona'" in msg
            or "got an unexpected keyword argument 'persona'" in msg
            or "takes 1 positional argument" in msg
            or "takes no keyword arguments" in msg
        )
        if legacy_signal:
            raise TypeError(
                f"Extension {module_name!r}: legacy create_extension "
                "signature does not accept the 'persona' keyword argument. "
                "Migration: change the factory to "
                "`def create_extension(config: dict[str, Any], *, persona: "
                "PersonaConfig | None = None) -> Extension:`. Stubs may "
                "accept and ignore `persona`; real Microsoft 365 factories "
                "use `persona` to construct an MSALStrategy + GraphClient. "
                "See docs/gotchas.md for the migration recipe."
            ) from exc
        raise


def _install_health_check_conformance_guard(ext: Any) -> None:
    """Wrap ``ext.health_check`` so the first call validates the return type.

    Per OpenSpec change ``error-resilience`` D11: with the protocol widened
    from ``bool`` to ``HealthStatus``, a private out-of-tree extension that
    was not migrated would otherwise return ``True`` and only fail later in
    a confusing way. This guard fires once on first probe, raising a
    ``TypeError`` with a clear migration recipe.

    The guard self-removes after the first successful conformance check so
    subsequent probes pay no overhead.
    """
    from assistant.core.resilience import HealthStatus

    original = getattr(ext, "health_check", None)
    if original is None or not callable(original):
        return

    async def _guarded(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        if not isinstance(result, HealthStatus):
            raise TypeError(
                f"Extension {ext.name!r}: health_check() returned "
                f"{type(result).__name__}, expected HealthStatus. "
                "Migration: `return default_health_status_for_unimplemented(self.name)`. "
                "See docs/gotchas.md for details.",
            )
        # Self-remove the guard so subsequent calls are unwrapped.
        try:
            ext.health_check = original
        except (AttributeError, TypeError):
            # Some Protocol-compatible objects may forbid attribute
            # assignment (e.g. frozen dataclasses); the guard remains
            # active and re-validates each call. Acceptable cost.
            pass
        return result

    try:
        ext.health_check = _guarded
    except (AttributeError, TypeError):
        # If we cannot install the guard at all, skip silently — mypy
        # remains the static check, runtime is best-effort.
        logger.debug(
            "could not install health_check guard on extension %r",
            getattr(ext, "name", "<unknown>"),
        )


async def _call_optional_hook(ext: Any, hook_name: str) -> None:
    """Invoke an optional lifecycle hook on ``ext``, tolerantly.

    Per extension-lifecycle design D1/D2: hooks are documented-optional
    (a ``typing.Protocol`` cannot carry defaults, and requiring them
    would break ``isinstance`` for structural private-submodule
    extensions), so absence is a no-op. A present hook is called and
    its result awaited only when awaitable — a synchronous hook on an
    out-of-tree extension is accepted. Exceptions propagate to the
    caller, which owns the failure policy.
    """
    hook = getattr(ext, hook_name, None)
    if not callable(hook):
        return
    result = hook()
    if inspect.isawaitable(result):
        await result


def _normalize_auth_header(src: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a tool-source's auth header to the structured form.

    Returns one of:

    * ``None`` — when neither ``auth_header`` nor ``auth_header_env`` is
      present (anonymous source).
    * ``{"type": "bearer", "env": VAR_NAME}`` — when only the legacy
      ``auth_header_env: VAR_NAME`` is set. ``VAR_NAME`` is the **name**
      of the environment variable, not the resolved credential; the
      resolver reads the value at discovery time.
    * The source's ``auth_header`` dict **as-is** when it is already a
      mapping with ``type`` / ``env`` (and optional ``header``). Extra
      keys are preserved so future auth types can round-trip without a
      schema bump.

    If both forms are present, the structured ``auth_header`` wins —
    this keeps migration safe for personas that redeclare the header in
    the new shape but leave the legacy key behind.
    """
    structured = src.get("auth_header")
    if isinstance(structured, dict):
        return dict(structured)

    legacy_env = src.get("auth_header_env")
    if legacy_env:
        return {"type": "bearer", "env": legacy_env}

    return None
