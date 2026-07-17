"""SandboxProvider protocol, PassthroughSandbox stub, and the first real
provider — ``ContainerSandboxProvider`` (P22 meta-harness-compat).

The sandbox-provider spec defines the enforcement seam at exactly two
boundaries: tool invocation and the **extension subprocess boundary**.
This module implements the latter via :class:`SandboxedProcessRunner`:
any subprocess an extension spawns should go through a runner obtained
from the active provider's execution context, so the declared three
planes (filesystem / network / credentials) are compiled into the
actual invocation instead of being ad-hoc per extension.

``ContainerSandboxProvider`` compiles a v2 :class:`SandboxConfig` into a
``docker run`` / ``podman run`` argv (runtime autodetected, runner
injectable so tests never execute a real container). OpenShell is the
deployment-target backend candidate behind the same runner abstraction
(ADR 0007) — swapping the runner/runtime is a config change, not a code
change.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from assistant.core.capabilities.types import (
    FILESYSTEM_LEVELS,
    CredentialsPlane,
    ExecutionContext,
    FilesystemPlane,
    NetworkPlane,
    SandboxConfig,
    SandboxMount,
)

logger = logging.getLogger(__name__)

#: Container runtimes probed (in order) by :func:`detect_container_runtime`.
CONTAINER_RUNTIMES = ("docker", "podman")

#: Path inside the container where the execution context's ``work_dir``
#: is mounted.
CONTAINER_WORKSPACE = "/workspace"

#: A process runner: argv in, completed process out. Injectable so all
#: container interaction is mocked in tests (no real ``docker run`` in CI).
ProcessRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run_process(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Default :data:`ProcessRunner` — plain ``subprocess.run``."""
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False
    )


@runtime_checkable
class SandboxProvider(Protocol):
    def create_context(self, config: SandboxConfig) -> ExecutionContext: ...
    def cleanup(self, context: ExecutionContext) -> None: ...


class PassthroughSandbox:
    """No-isolation stub — still the default provider.

    Accepts any v2 config without error and without enforcement: the
    declared planes are carried on the returned context's ``metadata``
    for observability (sandbox-provider spec, "Stub accepts v2 planes
    without enforcing them").
    """

    def create_context(self, config: SandboxConfig) -> ExecutionContext:
        metadata: dict[str, Any] = {}
        planes = config.declared_planes()
        if planes:
            metadata["declared_planes"] = planes
        return ExecutionContext(
            work_dir=Path.cwd(), isolation_type="none", metadata=metadata
        )

    def cleanup(self, context: ExecutionContext) -> None:
        pass


class SandboxError(Exception):
    """Actionable sandbox failure (missing runtime, bad invocation)."""


class SandboxConfigError(Exception):
    """Actionable persona ``sandbox:`` schema/validation error."""


def detect_container_runtime(
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Return the first available container runtime name, or ``None``.

    Probes ``docker`` then ``podman`` on PATH; ``which`` is injectable
    for tests.
    """
    for runtime in CONTAINER_RUNTIMES:
        if which(runtime):
            return runtime
    return None


class ContainerSandboxProvider:
    """First real SandboxProvider — compiles the three planes into a
    container run invocation (P22; sandbox-provider spec).

    Plane compilation:

    - **Filesystem** — ``read-only`` → ``--read-only`` root plus the
      workspace mounted ``:ro``; ``workspace-write`` → ``--read-only``
      root plus the workspace mounted ``:rw``; ``full-access`` →
      writable root and workspace. Declared mounts become ``-v
      host:sandbox:ro|rw``.
    - **Network** — deny-by-default: a declared plane with an empty
      allow-list compiles to ``--network=none``. A non-empty
      allow-list is a DOCUMENTED LIMITATION under plain docker/podman
      (no per-host egress filter primitive): it compiles to
      ``SANDBOX_NET_ALLOW`` plus proxy env vars (``HTTPS_PROXY`` /
      ``HTTP_PROXY`` / ``SANDBOX_NET_PROXY``) for an egress proxy or
      an enforcing backend (OpenShell / NemoClaw network policy) to
      honor. No declared plane → the runtime's default network
      (legacy permissive behavior).
    - **Credentials** — only refs in the visibility set are exported
      as ``-e REF=value`` (resolved through the injected
      ``CredentialProvider``-shaped resolver). Container runtimes do
      not inherit the host environment, so the no-ambient-inheritance
      posture holds by construction.

    ``runner`` is injectable; the default executes the compiled argv
    via ``subprocess.run``. Tests always inject — a real ``docker
    run`` is never executed in CI.
    """

    def __init__(
        self,
        *,
        image: str,
        runtime: str | None = None,
        runner: ProcessRunner | None = None,
        credentials: Any | None = None,
        work_dir_base: Path | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        if not image:
            raise SandboxError(
                "ContainerSandboxProvider requires a container image "
                "(persona sandbox.image)."
            )
        if runtime is None:
            runtime = detect_container_runtime(which)
            if runtime is None:
                raise SandboxError(
                    "sandbox provider 'container' requires docker or podman "
                    "on PATH, and neither was found. Install one, declare "
                    "'sandbox.runtime' explicitly, or switch the persona "
                    "back to 'provider: passthrough'."
                )
        elif runtime not in CONTAINER_RUNTIMES:
            raise SandboxError(
                f"sandbox.runtime {runtime!r} is not supported; expected "
                f"one of {list(CONTAINER_RUNTIMES)}."
            )
        self.image = image
        self.runtime = runtime
        self.runner: ProcessRunner = runner or _run_process
        # CredentialProvider-shaped (``get_credential(ref) -> str``);
        # falls back to the process env when absent.
        self._credentials = credentials
        self._work_dir_base = work_dir_base

    # -- SandboxProvider protocol -------------------------------------

    def create_context(self, config: SandboxConfig) -> ExecutionContext:
        work_dir = Path(
            tempfile.mkdtemp(
                prefix="assistant-sandbox-",
                dir=(
                    str(self._work_dir_base)
                    if self._work_dir_base is not None
                    else None
                ),
            )
        )
        metadata: dict[str, Any] = {
            "provider": "container",
            "runtime": self.runtime,
            "image": self.image,
            "config": config,
        }
        planes = config.declared_planes()
        if planes:
            metadata["declared_planes"] = planes
        return ExecutionContext(
            work_dir=work_dir,
            isolation_type="container",
            metadata=metadata,
        )

    def cleanup(self, context: ExecutionContext) -> None:
        shutil.rmtree(context.work_dir, ignore_errors=True)

    # -- plane compilation ---------------------------------------------

    def compile_run_argv(
        self,
        config: SandboxConfig,
        context: ExecutionContext,
        command: Sequence[str],
    ) -> list[str]:
        """Compile config + context + command into a container-run argv."""
        argv: list[str] = [self.runtime, "run", "--rm"]
        argv += self._compile_filesystem(config.filesystem, context)
        argv += self._compile_network(config.network)
        argv += self._compile_credentials(config.credentials)
        argv.append(self.image)
        argv.extend(command)
        return argv

    def _compile_filesystem(
        self, fs: FilesystemPlane | None, context: ExecutionContext
    ) -> list[str]:
        level = fs.level if fs is not None else "full-access"
        args: list[str] = ["--workdir", CONTAINER_WORKSPACE]
        if level == "read-only":
            args += [
                "--read-only",
                "-v",
                f"{context.work_dir}:{CONTAINER_WORKSPACE}:ro",
            ]
        elif level == "workspace-write":
            args += [
                "--read-only",
                "-v",
                f"{context.work_dir}:{CONTAINER_WORKSPACE}:rw",
            ]
        else:  # full-access
            args += ["-v", f"{context.work_dir}:{CONTAINER_WORKSPACE}:rw"]
        if fs is not None:
            for mount in fs.mounts:
                mode = "rw" if mount.writable else "ro"
                args += ["-v", f"{mount.host_path}:{mount.sandbox_path}:{mode}"]
        return args

    def _compile_network(self, net: NetworkPlane | None) -> list[str]:
        if net is None:
            # Legacy permissive behavior — no plane declared.
            return []
        if not net.allow:
            return ["--network=none"]
        # DOCUMENTED LIMITATION: docker/podman have no per-host egress
        # allow-list primitive. Compile the declared posture to env
        # vars for an egress proxy / enforcing backend to honor, and
        # log so the operator knows enforcement is delegated.
        logger.warning(
            "sandbox network allow-list %s cannot be enforced by plain "
            "%s; compiled to SANDBOX_NET_ALLOW/proxy env vars — pair "
            "with an egress proxy or an enforcing backend (OpenShell / "
            "NemoClaw network policy).",
            list(net.allow),
            self.runtime,
        )
        args = ["-e", f"SANDBOX_NET_ALLOW={','.join(net.allow)}"]
        if net.proxy:
            args += [
                "-e",
                f"HTTPS_PROXY={net.proxy}",
                "-e",
                f"HTTP_PROXY={net.proxy}",
                "-e",
                f"SANDBOX_NET_PROXY={net.proxy}",
            ]
        return args

    def _compile_credentials(self, creds: CredentialsPlane | None) -> list[str]:
        if creds is None:
            return []
        args: list[str] = []
        for ref in creds.visible:
            value = self._resolve_credential(ref)
            args += ["-e", f"{ref}={value}"]
        return args

    def _resolve_credential(self, ref: str) -> str:
        if self._credentials is not None:
            getter = getattr(self._credentials, "get_credential", None)
            if callable(getter):
                return str(getter(ref))
        return os.environ.get(ref, "")


class SandboxedProcessRunner:
    """The extension-subprocess-boundary seam (sandbox-provider spec,
    "Named Sandbox Enforcement Seam").

    Extensions spawn subprocesses through :meth:`run` instead of
    calling ``subprocess`` directly. Under a
    :class:`ContainerSandboxProvider` context the command is compiled
    into a container invocation carrying the three planes; under any
    other provider it runs directly on the host (passthrough posture).
    The posture comes from the execution context — never from
    per-extension configuration.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        config: SandboxConfig,
        context: ExecutionContext,
        *,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._context = context
        if runner is not None:
            self._runner = runner
        elif isinstance(provider, ContainerSandboxProvider):
            self._runner = provider.runner
        else:
            self._runner = _run_process

    @property
    def context(self) -> ExecutionContext:
        return self._context

    def compile(self, command: Sequence[str]) -> list[str]:
        """Return the argv that :meth:`run` would execute."""
        if isinstance(self._provider, ContainerSandboxProvider):
            return self._provider.compile_run_argv(
                self._config, self._context, command
            )
        return list(command)

    def run(
        self, command: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(self.compile(command))


# -- persona ``sandbox:`` section -------------------------------------


@dataclass(frozen=True)
class SandboxSettings:
    """Parsed persona ``sandbox:`` section.

    ``provider`` selects the implementation ("passthrough" default,
    "container" for :class:`ContainerSandboxProvider`); ``config``
    carries the declared three-plane posture either way (the
    passthrough stub records it without enforcing).
    """

    provider: str = "passthrough"
    image: str = ""
    runtime: str | None = None
    config: SandboxConfig = field(default_factory=SandboxConfig)


_TOP_KEYS = {"provider", "image", "runtime", "filesystem", "network", "credentials"}


def parse_sandbox_settings(raw: Any) -> SandboxSettings | None:
    """Validate a persona ``sandbox:`` mapping; ``None`` when undeclared.

    Actionable-error posture (mirrors ``auth.a2a`` parsing): unknown
    keys, unsupported providers/runtimes/levels, and inconsistent
    declarations fail with a :class:`SandboxConfigError` naming the
    offender so persona load surfaces it directly.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise SandboxConfigError(
            f"sandbox: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise SandboxConfigError(
            f"sandbox: unknown keys {unknown}. Expected "
            f"{sorted(_TOP_KEYS)}."
        )

    provider = raw.get("provider", "passthrough")
    if provider not in ("passthrough", "container"):
        raise SandboxConfigError(
            f"sandbox.provider {provider!r} is not supported; expected "
            f"'passthrough' or 'container'."
        )

    image = raw.get("image", "")
    if provider == "container" and (not isinstance(image, str) or not image):
        raise SandboxConfigError(
            "sandbox: provider 'container' requires a non-empty 'image' "
            "(e.g. 'python:3.12-slim')."
        )

    runtime = raw.get("runtime")
    if runtime is not None and runtime not in CONTAINER_RUNTIMES:
        raise SandboxConfigError(
            f"sandbox.runtime {runtime!r} is not supported; expected one "
            f"of {list(CONTAINER_RUNTIMES)} (or omit to autodetect)."
        )

    filesystem = _parse_filesystem(raw.get("filesystem"))
    network = _parse_network(raw.get("network"))
    credentials = _parse_credentials(raw.get("credentials"))

    return SandboxSettings(
        provider=provider,
        image=image if isinstance(image, str) else "",
        runtime=runtime,
        config=SandboxConfig(
            isolation_type="container" if provider == "container" else "none",
            filesystem=filesystem,
            network=network,
            credentials=credentials,
        ),
    )


def _parse_filesystem(raw: Any) -> FilesystemPlane | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SandboxConfigError(
            f"sandbox.filesystem: expected a mapping, got "
            f"{type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"level", "mounts"})
    if unknown:
        raise SandboxConfigError(
            f"sandbox.filesystem: unknown keys {unknown}. Expected "
            f"'level' and 'mounts'."
        )
    level = raw.get("level", "full-access")
    if level not in FILESYSTEM_LEVELS:
        raise SandboxConfigError(
            f"sandbox.filesystem.level {level!r} is not one of "
            f"{list(FILESYSTEM_LEVELS)} (the Codex policy vocabulary)."
        )
    mounts: list[SandboxMount] = []
    raw_mounts = raw.get("mounts") or []
    if not isinstance(raw_mounts, list):
        raise SandboxConfigError(
            "sandbox.filesystem.mounts: expected a list of mappings."
        )
    for i, m in enumerate(raw_mounts):
        if not isinstance(m, dict):
            raise SandboxConfigError(
                f"sandbox.filesystem.mounts[{i}]: expected a mapping with "
                f"'host_path' and 'sandbox_path'."
            )
        unknown = sorted(set(m) - {"host_path", "sandbox_path", "writable"})
        if unknown:
            raise SandboxConfigError(
                f"sandbox.filesystem.mounts[{i}]: unknown keys {unknown}."
            )
        host_path = m.get("host_path")
        sandbox_path = m.get("sandbox_path")
        if not host_path or not sandbox_path:
            raise SandboxConfigError(
                f"sandbox.filesystem.mounts[{i}]: both 'host_path' and "
                f"'sandbox_path' are required."
            )
        writable = bool(m.get("writable", False))
        if writable and level == "read-only":
            raise SandboxConfigError(
                f"sandbox.filesystem.mounts[{i}]: writable mount "
                f"{host_path!r} contradicts level 'read-only'. Use "
                f"'workspace-write' if the sandbox needs writable mounts."
            )
        mounts.append(
            SandboxMount(
                host_path=str(host_path),
                sandbox_path=str(sandbox_path),
                writable=writable,
            )
        )
    return FilesystemPlane(level=level, mounts=tuple(mounts))


def _parse_network(raw: Any) -> NetworkPlane | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SandboxConfigError(
            f"sandbox.network: expected a mapping, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"allow", "proxy"})
    if unknown:
        raise SandboxConfigError(
            f"sandbox.network: unknown keys {unknown}. Expected 'allow' "
            f"and 'proxy'."
        )
    allow_raw = raw.get("allow", [])
    if allow_raw is None:
        allow_raw = []
    if not isinstance(allow_raw, list) or not all(
        isinstance(h, str) and h for h in allow_raw
    ):
        raise SandboxConfigError(
            "sandbox.network.allow: expected a list of non-empty host/CIDR "
            "strings (empty list = no network)."
        )
    proxy = raw.get("proxy")
    if proxy is not None and (not isinstance(proxy, str) or not proxy):
        raise SandboxConfigError(
            "sandbox.network.proxy: expected a non-empty URL string."
        )
    return NetworkPlane(allow=tuple(allow_raw), proxy=proxy)


def _parse_credentials(raw: Any) -> CredentialsPlane | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SandboxConfigError(
            f"sandbox.credentials: expected a mapping, got "
            f"{type(raw).__name__}."
        )
    unknown = sorted(set(raw) - {"visible"})
    if unknown:
        raise SandboxConfigError(
            f"sandbox.credentials: unknown keys {unknown}. Expected "
            f"'visible'."
        )
    visible_raw = raw.get("visible", [])
    if visible_raw is None:
        visible_raw = []
    if not isinstance(visible_raw, list) or not all(
        isinstance(r, str) and r for r in visible_raw
    ):
        raise SandboxConfigError(
            "sandbox.credentials.visible: expected a list of non-empty "
            "credential ref names."
        )
    return CredentialsPlane(visible=tuple(visible_raw))
