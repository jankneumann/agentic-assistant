"""TelemetryConfig — frozen dataclass with `_env()`-driven loader.

Loads ``LANGFUSE_*`` environment variables through the same ``_env()``
helper pattern used by ``assistant.core.persona`` so credentials stay
out of code and are picked up at discovery time. See spec
"Configuration Loading Through Persona Pattern" and design D13 for
the empty-string-credential semantics.

Iter-2 note (IMPL_REVIEW round 1 finding H — 2-vendor confirmed):
empty-credential detection now records *which* env vars were
empty-but-present in :attr:`TelemetryConfig.empty_creds_present`
rather than emitting a warning here. The factory at
``factory._init_provider`` reads this tuple and routes the warning
through ``_warn_once`` so it deduplicates with the rest of the
degradation warnings (matching the per-process one-warning
guarantee in req observability.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(var_name: str) -> str:
    """Read an env var; return empty string if unset.

    Mirrors ``assistant.core.persona._env`` so the telemetry layer
    follows the same credential-resolution convention.
    """
    if not var_name:
        return ""
    return os.environ.get(var_name, "")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TelemetryConfig:
    """Resolved telemetry configuration.

    All fields are typed defaults; ``from_env()`` is the canonical
    factory. The dataclass is frozen so the resolved config cannot be
    mutated mid-process.

    The ``empty_creds_present`` tuple lists the names of any
    ``LANGFUSE_*`` env vars that were *set but blank* when
    ``LANGFUSE_ENABLED=true`` — populated so the factory can route a
    distinct warning through its ``_warn_once`` dedup. Empty in the
    happy path and in the all-unset case.
    """

    enabled: bool
    public_key: str
    secret_key: str
    host: str
    environment: str
    flush_mode: str
    sample_rate: float
    empty_creds_present: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> TelemetryConfig:
        """Build a TelemetryConfig from the process environment.

        Implements D13: empty-string credentials disable telemetry. The
        empty-but-present case is recorded in
        :attr:`empty_creds_present` so the factory can emit a
        distinguishing warning (deduplicated per process). This method
        does NOT log directly; emission is the factory's job per
        iter-2 fix H.
        """
        enabled_raw = _env("LANGFUSE_ENABLED")
        public_key_raw = _env("LANGFUSE_PUBLIC_KEY")
        secret_key_raw = _env("LANGFUSE_SECRET_KEY")

        # Whitespace-only values normalize to empty per D13.
        public_key = public_key_raw.strip()
        secret_key = secret_key_raw.strip()

        host = _env("LANGFUSE_HOST").strip() or "https://cloud.langfuse.com"
        environment = (
            _env("LANGFUSE_ENVIRONMENT").strip()
            or os.environ.get("ASSISTANT_PROFILE", "").strip()
            or "local"
        )
        flush_mode = _env("LANGFUSE_FLUSH_MODE").strip() or "shutdown"

        sample_rate_raw = _env("LANGFUSE_SAMPLE_RATE").strip()
        try:
            sample_rate = float(sample_rate_raw) if sample_rate_raw else 1.0
        except ValueError:
            sample_rate = 1.0

        # Determine enabled state.
        wants_enabled = _truthy(enabled_raw)
        has_creds = bool(public_key) and bool(secret_key)

        # D13 — distinguish empty-but-present from fully-unset.
        # We check the *raw* values: if the env var is present (even as
        # empty/whitespace) and the user signaled enabled=true, that's
        # almost certainly a misconfiguration the factory should flag.
        empty_but_present: list[str] = []
        if wants_enabled:
            if "LANGFUSE_PUBLIC_KEY" in os.environ and not public_key:
                empty_but_present.append("LANGFUSE_PUBLIC_KEY")
            if "LANGFUSE_SECRET_KEY" in os.environ and not secret_key:
                empty_but_present.append("LANGFUSE_SECRET_KEY")

        enabled = wants_enabled and has_creds

        return cls(
            enabled=enabled,
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            environment=environment,
            flush_mode=flush_mode,
            sample_rate=sample_rate,
            empty_creds_present=tuple(empty_but_present),
        )
