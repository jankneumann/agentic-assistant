"""Tests for TelemetryConfig (Task 1.1).

Spec: observability — Configuration Loading Through Persona Pattern
(spec.md:246-259), and the empty-string-credential disambiguation
behavior in design D13.
"""

from __future__ import annotations

import logging

import pytest


def test_from_env_no_vars_yields_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec scenario: 'Missing credentials default to disabled'."""
    for var in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_ENVIRONMENT",
        "LANGFUSE_FLUSH_MODE",
        "LANGFUSE_SAMPLE_RATE",
        "ASSISTANT_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)

    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.enabled is False
    assert cfg.public_key == ""
    assert cfg.secret_key == ""


def test_from_env_enabled_true_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://example.test")
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "ci")
    monkeypatch.setenv("LANGFUSE_FLUSH_MODE", "per_op")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.5")

    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.enabled is True
    assert cfg.public_key == "pk-lf-test"
    assert cfg.secret_key == "sk-lf-test"
    assert cfg.host == "https://example.test"
    assert cfg.environment == "ci"
    assert cfg.flush_mode == "per_op"
    assert cfg.sample_rate == 0.5


def test_environment_defaults_to_assistant_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_ENVIRONMENT", raising=False)
    monkeypatch.setenv("ASSISTANT_PROFILE", "staging")
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.environment == "staging"


def test_environment_falls_back_to_local_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ASSISTANT_PROFILE", raising=False)
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.environment == "local"


def test_empty_public_key_records_in_empty_creds_present(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D13 (iter-2 fix H) — empty-but-present credential records the
    env var name in ``empty_creds_present`` rather than emitting a
    warning here. Factory ``_warn_once`` handles emission.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-real")
    from assistant.telemetry.config import TelemetryConfig

    with caplog.at_level(logging.WARNING, logger="assistant.telemetry"):
        cfg = TelemetryConfig.from_env()

    assert cfg.enabled is False
    assert cfg.empty_creds_present == ("LANGFUSE_PUBLIC_KEY",)
    # ``from_env`` itself MUST NOT emit any warning — that is the
    # factory's responsibility now (iter-2 fix H).
    assert not any(
        "empty" in rec.message.lower() for rec in caplog.records
    )


def test_whitespace_credential_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D13 — `.strip()` whitespace-only creds normalize to empty."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "   ")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-real")
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()

    assert cfg.enabled is False
    assert cfg.empty_creds_present == ("LANGFUSE_PUBLIC_KEY",)


def test_both_empty_creds_with_enabled_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both creds are blank-but-set, ``empty_creds_present``
    contains both env var names, ordered by appearance in spec.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.empty_creds_present == (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    )


def test_unset_credentials_no_empty_creds_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D13 — fully-unset case yields empty ``empty_creds_present`` and
    no factory warning is appropriate (only the disabled-noop path).
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.enabled is False
    assert cfg.empty_creds_present == ()


def test_disabled_with_blank_creds_does_not_record_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If LANGFUSE_ENABLED is false, set-but-blank creds are NOT
    recorded — the user did not signal intent to enable so there is
    no misconfiguration to flag.
    """
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.enabled is False
    assert cfg.empty_creds_present == ()


def test_telemetry_config_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig(
        enabled=False,
        public_key="",
        secret_key="",
        host="https://cloud.langfuse.com",
        environment="local",
        flush_mode="shutdown",
        sample_rate=1.0,
    )
    with pytest.raises(FrozenInstanceError):
        cfg.enabled = True  # type: ignore[misc]


def test_default_sample_rate_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_SAMPLE_RATE", raising=False)
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.sample_rate == 1.0


def test_default_flush_mode_is_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_FLUSH_MODE", raising=False)
    from assistant.telemetry.config import TelemetryConfig

    cfg = TelemetryConfig.from_env()
    assert cfg.flush_mode == "shutdown"
