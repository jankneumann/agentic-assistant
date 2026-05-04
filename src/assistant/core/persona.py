"""Persona registry — discovers submodule-mounted persona configs."""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


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

    def __init__(self, personas_dir: Path | str | None = None) -> None:
        if personas_dir is None:
            env = os.environ.get("ASSISTANT_PERSONAS_DIR")
            personas_dir = Path(env) if env else _DEFAULT_PERSONAS_DIR
        self.personas_dir = Path(personas_dir)
        self._cache: dict[str, PersonaConfig] = {}

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

        config = PersonaConfig(
            name=raw["name"],
            display_name=raw.get("display_name", raw["name"]),
            database_url=_env((raw.get("database") or {}).get("url_env", "")),
            graphiti_url=_env((raw.get("graphiti") or {}).get("url_env", "")),
            auth_provider=(raw.get("auth") or {}).get("provider", "custom"),
            auth_config={k: _env(v) for k, v in auth_cfg_raw.items()},
            harnesses=raw.get("harnesses", {}) or {},
            tool_sources={
                src_name: {
                    "base_url": _env(src.get("base_url_env", "")),
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
        extensions: list[Any] = []
        for ext_def in config.extensions:
            module_name = ext_def["module"]
            ext = None

            private_path = config.extensions_dir / f"{module_name}.py"
            if private_path.exists():
                ext = _load_private_extension(
                    config.name, module_name, private_path, ext_def.get("config") or {}
                )

            if ext is None:
                try:
                    mod = import_module(f"assistant.extensions.{module_name}")
                    ext = mod.create_extension(ext_def.get("config") or {})
                except ImportError as e:
                    logger.warning(
                        "Extension %r not found (public or private): %s",
                        module_name,
                        e,
                    )
                    continue

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
    return mod.create_extension(config)


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


def _env(var_name: str | None) -> str:
    if not var_name:
        return ""
    return os.environ.get(var_name, "")


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
