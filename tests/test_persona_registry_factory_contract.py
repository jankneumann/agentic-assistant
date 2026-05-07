"""Tests for the post-P5 ``create_extension`` factory contract.

Covers extension-registry / "Extension Factory Contract Accepts
Optional Persona" scenarios:

- "PersonaRegistry passes persona to all factories"
- "Stub factory ignores persona argument"
- "Legacy factory signature raises actionable TypeError"

The "Real factory constructs MSALStrategy and GraphClient internally"
and "Real factory called with persona=None raises actionable
TypeError" scenarios depend on the real four MS extensions, which land
in wp-ms-graph / wp-outlook / wp-teams / wp-sharepoint — covered there.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from assistant.core.persona import PersonaRegistry


def _write_persona_yaml(persona_dir: Path, ext_module: str) -> None:
    """Write a minimal persona.yaml that enables a single extension."""
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "persona.yaml").write_text(
        textwrap.dedent(
            f"""
            name: testpersona
            display_name: "Test Persona"
            database:
              url_env: TEST_DB_URL
            graphiti:
              url_env: TEST_GRAPHITI_URL
            auth:
              provider: custom
            extensions:
              - name: {ext_module}
                module: {ext_module}
            """
        ).strip()
        + "\n"
    )


def _install_synthetic_module(name: str, source: str) -> str:
    """Import a synthetic ``assistant.extensions.<name>`` module from source.

    Returns the fully-qualified module name. Test cleanup MUST pop it
    out of ``sys.modules`` to avoid bleeding state into other tests.
    """
    qualname = f"assistant.extensions.{name}"
    spec = compile(source, f"<{qualname}>", "exec")
    mod = type(sys)(qualname)
    sys.modules[qualname] = mod
    exec(spec, mod.__dict__)
    return qualname


# ── PersonaRegistry passes persona to all factories ──────────────────


def test_load_extensions_passes_persona_kwarg(tmp_path: Path) -> None:
    """``load_extensions`` MUST call ``create_extension(config, persona=...)``.

    Spec scenario: extension-registry / "PersonaRegistry passes persona
    to all factories".
    """
    captured: list[tuple[dict[str, Any], object]] = []
    src = textwrap.dedent(
        """
        def create_extension(config, *, persona=None):
            from tests.test_persona_registry_factory_contract import (
                _capture_call,
            )
            _capture_call(config, persona)

            class _E:
                name = "synth_pass"
                def as_langchain_tools(self): return []
                def as_ms_agent_tools(self): return []
                async def health_check(self):
                    from assistant.core.resilience import (
                        default_health_status_for_unimplemented,
                    )
                    return default_health_status_for_unimplemented(self.name)
            return _E()
        """
    )
    qualname = _install_synthetic_module("synth_pass", src)
    try:
        # Hook capture into module via globals — set on the test module
        # itself so the synthetic factory above can import it.
        sys.modules[__name__]._captured = captured  # type: ignore[attr-defined]

        personas_root = tmp_path / "personas"
        _write_persona_yaml(personas_root / "testpersona", "synth_pass")
        registry = PersonaRegistry(personas_root)
        config = registry.load("testpersona")
        registry.load_extensions(config)

        assert len(captured) == 1, "factory MUST be called exactly once"
        cfg_arg, persona_arg = captured[0]
        assert isinstance(cfg_arg, dict), "first arg MUST be the config dict"
        assert persona_arg is config, (
            "persona kwarg MUST be the loaded PersonaConfig instance, "
            f"got {persona_arg!r}"
        )
    finally:
        sys.modules.pop(qualname, None)
        sys.modules[__name__].__dict__.pop("_captured", None)


def _capture_call(config: dict[str, Any], persona: object) -> None:
    """Module-level hook the synthetic factory uses to record its call."""
    captured = sys.modules[__name__].__dict__.get("_captured")
    if captured is not None:
        captured.append((config, persona))


# ── Stub factory ignores persona argument ────────────────────────────


def test_stub_factory_ignores_persona_kwarg(tmp_path: Path) -> None:
    """Stubs (gmail/gcal/gdrive) MUST accept and ignore ``persona``.

    Spec scenario: extension-registry / "Stub factory ignores persona
    argument".
    """
    from assistant.extensions._stub import StubExtension
    from assistant.extensions.gmail import create_extension

    # Direct factory call with persona kwarg — MUST NOT raise.
    ext = create_extension({}, persona=object())
    assert isinstance(ext, StubExtension)
    assert ext.name == "gmail"


# ── Legacy factory raises actionable TypeError ───────────────────────


def test_legacy_factory_signature_raises_actionable_typeerror(
    tmp_path: Path,
) -> None:
    """A factory that does not accept ``persona`` MUST raise TypeError.

    The error message MUST identify the offending extension name and
    the migration recipe.

    Spec scenario: extension-registry / "Legacy factory signature
    raises actionable TypeError".
    """
    src = textwrap.dedent(
        """
        # Legacy signature — does NOT accept persona.
        def create_extension(config):
            class _E:
                name = "synth_legacy"
                def as_langchain_tools(self): return []
                def as_ms_agent_tools(self): return []
                async def health_check(self):
                    from assistant.core.resilience import (
                        default_health_status_for_unimplemented,
                    )
                    return default_health_status_for_unimplemented(self.name)
            return _E()
        """
    )
    qualname = _install_synthetic_module("synth_legacy", src)
    try:
        personas_root = tmp_path / "personas"
        _write_persona_yaml(personas_root / "testpersona", "synth_legacy")
        registry = PersonaRegistry(personas_root)
        config = registry.load("testpersona")

        with pytest.raises(TypeError) as exc_info:
            registry.load_extensions(config)

        msg = str(exc_info.value)
        # Identify the offending extension by name.
        assert "synth_legacy" in msg
        # Cite the migration recipe so the operator can fix it.
        assert "persona" in msg
        assert "create_extension" in msg
    finally:
        sys.modules.pop(qualname, None)


def test_factory_propagates_unrelated_typeerror(tmp_path: Path) -> None:
    """A TypeError from inside the factory body MUST propagate unchanged.

    The legacy-signature TypeError translation MUST only fire on
    signature-mismatch errors, not on programmer mistakes inside the
    factory itself.
    """
    src = textwrap.dedent(
        """
        def create_extension(config, *, persona=None):
            # A different TypeError — argument count mismatch in body.
            int("abc", 10, 99)
            return None
        """
    )
    qualname = _install_synthetic_module("synth_internal_error", src)
    try:
        personas_root = tmp_path / "personas"
        _write_persona_yaml(
            personas_root / "testpersona", "synth_internal_error"
        )
        registry = PersonaRegistry(personas_root)
        config = registry.load("testpersona")

        with pytest.raises(TypeError) as exc_info:
            registry.load_extensions(config)

        msg = str(exc_info.value)
        # The translated legacy-signature error mentions "Migration:"
        # — internal errors must NOT be translated.
        assert "Migration:" not in msg
    finally:
        sys.modules.pop(qualname, None)
