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
    tool_sources: dict[str, dict[str, Any]]
    extensions: list[dict[str, Any]]
    extensions_dir: Path
    default_role: str = "chief_of_staff"
    disabled_roles: list[str] = field(default_factory=list)
    prompt_augmentation: str = ""
    memory_content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PersonaRegistry:
    """Discover and load personas from submodule-mounted directories."""

    def __init__(self, personas_dir: Path | str = Path("personas")) -> None:
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
                    "auth_header": _env(src.get("auth_header_env", "")),
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


def _env(var_name: str | None) -> str:
    if not var_name:
        return ""
    return os.environ.get(var_name, "")
