"""Tests for ``docker-compose.langfuse.yml`` validity (Task 4.1).

These are static smoke tests: the compose file MUST parse, declare the
expected services (postgres, clickhouse, redis, minio, langfuse-web,
langfuse-worker), expose the headless-initialization
``LANGFUSE_INIT_*`` env vars on ``langfuse-web`` (D9), and declare
healthchecks on the data-plane services so the dependent langfuse
containers can wait for them.

The tests do NOT shell out to ``docker compose up`` — they only parse
the YAML and assert structural invariants. This keeps them fast and
runnable on CI without a Docker daemon.

Spec / design references:
    - design.md D9 (LANGFUSE_INIT_* in Docker Compose)
    - docs/observability.md "Quickstart" section
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

COMPOSE_FILE = (
    Path(__file__).resolve().parent.parent.parent / "docker-compose.langfuse.yml"
)

EXPECTED_SERVICES = {
    "postgres",
    "clickhouse",
    "redis",
    "minio",
    "langfuse-web",
    "langfuse-worker",
    "init-dummy-guard",
}

REQUIRED_INIT_ENV_VARS = {
    "LANGFUSE_INIT_ORG_ID",
    "LANGFUSE_INIT_ORG_NAME",
    "LANGFUSE_INIT_PROJECT_ID",
    "LANGFUSE_INIT_PROJECT_NAME",
    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
    "LANGFUSE_INIT_PROJECT_SECRET_KEY",
    "LANGFUSE_INIT_USER_EMAIL",
    "LANGFUSE_INIT_USER_PASSWORD",
}

# Services whose healthchecks the langfuse-* containers depend on.
# minio + redis + postgres + clickhouse all need to be healthy before
# the langfuse containers start, so each MUST declare a healthcheck.
SERVICES_REQUIRING_HEALTHCHECK = {"postgres", "clickhouse", "redis", "minio"}


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    """Parse the compose file once per test module."""
    assert COMPOSE_FILE.is_file(), (
        f"docker-compose.langfuse.yml not found at {COMPOSE_FILE}"
    )
    raw = COMPOSE_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict), (
        "compose file must parse to a top-level mapping"
    )
    return cast(dict[str, Any], parsed)


def test_compose_file_parses(compose: dict[str, Any]) -> None:
    """The compose file is syntactically valid YAML and a mapping."""
    assert "services" in compose
    services = compose["services"]
    assert isinstance(services, dict)
    assert services, "services section must not be empty"


def test_compose_declares_expected_services(compose: dict[str, Any]) -> None:
    """All six services from the design (D9) MUST be present."""
    services = cast(dict[str, Any], compose["services"])
    actual = set(services.keys())
    missing = EXPECTED_SERVICES - actual
    assert not missing, (
        f"compose file is missing required services: {sorted(missing)}; "
        f"present services were {sorted(actual)}"
    )


def _service_env(service: dict[str, Any]) -> dict[str, str]:
    """Return the service's ``environment`` block as a ``dict[str, str]``.

    Compose accepts either a list of ``KEY=VALUE`` strings or a mapping;
    normalize both to a mapping for assertion purposes.
    """
    env = service.get("environment")
    if env is None:
        return {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    if isinstance(env, list):
        out: dict[str, str] = {}
        for item in env:
            if isinstance(item, str) and "=" in item:
                key, _, value = item.partition("=")
                out[key] = value
        return out
    raise AssertionError(
        f"unexpected environment block type {type(env).__name__}"
    )


def test_langfuse_web_has_init_env_vars(compose: dict[str, Any]) -> None:
    """Headless init vars (D9) MUST be set on langfuse-web.

    All ``LANGFUSE_INIT_*`` vars belong on the *web* service per the
    Langfuse self-hosting docs — the web container is the one that
    bootstraps org/project/user/keys on startup. The worker does not
    need them.
    """
    services = cast(dict[str, Any], compose["services"])
    web = services["langfuse-web"]
    env = _service_env(web)

    missing = REQUIRED_INIT_ENV_VARS - set(env.keys())
    assert not missing, (
        f"langfuse-web is missing required LANGFUSE_INIT_* vars: "
        f"{sorted(missing)}"
    )

    # Every committed credential must use the DUMMY- sentinel so secret
    # scanners skip it and a copy-paste to prod is visually wrong (D9).
    for key in (
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
        "LANGFUSE_INIT_PROJECT_SECRET_KEY",
        "LANGFUSE_INIT_USER_PASSWORD",
    ):
        assert env[key].startswith("DUMMY-"), (
            f"{key} must be a DUMMY-* sentinel in the committed compose "
            f"file (got {env[key]!r})"
        )


def test_langfuse_web_exposes_port_3100(compose: dict[str, Any]) -> None:
    """Task 4.2: the web UI MUST be reachable on host port 3100.

    Tasks/proposal pin the local-dev UI to 3100 (avoiding the default
    3000 port collision with other dev tools).
    """
    services = cast(dict[str, Any], compose["services"])
    web = services["langfuse-web"]
    ports = web.get("ports", [])
    assert any("3100" in str(p) for p in ports), (
        f"langfuse-web does not expose port 3100; ports={ports!r}"
    )


def test_data_plane_services_have_healthchecks(compose: dict[str, Any]) -> None:
    """postgres, clickhouse, redis, minio MUST declare healthchecks.

    Without healthchecks, ``depends_on: condition: service_healthy``
    on the langfuse containers cannot wait for these to be ready and
    a fresh ``up -d`` race-conditions on first boot.
    """
    services = cast(dict[str, Any], compose["services"])
    for name in SERVICES_REQUIRING_HEALTHCHECK:
        svc = services[name]
        assert "healthcheck" in svc, (
            f"service {name!r} is missing a healthcheck block"
        )
        hc = svc["healthcheck"]
        assert isinstance(hc, dict)
        assert "test" in hc, (
            f"service {name!r} healthcheck must define a test command"
        )


def test_langfuse_containers_wait_for_data_plane(compose: dict[str, Any]) -> None:
    """langfuse-web and langfuse-worker MUST depend on the data plane.

    Both containers need postgres + clickhouse + redis + minio to be
    healthy before they start, otherwise migrations fail on first run.
    """
    services = cast(dict[str, Any], compose["services"])
    for langfuse_service in ("langfuse-web", "langfuse-worker"):
        svc = services[langfuse_service]
        depends = svc.get("depends_on")
        assert depends, (
            f"{langfuse_service} must declare depends_on for the data plane"
        )
        # depends_on may be a list (short form) or a dict (long form).
        if isinstance(depends, dict):
            dep_names = set(depends.keys())
        else:
            dep_names = set(depends)
        for required in ("postgres", "clickhouse", "redis", "minio"):
            assert required in dep_names, (
                f"{langfuse_service} must depend on {required!r}; "
                f"depends_on names = {sorted(dep_names)}"
            )


# ---------------------------------------------------------------------------
# Iter-2 Fix B (IMPL_REVIEW round 1, codex blocking) — localhost-DUMMY guard.
# ---------------------------------------------------------------------------


def test_init_dummy_guard_service_is_declared(compose: dict[str, Any]) -> None:
    """Spec req observability.14 — the compose file MUST declare a
    startup-check service named ``init-dummy-guard`` whose ``command``
    inspects ``NEXTAUTH_URL`` and the ``LANGFUSE_INIT_*`` values for
    DUMMY-prefix safety.
    """
    services = cast(dict[str, Any], compose["services"])
    assert "init-dummy-guard" in services, (
        "compose file must declare an init-dummy-guard service per "
        "spec req observability.14 (escalated from design D9)"
    )
    svc = services["init-dummy-guard"]
    cmd = svc.get("command")
    assert cmd is not None, "init-dummy-guard must declare a command"
    cmd_text = str(cmd)
    assert "NEXTAUTH_URL" in cmd_text, (
        "guard command must inspect NEXTAUTH_URL"
    )
    assert "DUMMY-" in cmd_text, (
        "guard command must check for the DUMMY- prefix"
    )
    assert "localhost" in cmd_text or "127.0.0.1" in cmd_text, (
        "guard command must accept localhost / 127.0.0.1 as the safe host"
    )


def test_langfuse_web_depends_on_init_dummy_guard(
    compose: dict[str, Any],
) -> None:
    """``langfuse-web.depends_on`` MUST gate startup on the guard exit
    via ``condition: service_completed_successfully`` so a non-zero
    guard exit blocks the web service from launching.
    """
    services = cast(dict[str, Any], compose["services"])
    web = services["langfuse-web"]
    depends = web.get("depends_on")
    assert isinstance(depends, dict), (
        "langfuse-web.depends_on must use long-form (dict) so we can "
        "assert the condition for init-dummy-guard"
    )
    assert "init-dummy-guard" in depends, (
        "langfuse-web must depend on init-dummy-guard so the guard "
        "exit gates startup (spec req observability.14)"
    )
    cond = depends["init-dummy-guard"]
    assert isinstance(cond, dict)
    assert cond.get("condition") == "service_completed_successfully", (
        "init-dummy-guard dependency MUST use "
        "condition: service_completed_successfully so a non-zero "
        "guard exit blocks langfuse-web; got {cond!r}"
    )


def test_init_dummy_guard_environment_carries_canonical_dummy_values(
    compose: dict[str, Any],
) -> None:
    """The guard service receives the same ``LANGFUSE_INIT_*`` env block
    as ``langfuse-web`` so the same values that would seed the Langfuse
    instance are the ones inspected. NEXTAUTH_URL is set to localhost
    by default — the guard's exit-0 path under that local default is
    asserted in the docker-compose spec scenario.
    """
    services = cast(dict[str, Any], compose["services"])
    guard_env = _service_env(services["init-dummy-guard"])
    for key in REQUIRED_INIT_ENV_VARS:
        assert key in guard_env, (
            f"init-dummy-guard must receive {key} so the guard can "
            f"inspect the same value langfuse-web would seed"
        )
    assert "NEXTAUTH_URL" in guard_env, (
        "init-dummy-guard must receive NEXTAUTH_URL so the host check "
        "can run"
    )
    # The default committed values are ALL DUMMY-prefixed for safety,
    # but NEXTAUTH_URL is localhost so the guard returns 0.
    assert "localhost" in guard_env["NEXTAUTH_URL"] or "127.0.0.1" in guard_env["NEXTAUTH_URL"]
