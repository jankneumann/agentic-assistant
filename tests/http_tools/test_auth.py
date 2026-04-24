"""Unit tests for :mod:`assistant.http_tools.auth`.

Covers the four scenarios under the "Auth Header Resolution"
requirement in ``openspec/changes/http-tools-layer/specs/http-tools/spec.md``
plus the D11 legacy flat-string form.
"""

from __future__ import annotations

import pytest

from assistant.http_tools.auth import resolve_auth_header

# ── Bearer ───────────────────────────────────────────────────────────


def test_bearer_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``{type: bearer, env: API_TOKEN}`` + ``API_TOKEN=t0k3n`` →
    ``{"Authorization": "Bearer t0k3n"}``.
    """
    monkeypatch.setenv("API_TOKEN", "t0k3n")
    headers = resolve_auth_header({"type": "bearer", "env": "API_TOKEN"})
    assert headers == {"Authorization": "Bearer t0k3n"}


# ── API key default header ───────────────────────────────────────────


def test_api_key_default_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """``{type: api-key, env: API_KEY}`` → ``{"X-API-Key": <value>}``."""
    monkeypatch.setenv("API_KEY", "abc")
    headers = resolve_auth_header({"type": "api-key", "env": "API_KEY"})
    assert headers == {"X-API-Key": "abc"}


# ── API key custom header name ───────────────────────────────────────


def test_api_key_custom_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """``header`` key overrides the default ``X-API-Key`` name."""
    monkeypatch.setenv("API_KEY", "abc")
    headers = resolve_auth_header(
        {"type": "api-key", "env": "API_KEY", "header": "X-Custom"}
    )
    assert headers == {"X-Custom": "abc"}


# ── Missing env var → KeyError ───────────────────────────────────────


def test_missing_env_var_raises_keyerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env var named by ``env`` raises ``KeyError`` naming the var."""
    monkeypatch.delenv("UNSET_VAR_XYZ", raising=False)
    with pytest.raises(KeyError) as excinfo:
        resolve_auth_header({"type": "bearer", "env": "UNSET_VAR_XYZ"})
    # The missing variable name MUST appear in the KeyError payload so
    # callers can surface it in warning logs.
    assert "UNSET_VAR_XYZ" in str(excinfo.value)


# ── None → {} (no auth configured) ───────────────────────────────────


def test_none_returns_empty_dict() -> None:
    """``None`` means "no auth configured" → empty header dict."""
    assert resolve_auth_header(None) == {}


# ── Legacy flat-string form (D11) ────────────────────────────────────


def test_legacy_flat_string_treated_as_bearer_value() -> None:
    """A raw string is treated as a bearer token *value* (not env var).

    Per design decision D11 the primary consumer (``persona.py``)
    normalizes the legacy ``auth_header_env`` form to the structured
    dict at load-time — but ``resolve_auth_header`` still accepts a
    bare string for robustness.
    """
    headers = resolve_auth_header("t0k3n")
    assert headers == {"Authorization": "Bearer t0k3n"}
