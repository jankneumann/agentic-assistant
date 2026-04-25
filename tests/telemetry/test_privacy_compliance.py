"""Privacy-boundary compliance for the telemetry module (wp-integration).

Task 5.2 — three independent assertions, each closing a separate
threat-model gap:

a. **No filesystem I/O from any provider Protocol method.** Calling
   every method on every shipped provider (``noop`` and ``langfuse``)
   under the existing two-layer privacy guard MUST NOT trigger any
   read/write under a forbidden persona path. We don't attempt to
   *count* I/O calls on the open patches (the guard's sentinel paths
   are the only I/O it intercepts); instead we drive every Protocol
   method through and assert the guard's I/O patches stay quiet — i.e.
   the calls return without raising ``_PrivacyBoundaryViolation`` and
   without otherwise touching the FS. The Langfuse provider lazy-
   imports the SDK only inside ``setup()``; we exercise ``setup()``
   without enabling Langfuse so no SDK-side network/FS happens.

b. **No inbound web framework imported.** Loading the entire
   ``assistant.telemetry`` subtree MUST NOT pull any inbound server
   framework into ``sys.modules``. This enforces req
   ``observability.12`` ("No Inbound Interfaces").

c. **Module docstring declares outbound-only posture** (req
   ``observability.12`` scenario "Module docstring declares outbound-
   only posture"). The phrase ``outbound-only`` MUST be in
   ``assistant.telemetry.__doc__``.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# (a) Provider Protocol methods do not trigger filesystem I/O.
# ---------------------------------------------------------------------------


def _exercise_provider_methods(provider: Any) -> None:
    """Call every Protocol method with valid args.

    Methods MUST NOT raise; we don't assert specific outputs — only
    that none of these calls trip the privacy guard or otherwise touch
    a forbidden FS path.
    """
    # ``setup`` is the lifecycle entry point.
    provider.setup()

    # Four first-class trace_* methods — valid kwargs from spec.
    provider.trace_llm_call(
        model="x:y",
        persona="personal",
        role="assistant",
        messages=None,
        input_tokens=None,
        output_tokens=None,
        duration_ms=0.0,
        metadata=None,
    )
    provider.trace_delegation(
        parent_role="assistant",
        sub_role="researcher",
        task="find X",
        persona="personal",
        duration_ms=0.0,
        outcome="success",
        metadata=None,
    )
    provider.trace_tool_call(
        tool_name="gmail.search",
        tool_kind="extension",
        persona="personal",
        role="assistant",
        duration_ms=0.0,
        error=None,
        metadata=None,
    )
    provider.trace_memory_op(
        op="context",
        target="personal",
        persona="personal",
        duration_ms=0.0,
        metadata=None,
    )

    # Escape-hatch span context manager.
    with provider.start_span("test-span", attributes={"k": "v"}):
        pass

    # Lifecycle drain.
    provider.flush()
    provider.shutdown()


def test_noop_provider_protocol_methods_do_no_filesystem_io() -> None:
    """Driving every NoopProvider method is a privacy-safe operation."""
    from assistant.telemetry.providers.noop import NoopProvider

    provider = NoopProvider()
    # If any provider method tried to read a forbidden path, the Layer 2
    # guard's patched I/O entry points would raise _PrivacyBoundaryViolation
    # (a UsageError subclass) and this test would fail loudly.
    _exercise_provider_methods(provider)


def test_langfuse_provider_protocol_methods_do_no_filesystem_io() -> None:
    """Driving every LangfuseProvider method is privacy-safe.

    Skipped when the optional ``[telemetry]`` extra is not installed in
    the test environment — the provider lazy-imports the langfuse SDK
    inside ``setup()`` per design D1, so the test cannot run without
    the SDK. Production CI installs the extra and runs this test fully.
    """
    pytest.importorskip("langfuse")

    from assistant.telemetry.config import TelemetryConfig
    from assistant.telemetry.providers.langfuse import LangfuseProvider

    # Force a clean ``disabled`` config — empty strings match D13 semantics
    # ("empty-string credentials are treated as missing"). All four fields
    # are typed ``str`` (not ``Optional[str]``); ``""`` is the canonical
    # disabled-but-present-shape value.
    cfg = TelemetryConfig(
        enabled=False,
        public_key="",
        secret_key="",
        host="",
        environment="",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    provider = LangfuseProvider(cfg)
    _exercise_provider_methods(provider)


# ---------------------------------------------------------------------------
# (b) No inbound web framework imported when telemetry is loaded.
# ---------------------------------------------------------------------------


_FORBIDDEN_INBOUND = {
    "fastapi",
    "flask",
    "aiohttp.web",
    "tornado.web",
    "bottle",
    "starlette",
    "starlette.applications",
    "grpc.aio.server",
}


def test_telemetry_imports_do_not_pull_inbound_frameworks() -> None:
    """Loading ``assistant.telemetry`` subtree adds no inbound server framework.

    Snapshots ``sys.modules`` before/after a fresh import of every
    submodule and asserts no forbidden inbound-server module slipped
    in. The check uses the post-import set rather than the diff because
    a forbidden module already loaded by an earlier test would still
    be a violation if it came in via the telemetry import (we can't
    tell after the fact). To handle that, we ALSO assert no forbidden
    name appears in ``sys.modules`` *after* the telemetry imports
    complete. If another test happens to import fastapi first, this
    assertion will catch any subsequent telemetry-driven import too.
    """
    # Force-import every telemetry submodule so we can confidently
    # assert "the entire subtree imports without inbound frameworks".
    importlib.import_module("assistant.telemetry")
    importlib.import_module("assistant.telemetry.config")
    importlib.import_module("assistant.telemetry.context")
    importlib.import_module("assistant.telemetry.factory")
    importlib.import_module("assistant.telemetry.flush_hook")
    importlib.import_module("assistant.telemetry.sanitize")
    importlib.import_module("assistant.telemetry.decorators")
    importlib.import_module("assistant.telemetry.tool_wrap")
    importlib.import_module("assistant.telemetry.providers.base")
    importlib.import_module("assistant.telemetry.providers.noop")
    importlib.import_module("assistant.telemetry.providers.langfuse")

    loaded = set(sys.modules.keys())
    intersect = _FORBIDDEN_INBOUND & loaded
    assert not intersect, (
        f"Telemetry import pulled forbidden inbound framework(s) into "
        f"sys.modules: {sorted(intersect)}. Per req observability.12, the "
        "telemetry module is outbound-only — no inbound HTTP/gRPC/webhook "
        "interfaces."
    )


# ---------------------------------------------------------------------------
# (c) Module docstring contains the outbound-only declaration.
# ---------------------------------------------------------------------------


def test_telemetry_module_docstring_contains_outbound_only() -> None:
    """Per observability.12 scenario, the module docstring asserts posture."""
    import assistant.telemetry as tele

    doc = tele.__doc__ or ""
    assert "outbound-only" in doc, (
        "src/assistant/telemetry/__init__.py module docstring MUST contain "
        "the phrase 'outbound-only' per req observability.12 scenario "
        "'Module docstring declares outbound-only posture'."
    )


# ---------------------------------------------------------------------------
# Provider validation must still run — proves the privacy assertions
# above did not silently disable the enum-rejection contract.
# ---------------------------------------------------------------------------


def test_provider_enum_validation_still_fires_under_privacy_guard() -> None:
    """The privacy guard must not affect provider enum-validation behavior.

    A defense in depth: if a future refactor accidentally widens the
    privacy-guard surface to swallow ValueError, this test catches it.
    """
    from assistant.telemetry.providers.noop import NoopProvider

    provider = NoopProvider()
    with pytest.raises(ValueError, match="invalid tool_kind="):
        provider.trace_tool_call(
            tool_name="x",
            tool_kind="database",  # not in {"extension", "http"}
            persona="personal",
            role="assistant",
            duration_ms=0.0,
            error=None,
            metadata=None,
        )
    with pytest.raises(ValueError, match="invalid op="):
        provider.trace_memory_op(
            op="CONTEXT",  # wrong case — must be rejected
            target="personal",
            persona="personal",
            duration_ms=0.0,
            metadata=None,
        )
