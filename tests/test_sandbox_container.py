"""Tests for P22 meta-harness-compat — sandbox-provider deltas.

Covers: SandboxConfig v2 plane types, PassthroughSandbox plane
carry-without-enforce, ContainerSandboxProvider plane→argv compilation,
runtime autodetect + runner injection, SandboxedProcessRunner (the
extension-subprocess-boundary seam), persona ``sandbox:`` parsing, and
capability-resolver selection. All subprocess interaction is mocked —
no real ``docker run`` ever executes here (the skip-guarded real-run
test lives in tests/integration/).
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from assistant.core.capabilities.resolver import CapabilityResolver
from assistant.core.capabilities.sandbox import (
    ContainerSandboxProvider,
    PassthroughSandbox,
    SandboxConfigError,
    SandboxedProcessRunner,
    SandboxError,
    SandboxProvider,
    SandboxSettings,
    detect_container_runtime,
    parse_sandbox_settings,
)
from assistant.core.capabilities.types import (
    CredentialsPlane,
    FilesystemPlane,
    NetworkPlane,
    SandboxConfig,
    SandboxMount,
)


class FakeRunner:
    """Injectable ProcessRunner that records argv, never spawns."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")


class FakeCredentials:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get_credential(self, ref: str) -> str:
        return self.values.get(ref, "")


def make_provider(**kwargs: Any) -> ContainerSandboxProvider:
    kwargs.setdefault("image", "python:3.12-slim")
    kwargs.setdefault("runtime", "docker")
    kwargs.setdefault("runner", FakeRunner())
    return ContainerSandboxProvider(**kwargs)


# -- SandboxConfig v2 planes -------------------------------------------


def test_filesystem_plane_exposes_typed_attributes() -> None:
    plane = FilesystemPlane(
        level="workspace-write",
        mounts=(SandboxMount("/data", "/data", writable=False),),
    )
    assert plane.level == "workspace-write"
    assert plane.mounts[0].host_path == "/data"
    assert plane.mounts[0].writable is False


def test_filesystem_plane_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="not one of"):
        FilesystemPlane(level="everything")


def test_omitted_planes_preserve_legacy_behavior() -> None:
    cfg = SandboxConfig(isolation_type="none")
    assert cfg.filesystem is None
    assert cfg.network is None
    assert cfg.credentials is None
    assert cfg.declared_planes() == {}


def test_passthrough_carries_planes_without_enforcing() -> None:
    cfg = SandboxConfig(
        filesystem=FilesystemPlane(level="read-only"),
        network=NetworkPlane(allow=()),
    )
    ctx = PassthroughSandbox().create_context(cfg)
    assert ctx.isolation_type == "none"
    assert ctx.work_dir == Path.cwd()
    planes = ctx.metadata["declared_planes"]
    assert planes["filesystem"]["level"] == "read-only"
    assert planes["network"]["allow"] == []


# -- runtime autodetect + construction ---------------------------------


def test_detect_container_runtime_prefers_docker() -> None:
    assert detect_container_runtime(which=lambda name: f"/usr/bin/{name}") == "docker"


def test_detect_container_runtime_falls_back_to_podman() -> None:
    which = lambda name: "/usr/bin/podman" if name == "podman" else None  # noqa: E731
    assert detect_container_runtime(which=which) == "podman"


def test_provider_autodetects_runtime_via_injected_which() -> None:
    which = lambda name: "/usr/bin/podman" if name == "podman" else None  # noqa: E731
    provider = ContainerSandboxProvider(
        image="img", runner=FakeRunner(), which=which
    )
    assert provider.runtime == "podman"


def test_provider_errors_actionably_when_no_runtime_found() -> None:
    with pytest.raises(SandboxError, match="docker or podman"):
        ContainerSandboxProvider(
            image="img", runner=FakeRunner(), which=lambda name: None
        )


def test_provider_rejects_unknown_runtime() -> None:
    with pytest.raises(SandboxError, match="not supported"):
        make_provider(runtime="lxc")


def test_provider_satisfies_sandbox_provider_protocol() -> None:
    assert isinstance(make_provider(), SandboxProvider)


def test_create_context_and_cleanup_manage_work_dir(tmp_path: Path) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    ctx = provider.create_context(SandboxConfig())
    assert ctx.isolation_type == "container"
    assert ctx.work_dir.exists()
    assert ctx.work_dir.parent == tmp_path
    assert ctx.metadata["runtime"] == "docker"
    provider.cleanup(ctx)
    assert not ctx.work_dir.exists()


# -- filesystem plane compilation ---------------------------------------


def _argv(provider: ContainerSandboxProvider, cfg: SandboxConfig) -> list[str]:
    ctx = provider.create_context(cfg)
    try:
        return provider.compile_run_argv(cfg, ctx, ["echo", "hi"])
    finally:
        provider.cleanup(ctx)


def test_fs_read_only_compiles_to_read_only_root_and_ro_workspace(
    tmp_path: Path,
) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(filesystem=FilesystemPlane(level="read-only"))
    argv = _argv(provider, cfg)
    assert "--read-only" in argv
    workspace_mounts = [a for a in argv if a.endswith(":/workspace:ro")]
    assert len(workspace_mounts) == 1


def test_fs_workspace_write_mounts_workspace_rw_root_ro(
    tmp_path: Path,
) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(filesystem=FilesystemPlane(level="workspace-write"))
    argv = _argv(provider, cfg)
    assert "--read-only" in argv
    assert any(a.endswith(":/workspace:rw") for a in argv)


def test_fs_full_access_keeps_root_writable(tmp_path: Path) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(filesystem=FilesystemPlane(level="full-access"))
    argv = _argv(provider, cfg)
    assert "--read-only" not in argv
    assert any(a.endswith(":/workspace:rw") for a in argv)


def test_fs_mounts_compile_with_declared_writability(tmp_path: Path) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(
        filesystem=FilesystemPlane(
            level="workspace-write",
            mounts=(
                SandboxMount("/data", "/mnt/data", writable=False),
                SandboxMount("/scratch", "/mnt/scratch", writable=True),
            ),
        )
    )
    argv = _argv(provider, cfg)
    assert "/data:/mnt/data:ro" in argv
    assert "/scratch:/mnt/scratch:rw" in argv


def test_no_fs_plane_defaults_to_full_access_posture(tmp_path: Path) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    argv = _argv(provider, SandboxConfig())
    assert "--read-only" not in argv


# -- network plane compilation -------------------------------------------


def test_network_empty_allow_list_compiles_to_network_none(
    tmp_path: Path,
) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(network=NetworkPlane(allow=()))
    argv = _argv(provider, cfg)
    assert "--network=none" in argv


def test_network_allow_list_compiles_to_env_vars_documented_limitation(
    tmp_path: Path,
) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    cfg = SandboxConfig(
        network=NetworkPlane(
            allow=("api.anthropic.com", "10.0.0.0/8"),
            proxy="http://proxy:3128",
        )
    )
    argv = _argv(provider, cfg)
    assert "--network=none" not in argv
    assert "SANDBOX_NET_ALLOW=api.anthropic.com,10.0.0.0/8" in argv
    assert "HTTPS_PROXY=http://proxy:3128" in argv
    assert "HTTP_PROXY=http://proxy:3128" in argv
    assert "SANDBOX_NET_PROXY=http://proxy:3128" in argv


def test_no_network_plane_keeps_default_network(tmp_path: Path) -> None:
    provider = make_provider(work_dir_base=tmp_path)
    argv = _argv(provider, SandboxConfig())
    assert "--network=none" not in argv
    assert not any(a.startswith("SANDBOX_NET_ALLOW") for a in argv)


# -- credentials plane compilation ----------------------------------------


def test_credentials_plane_exports_only_visible_refs(tmp_path: Path) -> None:
    provider = make_provider(
        work_dir_base=tmp_path,
        credentials=FakeCredentials(
            {"GMAIL_TOKEN": "tok-123", "OTHER_SECRET": "nope"}
        ),
    )
    cfg = SandboxConfig(credentials=CredentialsPlane(visible=("GMAIL_TOKEN",)))
    argv = _argv(provider, cfg)
    assert "GMAIL_TOKEN=tok-123" in argv
    assert not any("OTHER_SECRET" in a for a in argv)


def test_no_credentials_plane_exports_nothing(tmp_path: Path) -> None:
    provider = make_provider(
        work_dir_base=tmp_path,
        credentials=FakeCredentials({"GMAIL_TOKEN": "tok-123"}),
    )
    argv = _argv(provider, SandboxConfig())
    assert not any("GMAIL_TOKEN" in a for a in argv)


# -- SandboxedProcessRunner (extension subprocess boundary) ----------------


def test_process_runner_wraps_command_in_container_invocation(
    tmp_path: Path,
) -> None:
    fake = FakeRunner()
    provider = make_provider(work_dir_base=tmp_path, runner=fake)
    cfg = SandboxConfig(network=NetworkPlane(allow=()))
    ctx = provider.create_context(cfg)
    runner = SandboxedProcessRunner(provider, cfg, ctx)
    result = runner.run(["echo", "hi"])
    assert result.returncode == 0
    assert len(fake.calls) == 1
    argv = fake.calls[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv
    assert argv[-2:] == ["echo", "hi"]
    provider.cleanup(ctx)


def test_process_runner_posture_comes_from_context_not_extension_config(
    tmp_path: Path,
) -> None:
    """The compiled posture is derived from the execution context's
    config — the runner takes no per-extension isolation knobs."""
    fake = FakeRunner()
    provider = make_provider(work_dir_base=tmp_path, runner=fake)
    cfg = SandboxConfig(filesystem=FilesystemPlane(level="read-only"))
    ctx = provider.create_context(cfg)
    runner = SandboxedProcessRunner(provider, cfg, ctx)
    assert "--read-only" in runner.compile(["ls"])
    provider.cleanup(ctx)


def test_process_runner_passthrough_runs_command_unwrapped() -> None:
    fake = FakeRunner()
    provider = PassthroughSandbox()
    cfg = SandboxConfig()
    ctx = provider.create_context(cfg)
    runner = SandboxedProcessRunner(provider, cfg, ctx, runner=fake)
    runner.run(["echo", "hi"])
    assert fake.calls == [["echo", "hi"]]


# -- persona ``sandbox:`` parsing -------------------------------------------


def test_parse_sandbox_settings_none_when_undeclared() -> None:
    assert parse_sandbox_settings(None) is None
    assert parse_sandbox_settings({}) is None


def test_parse_sandbox_settings_full_container_declaration() -> None:
    settings = parse_sandbox_settings(
        {
            "provider": "container",
            "image": "python:3.12-slim",
            "runtime": "podman",
            "filesystem": {
                "level": "workspace-write",
                "mounts": [
                    {"host_path": "/data", "sandbox_path": "/data"},
                ],
            },
            "network": {"allow": ["api.anthropic.com"], "proxy": "http://p:1"},
            "credentials": {"visible": ["GMAIL_TOKEN"]},
        }
    )
    assert settings is not None
    assert settings.provider == "container"
    assert settings.image == "python:3.12-slim"
    assert settings.runtime == "podman"
    assert settings.config.isolation_type == "container"
    assert settings.config.filesystem is not None
    assert settings.config.filesystem.level == "workspace-write"
    assert settings.config.network == NetworkPlane(
        allow=("api.anthropic.com",), proxy="http://p:1"
    )
    assert settings.config.credentials == CredentialsPlane(
        visible=("GMAIL_TOKEN",)
    )


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("container", "expected a mapping"),
        ({"provider": "firecracker"}, "not supported"),
        ({"provider": "container"}, "requires a non-empty 'image'"),
        ({"provider": "container", "image": "i", "bogus": 1}, "unknown keys"),
        (
            {"provider": "container", "image": "i", "runtime": "lxc"},
            "not supported",
        ),
        (
            {"provider": "container", "image": "i", "filesystem": {"level": "rw"}},
            "Codex policy vocabulary",
        ),
        (
            {
                "provider": "container",
                "image": "i",
                "filesystem": {"mounts": [{"host_path": "/a"}]},
            },
            "'sandbox_path'",
        ),
        (
            {
                "provider": "container",
                "image": "i",
                "filesystem": {
                    "level": "read-only",
                    "mounts": [
                        {
                            "host_path": "/a",
                            "sandbox_path": "/a",
                            "writable": True,
                        }
                    ],
                },
            },
            "contradicts level 'read-only'",
        ),
        (
            {"provider": "container", "image": "i", "network": {"allow": "x"}},
            "list of non-empty",
        ),
        (
            {"provider": "container", "image": "i", "credentials": {"see": []}},
            "unknown keys",
        ),
    ],
)
def test_parse_sandbox_settings_actionable_errors(
    raw: Any, match: str
) -> None:
    with pytest.raises(SandboxConfigError, match=match):
        parse_sandbox_settings(raw)


def test_persona_load_parses_sandbox_section(tmp_path: Path) -> None:
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "sandboxed"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: sandboxed\n"
        "sandbox:\n"
        "  provider: container\n"
        "  image: python:3.12-slim\n"
        "  network:\n"
        "    allow: []\n"
    )
    pc = PersonaRegistry(personas_dir=tmp_path).load("sandboxed")
    assert pc.sandbox is not None
    assert pc.sandbox.provider == "container"
    assert pc.sandbox.config.network == NetworkPlane(allow=())


def test_persona_load_surfaces_sandbox_config_errors(tmp_path: Path) -> None:
    from assistant.core.persona import PersonaRegistry

    persona_dir = tmp_path / "broken"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: broken\nsandbox:\n  provider: container\n"
    )
    with pytest.raises(ValueError, match="invalid sandbox: section"):
        PersonaRegistry(personas_dir=tmp_path).load("broken")


# -- resolver selection ------------------------------------------------------


class _StubPersona:
    """Minimal persona shim for resolver tests."""

    def __init__(self, sandbox: SandboxSettings | None) -> None:
        self.name = "stub"
        self.sandbox = sandbox
        self.database_url = ""
        self.credentials = FakeCredentials({})


def test_resolver_defaults_to_passthrough_without_sandbox_section() -> None:
    cs = CapabilityResolver().resolve(_StubPersona(None), "sdk", object())
    assert isinstance(cs.sandbox, PassthroughSandbox)


def test_resolver_selects_container_provider_when_persona_requests_it() -> None:
    settings = parse_sandbox_settings(
        {"provider": "container", "image": "img", "runtime": "docker"}
    )
    cs = CapabilityResolver().resolve(_StubPersona(settings), "sdk", object())
    assert isinstance(cs.sandbox, ContainerSandboxProvider)
    assert cs.sandbox.image == "img"
    assert cs.sandbox.runtime == "docker"


def test_resolver_passthrough_for_explicit_passthrough_provider() -> None:
    settings = parse_sandbox_settings(
        {"provider": "passthrough", "network": {"allow": []}}
    )
    cs = CapabilityResolver().resolve(_StubPersona(settings), "sdk", object())
    assert isinstance(cs.sandbox, PassthroughSandbox)


def test_resolver_sandbox_factory_still_wins() -> None:
    marker = PassthroughSandbox()
    settings = parse_sandbox_settings(
        {"provider": "container", "image": "img", "runtime": "docker"}
    )
    resolver = CapabilityResolver(sandbox_factory=lambda: marker)
    cs = resolver.resolve(_StubPersona(settings), "sdk", object())
    assert cs.sandbox is marker
