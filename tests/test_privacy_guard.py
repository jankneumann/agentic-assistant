"""Tests for the two-layer privacy-boundary guard.

Each test builds a synthetic pytest-runnable tree under ``tmp_path`` and
invokes ``python -m pytest`` against it as a subprocess, so the real
repo's conftest + Layer 2 plugin run from a fresh pytest session inside
the tmp tree. The subprocess approach sidesteps ``pytester``'s plugin-
registration requirement (Round 1 finding I6).

All forbidden-substring literals in this file are **constructed
dynamically** from ``FORBIDDEN_PATH_NAMES`` (per D9 / Round 2 B-N4), so
this module itself never embeds a literal ``personas/<forbidden>/``
string in its source -- Layer 1 would otherwise reject it at collection.

The synthetic test trees copy the **real** conftest and plugin module
sources into tmp_path as a standalone ``tests/`` package so the guard is
actually live inside the subprocess session.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES

# Build the forbidden path fragments dynamically. After this point the
# file may contain these substrings at RUNTIME but NOT as source literals.
FORBIDDEN_NAME = FORBIDDEN_PATH_NAMES[0]  # e.g. "personal"
FORBIDDEN_PREFIX = f"personas/{FORBIDDEN_NAME}/"
FORBIDDEN_DIR_SEGMENTS = ("personas", FORBIDDEN_NAME)  # for Path-joining

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_CONFTEST = REPO_ROOT / "tests" / "conftest.py"
SRC_PLUGIN = REPO_ROOT / "tests" / "_privacy_guard_plugin.py"
SRC_CONFIG = REPO_ROOT / "tests" / "_privacy_guard_config.py"


def _scaffold_synthetic_tree(tmp_path: Path) -> Path:
    """Create a tmp pytest tree with the real guard wired in.

    Layout:
        tmp_path/
          pyproject.toml       # minimal, no [tool.pytest.ini_options]
          tests/
            __init__.py
            conftest.py              <- copied from repo
            _privacy_guard_plugin.py <- copied from repo
            _privacy_guard_config.py <- copied from repo
    Returns the ``tmp_path`` root.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'synthetic-guard-test'\nversion = '0'\n"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "conftest.py").write_text(SRC_CONFTEST.read_text())
    (tests / "_privacy_guard_plugin.py").write_text(SRC_PLUGIN.read_text())
    (tests / "_privacy_guard_config.py").write_text(SRC_CONFIG.read_text())
    return tmp_path


def _run_pytest(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Make tmp_path importable so ``tests._privacy_guard_plugin`` resolves.
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         str(tmp_path / "tests"), *extra],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )


# ── Layer 1 ────────────────────────────────────────────────────────────


def test_layer1_rejects_literal_forbidden_substring(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    # Write a test file containing the forbidden literal in its SOURCE.
    offender = root / "tests" / "test_offender.py"
    offender.write_text(
        textwrap.dedent(
            f"""
            # This file intentionally contains a forbidden substring.
            FORBIDDEN = "{FORBIDDEN_PREFIX}persona.yaml"

            def test_ok() -> None:
                assert FORBIDDEN
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode != 0, (result.stdout, result.stderr)
    combined = result.stdout + result.stderr
    assert "Privacy-boundary violation" in combined
    assert FORBIDDEN_PREFIX in combined
    assert "test_offender.py" in combined


def test_layer1_allows_fixture_and_template_references(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    ok = root / "tests" / "test_allowed.py"
    ok.write_text(
        textwrap.dedent(
            """
            # Fixture + template references are NOT forbidden.
            FIXTURE = "tests/fixtures/personas/whatever/x.yaml"
            TEMPLATE = "personas/_template/role.yaml"

            def test_ok() -> None:
                assert FIXTURE and TEMPLATE
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_layer1_excludes_its_own_implementation_files(tmp_path: Path) -> None:
    """The config + plugin files contain forbidden substrings as data --
    Layer 1 must NOT flag them."""
    root = _scaffold_synthetic_tree(tmp_path)
    # Add a placeholder test so pytest has something to collect.
    (root / "tests" / "test_dummy.py").write_text(
        "def test_ok() -> None:\n    assert True\n"
    )
    result = _run_pytest(root)
    assert result.returncode == 0, (result.stdout, result.stderr)


# ── Layer 2 ────────────────────────────────────────────────────────────


def test_layer2_rejects_path_read_text_on_forbidden(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    offender = root / "tests" / "test_runtime_read.py"
    # Build the forbidden path at RUNTIME via Path-joining so the source
    # of this synthetic test contains no forbidden literal.
    offender.write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path

            def test_runtime_read() -> None:
                target = Path({FORBIDDEN_DIR_SEGMENTS[0]!r}) / {FORBIDDEN_DIR_SEGMENTS[1]!r} / "persona.yaml"
                target.read_text()
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Privacy-boundary violation" in combined


def test_layer2_rejects_os_open_on_forbidden(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    offender = root / "tests" / "test_os_open.py"
    offender.write_text(
        textwrap.dedent(
            f"""
            import os

            def test_os_open() -> None:
                path = "{FORBIDDEN_DIR_SEGMENTS[0]}" + "/" + "{FORBIDDEN_DIR_SEGMENTS[1]}" + "/persona.yaml"
                os.open(path, os.O_RDONLY)
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Privacy-boundary violation" in combined


def test_layer2_rejects_subprocess_argv_with_forbidden(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    offender = root / "tests" / "test_subproc.py"
    offender.write_text(
        textwrap.dedent(
            f"""
            import subprocess

            def test_subproc() -> None:
                arg = "{FORBIDDEN_DIR_SEGMENTS[0]}" + "/" + "{FORBIDDEN_DIR_SEGMENTS[1]}" + "/persona.yaml"
                subprocess.run(["cat", arg])
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Privacy-boundary violation" in combined


def test_layer2_allows_reads_under_fixtures(tmp_path: Path) -> None:
    root = _scaffold_synthetic_tree(tmp_path)
    # Create a fixture file to read from.
    fixtures = root / "tests" / "fixtures" / "personas" / "synthetic"
    fixtures.mkdir(parents=True)
    (fixtures / "persona.yaml").write_text("name: synthetic\n")
    ok = root / "tests" / "test_fixture_read.py"
    ok.write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            def test_fixture_read() -> None:
                here = Path(__file__).resolve().parent
                target = here / "fixtures" / "personas" / "synthetic" / "persona.yaml"
                assert "synthetic" in target.read_text()
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_layer2_rejects_constructed_path_join(tmp_path: Path) -> None:
    """Covers the ``Path('personas') / name / 'x.yaml'`` idiom that
    substring-only checks miss."""
    root = _scaffold_synthetic_tree(tmp_path)
    offender = root / "tests" / "test_constructed.py"
    offender.write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path

            def test_constructed() -> None:
                # Name is a variable, not a literal in the source.
                name = {FORBIDDEN_DIR_SEGMENTS[1]!r}
                p = Path("personas") / name / "x.yaml"
                p.read_text()
            """
        )
    )
    result = _run_pytest(root)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Privacy-boundary violation" in combined


def test_layer2_self_probe_fires_when_install_is_noop(tmp_path: Path) -> None:
    """If the plugin's install step is short-circuited, the self-probe
    must fail the session via pytest.UsageError."""
    root = _scaffold_synthetic_tree(tmp_path)
    # Overwrite the plugin with a broken install that no-ops. Reuses the
    # public API so the self-probe path is still exercised.
    broken_plugin = textwrap.dedent(
        '''
        """Broken plugin: install is no-op to simulate CPython blocking
        Python-level rebinding of a C-slot method. Self-probe must fire."""
        from __future__ import annotations
        from pathlib import Path
        import pytest
        from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES


        class _PrivacyBoundaryViolation(pytest.UsageError):
            pass


        def _install_patches() -> None:
            return  # no-op to simulate failure


        def _self_probe() -> None:
            canary_name = FORBIDDEN_PATH_NAMES[0]
            canary = Path("personas") / canary_name / "privacy-guard-canary-nonexistent"
            try:
                canary.read_text()
            except _PrivacyBoundaryViolation:
                return
            except BaseException:
                pass
            raise pytest.UsageError("Layer 2 privacy guard failed to install")


        def pytest_configure(config: pytest.Config) -> None:
            _install_patches()
            _self_probe()
        '''
    )
    (root / "tests" / "_privacy_guard_plugin.py").write_text(broken_plugin)
    # Add a harmless test so collection happens.
    (root / "tests" / "test_harmless.py").write_text(
        "def test_ok() -> None:\n    assert True\n"
    )
    result = _run_pytest(root)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Layer 2 privacy guard failed to install" in combined
