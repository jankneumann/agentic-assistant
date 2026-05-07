"""Tests for ``core/msal_auth.py``.

Covers every msal-auth spec scenario via mocked
``msal.PublicClientApplication`` / ``msal.ConfidentialClientApplication``.
No real Microsoft Graph or Entra ID calls. Per-test temp dirs replace
the production ``personas/<name>/.cache/`` layout so the test suite
doesn't touch real persona submodules.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import assistant.core.msal_auth as msal_auth
from assistant.core.msal_auth import (
    ClientCredentialsStrategy,
    InteractiveDelegatedStrategy,
    MSALAuthenticationError,
    MSALStrategy,
    create_msal_strategy,
)
from assistant.core.persona import PersonaConfig

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _DuckPersona:
    """Minimal stand-in for ``PersonaConfig`` — only ``name`` + ``raw`` are used."""

    name: str
    raw: dict[str, Any] = field(default_factory=dict)


def _persona(name: str, raw: dict[str, Any] | None = None) -> PersonaConfig:
    """Build a duck-typed persona, ``cast``-ed to ``PersonaConfig`` for mypy.

    The strategy classes only access ``persona.name`` and ``persona.raw``;
    a full ``PersonaConfig`` carries many other fields that the tests
    don't need. ``cast`` is the type-system bridge between the test's
    minimal duck and the strict type annotation on
    ``InteractiveDelegatedStrategy``.
    """
    return cast(PersonaConfig, _DuckPersona(name=name, raw=raw or {}))


@pytest.fixture
def persona_root(tmp_path: Path) -> Path:
    """Per-test persona root with an already-correct gitignore."""
    root = tmp_path / "persona_test"
    root.mkdir()
    (root / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    return root


@pytest.fixture
def cache_path(persona_root: Path) -> Path:
    return persona_root / ".cache" / "msal_token_cache.json"


# ---------------------------------------------------------------------------
# Protocol shape — Requirement: MSAL Strategy Protocol.
# ---------------------------------------------------------------------------


def test_protocol_is_runtime_checkable(persona_root: Path, cache_path: Path) -> None:
    """Both concrete strategies satisfy ``MSALStrategy`` at runtime.

    Spec scenario: msal-auth / "Protocol is runtime-checkable".
    """
    persona = _persona("t1")
    interactive = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant-x",
        client_id="client-x",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    cc = ClientCredentialsStrategy(
        tenant_id="tenant-x",
        client_id="client-x",
        client_secret="secret",
    )
    assert isinstance(interactive, MSALStrategy)
    assert isinstance(cc, MSALStrategy)


# ---------------------------------------------------------------------------
# InteractiveDelegatedStrategy — first call, silent, force_refresh, fallback.
# ---------------------------------------------------------------------------


def _make_app_mock(
    *,
    accounts: list[Any] | None = None,
    silent_result: dict[str, Any] | None = None,
    interactive_result: dict[str, Any] | None = None,
    device_flow_init: dict[str, Any] | None = None,
    device_flow_result: dict[str, Any] | None = None,
) -> MagicMock:
    """Construct a mocked ``msal.PublicClientApplication``-shaped object."""
    app = MagicMock()
    app.get_accounts.return_value = list(accounts or [])
    app.acquire_token_silent.return_value = silent_result
    app.acquire_token_interactive.return_value = interactive_result
    app.initiate_device_flow.return_value = device_flow_init
    app.acquire_token_by_device_flow.return_value = device_flow_result
    return app


async def test_first_call_is_interactive_when_cache_empty(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "First call opens interactive flow when cache is empty"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[],
        interactive_result={"access_token": "TKN_INTERACTIVE"},
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    # Force cache to "dirty" so persistence path is exercised.
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    token = await strat.acquire_token(["Mail.Read"])
    assert token == "TKN_INTERACTIVE"
    app.acquire_token_interactive.assert_called_once()
    _, kwargs = app.acquire_token_interactive.call_args
    assert kwargs.get("scopes") == ["Mail.Read"]
    # Cache was persisted.
    assert cache_path.exists()


async def test_subsequent_call_uses_silent(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Subsequent call uses silent flow"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    fake_account = {"home_account_id": "abc"}
    app = _make_app_mock(
        accounts=[fake_account],
        silent_result={"access_token": "TKN_SILENT"},
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)

    token = await strat.acquire_token(["Mail.Read"])
    assert token == "TKN_SILENT"
    app.acquire_token_silent.assert_called_once()
    app.acquire_token_interactive.assert_not_called()


async def test_silent_failure_falls_back_to_interactive(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Silent failure falls back to interactive"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    fake_account = {"home_account_id": "abc"}
    app = _make_app_mock(
        accounts=[fake_account],
        silent_result=None,  # refresh expired
        interactive_result={"access_token": "TKN_FALLBACK"},
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    token = await strat.acquire_token(["Mail.Read"])
    assert token == "TKN_FALLBACK"
    app.acquire_token_silent.assert_called_once()
    app.acquire_token_interactive.assert_called_once()


async def test_force_refresh_skips_silent(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "force_refresh bypasses silent flow"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    fake_account = {"home_account_id": "abc"}
    app = _make_app_mock(
        accounts=[fake_account],
        silent_result={"access_token": "TKN_SILENT"},
        interactive_result={"access_token": "TKN_FORCED"},
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    token = await strat.acquire_token(["Mail.Read"], force_refresh=True)
    assert token == "TKN_FORCED"
    app.acquire_token_silent.assert_not_called()
    app.acquire_token_interactive.assert_called_once()


async def test_device_code_fallback_on_env_var(
    persona_root: Path,
    cache_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: msal-auth / "Device-code fallback when MSAL_FALLBACK_DEVICE_CODE is set"."""
    monkeypatch.setenv("MSAL_FALLBACK_DEVICE_CODE", "1")
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[],
        device_flow_init={
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "message": "Visit microsoft.com/devicelogin and enter code ABCD-EFGH",
        },
        device_flow_result={"access_token": "TKN_DEVICE"},
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    token = await strat.acquire_token(["Mail.Read"])
    assert token == "TKN_DEVICE"
    app.initiate_device_flow.assert_called_once()
    app.acquire_token_interactive.assert_not_called()
    captured = capsys.readouterr()
    assert "ABCD-EFGH" in captured.err


# ---------------------------------------------------------------------------
# Token cache file discipline — Requirement: Token Cache File Discipline.
# ---------------------------------------------------------------------------


async def test_first_write_creates_directory_with_0o700(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "First write creates directory with restrictive permissions"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    await strat.acquire_token(["Mail.Read"])
    assert cache_path.parent.exists()
    mode = os.stat(str(cache_path.parent)).st_mode
    assert mode & 0o777 == 0o700


async def test_file_written_with_0o600(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "File is written with mode 0o600"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    await strat.acquire_token(["Mail.Read"])
    mode = os.stat(str(cache_path)).st_mode
    assert mode & 0o077 == 0
    assert mode & 0o700 == 0o600


async def test_atomic_write_via_tmp_then_rename(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Atomic write via tmp + rename" + "Tmp file is created with mode 0o600 atomically".

    Verified by patching ``os.rename`` to confirm a tmp filename was
    produced before the rename, AND ``os.open`` to confirm
    ``O_EXCL | O_CREAT | O_WRONLY`` flags + 0o600 mode.
    """
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    real_open = os.open
    open_calls: list[tuple[str, int, int]] = []

    def spy_open(path: str | bytes, flags: int, mode: int = 0o777) -> int:
        spath = path.decode() if isinstance(path, bytes) else path
        if spath.endswith(".tmp"):
            open_calls.append((spath, flags, mode))
        return real_open(path, flags, mode)

    real_rename = os.rename
    rename_calls: list[tuple[str, str]] = []

    def spy_rename(src: str | bytes, dst: str | bytes) -> None:
        ssrc = src.decode() if isinstance(src, bytes) else src
        sdst = dst.decode() if isinstance(dst, bytes) else dst
        rename_calls.append((ssrc, sdst))
        return real_rename(src, dst)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "rename", spy_rename)

    await strat.acquire_token(["Mail.Read"])

    # tmp open used O_EXCL | O_CREAT | O_WRONLY, mode 0o600.
    assert open_calls, "expected at least one os.open on a .tmp path"
    _, flags, mode = open_calls[0]
    assert flags & os.O_EXCL
    assert flags & os.O_CREAT
    assert flags & os.O_WRONLY
    assert mode == 0o600
    # Rename moved the tmp file onto the final path.
    assert any(
        src.endswith(".tmp") and dst == str(cache_path)
        for src, dst in rename_calls
    )


async def test_concurrent_tmp_uses_random_suffix(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Concurrent refresh handles tmp-file collision via random suffix".

    Two strategies (simulated via two writes) MUST each produce a
    tmp path with a random suffix; neither MUST raise on the
    no-existing-file path.
    """
    persona = _persona("t1")
    seen_tmp_paths: set[str] = set()
    real_open = os.open

    def spy_open(path: str | bytes, flags: int, mode: int = 0o777) -> int:
        spath = path.decode() if isinstance(path, bytes) else path
        if spath.endswith(".tmp"):
            seen_tmp_paths.add(spath)
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", spy_open)

    for _ in range(3):
        strat = InteractiveDelegatedStrategy(
            persona,
            tenant_id="tenant",
            client_id="client",
            cache_path=cache_path,
            persona_root=persona_root,
        )
        app = _make_app_mock(
            accounts=[], interactive_result={"access_token": "TKN"}
        )
        monkeypatch.setattr(strat, "_app", app, raising=False)
        monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
        monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)
        await strat.acquire_token(["Mail.Read"])

    # Each strategy got a distinct tmp path.
    assert len(seen_tmp_paths) == 3


async def test_missing_cache_yields_empty_cache_no_error(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Missing cache file yields empty cache without error"."""
    persona = _persona("t1")
    # Construct a strategy against a non-existent cache path.
    assert not cache_path.exists()
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    # Cache was loaded with no error, has zero entries.
    assert strat._cache is not None


async def test_permission_audit_fails_fast(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Permission audit fails fast on broken filesystem state"."""
    persona = _persona("t1")
    # Create the cache dir with a permissive mode FIRST.
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(str(cache_path.parent), 0o755)  # has 0o055 bits set

    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    with pytest.raises(MSALAuthenticationError) as ei:
        await strat.acquire_token(["Mail.Read"])
    assert "chmod 700" in str(ei.value)


# ---------------------------------------------------------------------------
# Gitignore verification — Requirement: Persona Repo Gitignore Verification.
# ---------------------------------------------------------------------------


async def test_missing_gitignore_blocks_token_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Missing gitignore entry blocks token write"."""
    persona = _persona("t1")
    persona_root = tmp_path / "persona_no_gitignore"
    persona_root.mkdir()
    cache_path = persona_root / ".cache" / "msal_token_cache.json"
    # NO .gitignore created.

    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    with pytest.raises(MSALAuthenticationError) as ei:
        await strat.acquire_token(["Mail.Read"])
    assert ".gitignore" in str(ei.value)
    assert ".cache" in str(ei.value)
    # Confirm no file written.
    assert not cache_path.exists()


async def test_present_gitignore_allows_write(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Present gitignore entry allows token write"."""
    persona = _persona("t1")
    # persona_root fixture wrote ``.cache/`` to gitignore already.
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[], interactive_result={"access_token": "TKN"}
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)
    monkeypatch.setattr(strat._cache, "has_state_changed", True, raising=False)
    monkeypatch.setattr(strat._cache, "serialize", lambda: '{"x":1}', raising=False)

    # Should not raise.
    token = await strat.acquire_token(["Mail.Read"])
    assert token == "TKN"
    assert cache_path.exists()


# ---------------------------------------------------------------------------
# ClientCredentialsStrategy — Requirement: Client Credentials Strategy.
# ---------------------------------------------------------------------------


async def test_client_credentials_uses_confidential_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: msal-auth / "Strategy uses ConfidentialClientApplication"."""
    strat = ClientCredentialsStrategy(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
    )
    app = MagicMock()
    app.acquire_token_for_client.return_value = {"access_token": "TKN_APP_ONLY"}
    monkeypatch.setattr(strat, "_app", app, raising=False)

    token = await strat.acquire_token(["https://graph.microsoft.com/.default"])
    assert token == "TKN_APP_ONLY"
    app.acquire_token_for_client.assert_called_once()


async def test_client_credentials_rejects_user_scoped_scope() -> None:
    """Spec: msal-auth / "Strategy rejects user-scoped scopes"."""
    strat = ClientCredentialsStrategy(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
    )
    with pytest.raises(MSALAuthenticationError) as ei:
        await strat.acquire_token(["Mail.Read"])
    msg = str(ei.value)
    assert ".default" in msg
    assert "InteractiveDelegatedStrategy" in msg


# ---------------------------------------------------------------------------
# Strategy factory — Requirement: Strategy Selection by Persona Configuration.
# ---------------------------------------------------------------------------


def test_factory_selects_interactive_strategy(
    monkeypatch: pytest.MonkeyPatch, persona_root: Path
) -> None:
    """Spec: msal-auth / "interactive flow returns InteractiveDelegatedStrategy"."""
    monkeypatch.setenv("MS_TENANT_ID", "the-tenant")
    monkeypatch.setenv("MS_CLIENT_ID", "the-client")
    persona = _persona(
        "t1",
        raw={
            "auth": {
                "ms": {
                    "flow": "interactive",
                    "tenant_id_env": "MS_TENANT_ID",
                    "client_id_env": "MS_CLIENT_ID",
                }
            }
        },
    )
    # Factory uses persona_root from PersonaRegistry; for this test we
    # only care about the dispatch path, so monkey-patch the resolver
    # to return the test root.
    monkeypatch.setattr(
        msal_auth,
        "_resolve_cache_dir",
        lambda p: (persona_root / ".cache", persona_root),
    )
    strat = create_msal_strategy(persona)
    assert isinstance(strat, InteractiveDelegatedStrategy)


def test_factory_selects_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: msal-auth / "client_credentials flow returns ClientCredentialsStrategy"."""
    monkeypatch.setenv("MS_TENANT_ID", "the-tenant")
    monkeypatch.setenv("MS_CLIENT_ID", "the-client")
    monkeypatch.setenv("MS_CLIENT_SECRET", "the-secret")
    persona = _persona(
        "t1",
        raw={
            "auth": {
                "ms": {
                    "flow": "client_credentials",
                    "tenant_id_env": "MS_TENANT_ID",
                    "client_id_env": "MS_CLIENT_ID",
                    "client_secret_env": "MS_CLIENT_SECRET",
                }
            }
        },
    )
    strat = create_msal_strategy(persona)
    assert isinstance(strat, ClientCredentialsStrategy)


def test_factory_missing_secret_raises_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: msal-auth / "Missing required env raises with actionable message"."""
    monkeypatch.setenv("MS_TENANT_ID", "the-tenant")
    monkeypatch.setenv("MS_CLIENT_ID", "the-client")
    # MS_CLIENT_SECRET intentionally not set.
    monkeypatch.delenv("MS_CLIENT_SECRET", raising=False)
    persona = _persona(
        "t1",
        raw={
            "auth": {
                "ms": {
                    "flow": "client_credentials",
                    "tenant_id_env": "MS_TENANT_ID",
                    "client_id_env": "MS_CLIENT_ID",
                    "client_secret_env": "MS_CLIENT_SECRET",
                }
            }
        },
    )
    with pytest.raises(MSALAuthenticationError) as ei:
        create_msal_strategy(persona)
    msg = str(ei.value)
    assert "MS_CLIENT_SECRET" in msg
    assert "t1" in msg


def test_factory_missing_tenant_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory rejects missing tenant env with actionable message."""
    monkeypatch.delenv("MS_TENANT_ID", raising=False)
    persona = _persona(
        "t1",
        raw={
            "auth": {
                "ms": {
                    "flow": "interactive",
                    "tenant_id_env": "MS_TENANT_ID",
                    "client_id_env": "MS_CLIENT_ID",
                }
            }
        },
    )
    with pytest.raises(MSALAuthenticationError) as ei:
        create_msal_strategy(persona)
    assert "MS_TENANT_ID" in str(ei.value)


def test_factory_unknown_flow_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory rejects unknown auth.ms.flow with actionable message."""
    persona = _persona(
        "t1",
        raw={"auth": {"ms": {"flow": "saml"}}},
    )
    with pytest.raises(MSALAuthenticationError) as ei:
        create_msal_strategy(persona)
    assert "interactive" in str(ei.value)


# ---------------------------------------------------------------------------
# Concurrency — Requirement: Synchronous MSAL Calls Run Off the Event Loop.
# ---------------------------------------------------------------------------


async def test_acquire_token_does_not_block_event_loop(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Concurrent Graph calls are not serialized by MSAL".

    Mock acquire_token_silent to sleep 100ms synchronously. Two
    concurrent ``acquire_token`` calls MUST both complete within
    250ms (proving asyncio.to_thread parallelism). An unrelated
    ``asyncio.sleep(0)`` MUST yield within 10ms during the MSAL
    block.
    """
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )

    fake_account = {"home_account_id": "abc"}

    def slow_silent(scopes: Any, account: Any) -> dict[str, Any]:
        time.sleep(0.1)  # synchronously block the worker thread
        return {"access_token": "TKN_SLOW"}

    app = MagicMock()
    app.get_accounts.return_value = [fake_account]
    app.acquire_token_silent.side_effect = slow_silent
    monkeypatch.setattr(strat, "_app", app, raising=False)

    start = time.perf_counter()
    results = await asyncio.gather(
        strat.acquire_token(["Mail.Read"]),
        strat.acquire_token(["Mail.Read"]),
    )
    duration = time.perf_counter() - start
    assert all(t == "TKN_SLOW" for t in results)
    # Strict serialization would be >=200ms; with to_thread parallelism
    # it should land well under 250ms even on a slow CI runner.
    assert duration < 0.25, f"acquire_token serialized: {duration:.3f}s"


async def test_event_loop_remains_responsive_during_msal_block(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "Concurrent Graph calls are not serialized by MSAL".

    During a 100ms MSAL block, an unrelated ``asyncio.sleep(0)``
    MUST yield within 10ms.
    """
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )

    fake_account = {"home_account_id": "abc"}

    def slow_silent(scopes: Any, account: Any) -> dict[str, Any]:
        time.sleep(0.1)
        return {"access_token": "TKN"}

    app = MagicMock()
    app.get_accounts.return_value = [fake_account]
    app.acquire_token_silent.side_effect = slow_silent
    monkeypatch.setattr(strat, "_app", app, raising=False)

    async def yield_quickly() -> None:
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.01)

    # Run the MSAL acquire concurrently with the responsiveness probe;
    # if the loop is blocked, asyncio.wait_for will time out.
    await asyncio.gather(strat.acquire_token(["Mail.Read"]), yield_quickly())


# ---------------------------------------------------------------------------
# Auth errors don't retry — Requirement: Authentication Errors Do Not Retry.
# ---------------------------------------------------------------------------


async def test_auth_error_propagates_without_retry(
    persona_root: Path, cache_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: msal-auth / "401-equivalent auth error propagates without retry"."""
    persona = _persona("t1")
    strat = InteractiveDelegatedStrategy(
        persona,
        tenant_id="tenant",
        client_id="client",
        cache_path=cache_path,
        persona_root=persona_root,
    )
    app = _make_app_mock(
        accounts=[],
        interactive_result={
            "error": "invalid_grant",
            "error_description": "AADSTS50173: token revoked",
        },
    )
    monkeypatch.setattr(strat, "_app", app, raising=False)

    with pytest.raises(MSALAuthenticationError) as ei:
        await strat.acquire_token(["Mail.Read"])
    # Ensure interactive was called exactly once — no retry.
    assert app.acquire_token_interactive.call_count == 1
    assert "invalid_grant" in str(ei.value)


def test_error_string_is_sanitized() -> None:
    """Spec: msal-auth / "Error string is sanitized"."""
    err = MSALAuthenticationError(
        "invalid_grant: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.something"
    )
    rendered = str(err)
    # The JWT pattern from sanitize.py removes "eyJ..." → "JWT-REDACTED";
    # the Bearer-token pattern further redacts ``Bearer ...``.
    assert "eyJ0eXAi" not in rendered
    assert "JWT-REDACTED" in rendered or "Bearer REDACTED" in rendered
