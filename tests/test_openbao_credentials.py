"""OpenBao credential backend tests (agent-iam / P25).

All HTTP traffic is mocked with ``httpx.MockTransport`` — no OpenBao
server exists in the dev/CI environment; the client is a thin httpx
wrapper tested purely against canned responses.

Spec: openspec/changes/agent-iam/specs/credential-provider/spec.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from assistant.core.capabilities.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
)
from assistant.core.capabilities.openbao import (
    CredentialsConfigError,
    OpenBaoConfig,
    OpenBaoCredentialProvider,
    build_credential_provider,
    parse_credentials_config,
)
from assistant.core.persona import PersonaRegistry

BAO_URL = "https://bao.example.com"


class _FakeBao:
    """Programmable OpenBao double behind an ``httpx.MockTransport``."""

    def __init__(
        self,
        secrets: dict[str, str] | None = None,
        *,
        lease_duration: int = 3600,
        login_status: int = 200,
        read_status: int | None = None,
    ) -> None:
        self.secrets = secrets or {}
        self.lease_duration = lease_duration
        self.login_status = login_status
        self.read_status = read_status
        self.login_calls = 0
        self.read_calls: list[str] = []
        self.tokens_issued: list[str] = []
        self.seen_tokens: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/auth/approle/login":
            self.login_calls += 1
            body = json.loads(request.content)
            assert body == {"role_id": "rid", "secret_id": "sid"}
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={"errors": []})
            token = f"tok-{self.login_calls}"
            self.tokens_issued.append(token)
            return httpx.Response(
                200,
                json={
                    "auth": {
                        "client_token": token,
                        "lease_duration": self.lease_duration,
                    }
                },
            )
        assert path.startswith("/v1/secret/data/fixture/")
        ref = path.rsplit("/", 1)[-1]
        self.read_calls.append(ref)
        self.seen_tokens.append(request.headers.get("X-Vault-Token", ""))
        if self.read_status is not None:
            return httpx.Response(self.read_status, json={"errors": []})
        if ref not in self.secrets:
            return httpx.Response(404, json={"errors": []})
        return httpx.Response(
            200,
            json={"data": {"data": {"value": self.secrets[ref]}}},
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _provider(
    bao: _FakeBao,
    *,
    fallback: CredentialProvider | None = None,
    clock=None,
) -> OpenBaoCredentialProvider:
    kwargs: dict = {}
    if clock is not None:
        kwargs["clock"] = clock
    return OpenBaoCredentialProvider(
        url=BAO_URL,
        role_id="rid",
        secret_id="sid",
        persona="fixture",
        fallback=fallback or EnvCredentialProvider(scoped={}),
        http_client=bao.client(),
        **kwargs,
    )


# ── Protocol conformance ───────────────────────────────────────────────


def test_openbao_provider_satisfies_credential_provider_protocol():
    bao = _FakeBao()
    assert isinstance(_provider(bao), CredentialProvider)


# ── AppRole login + KV v2 read ─────────────────────────────────────────


def test_kv_read_logs_in_then_reads_per_persona_path():
    bao = _FakeBao({"OPENROUTER_API_KEY": "sk-123"})
    provider = _provider(bao)
    assert provider.get_credential("OPENROUTER_API_KEY") == "sk-123"
    assert bao.login_calls == 1
    assert bao.read_calls == ["OPENROUTER_API_KEY"]
    assert bao.seen_tokens == ["tok-1"]


def test_empty_vault_value_masks_the_fallback_tier():
    bao = _FakeBao({"MASKED": ""})
    fallback = EnvCredentialProvider(scoped={"MASKED": "env-value"})
    provider = _provider(bao, fallback=fallback)
    # Present in the vault namespace — even empty — wins (P13 parity).
    assert provider.get_credential("MASKED") == ""


def test_absent_ref_falls_back_to_env_tier():
    bao = _FakeBao({})
    fallback = EnvCredentialProvider(scoped={"ONLY_ENV": "env-value"})
    provider = _provider(bao, fallback=fallback)
    assert provider.get_credential("ONLY_ENV") == "env-value"
    assert bao.read_calls == ["ONLY_ENV"]  # vault WAS consulted first


def test_empty_ref_returns_empty_without_any_request():
    bao = _FakeBao()
    assert _provider(bao).get_credential("") == ""
    assert bao.login_calls == 0


def test_secret_without_value_key_treated_as_absent(caplog):
    class _WeirdBao(_FakeBao):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/auth/approle/login":
                return super().handler(request)
            return httpx.Response(
                200, json={"data": {"data": {"other": "x"}}}
            )

    fallback = EnvCredentialProvider(scoped={"REF": "env-value"})
    provider = _provider(_WeirdBao(), fallback=fallback)
    assert provider.get_credential("REF") == "env-value"


# ── Token caching + renewal before TTL expiry ──────────────────────────


def test_token_is_cached_across_reads():
    bao = _FakeBao({"A": "1", "B": "2"})
    provider = _provider(bao)
    provider.get_credential("A")
    provider.get_credential("B")
    assert bao.login_calls == 1


def test_token_renewed_before_ttl_expiry():
    now = {"t": 0.0}
    bao = _FakeBao({"A": "1"}, lease_duration=100)
    provider = _provider(bao, clock=lambda: now["t"])

    provider.get_credential("A")
    assert bao.login_calls == 1

    # Inside the safe window (expiry 100, margin 60 → renew at t>=40).
    now["t"] = 30.0
    provider.get_credential("A")
    assert bao.login_calls == 1

    # Within the renewal margin but BEFORE actual expiry → proactive
    # re-login; the new token is used on the wire.
    now["t"] = 50.0
    provider.get_credential("A")
    assert bao.login_calls == 2
    assert bao.seen_tokens[-1] == "tok-2"


def test_zero_lease_duration_token_never_renews():
    now = {"t": 0.0}
    bao = _FakeBao({"A": "1"}, lease_duration=0)
    provider = _provider(bao, clock=lambda: now["t"])
    provider.get_credential("A")
    now["t"] = 10_000_000.0
    provider.get_credential("A")
    assert bao.login_calls == 1


# ── Degradation: unreachable / failing OpenBao ─────────────────────────


def test_unreachable_server_warns_and_falls_back(caplog):
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    fallback = EnvCredentialProvider(scoped={"REF": "env-value"})
    provider = OpenBaoCredentialProvider(
        url=BAO_URL,
        role_id="rid",
        secret_id="sid",
        persona="fixture",
        fallback=fallback,
        http_client=httpx.Client(transport=httpx.MockTransport(_boom)),
    )
    with caplog.at_level("WARNING"):
        assert provider.get_credential("REF") == "env-value"
        assert provider.get_credential("REF") == "env-value"
    warnings = [
        r for r in caplog.records if "falling back" in r.getMessage()
    ]
    assert len(warnings) == 1  # warn once, not per read


def test_login_failure_falls_back():
    bao = _FakeBao(login_status=403)
    fallback = EnvCredentialProvider(scoped={"REF": "env-value"})
    assert _provider(bao, fallback=fallback).get_credential("REF") == "env-value"


def test_server_error_on_read_falls_back():
    bao = _FakeBao(read_status=500)
    fallback = EnvCredentialProvider(scoped={"REF": "env-value"})
    assert _provider(bao, fallback=fallback).get_credential("REF") == "env-value"


# ── credentials: section parsing ───────────────────────────────────────


def test_parse_missing_or_env_backend_returns_none():
    assert parse_credentials_config(None) is None
    assert parse_credentials_config({}) is None
    assert parse_credentials_config({"backend": "env"}) is None


def test_parse_openbao_backend():
    config = parse_credentials_config(
        {
            "backend": "openbao",
            "url_env": "BAO_ADDR",
            "role_id_env": "BAO_ROLE_ID",
            "secret_id_env": "BAO_SECRET_ID",
            "mount": "kv",
        }
    )
    assert config == OpenBaoConfig(
        url_env="BAO_ADDR",
        role_id_env="BAO_ROLE_ID",
        secret_id_env="BAO_SECRET_ID",
        mount="kv",
    )


def test_parse_openbao_defaults_mount_to_secret():
    config = parse_credentials_config(
        {
            "backend": "openbao",
            "url_env": "A",
            "role_id_env": "B",
            "secret_id_env": "C",
        }
    )
    assert config is not None and config.mount == "secret"


@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        ({"backend": "vault9000"}, "vault9000"),
        ({"backend": "openbao"}, "url_env"),
        ({"backend": "openbao", "url_env": "A", "role_id_env": "B"}, "secret_id_env"),
        ({"backend": "env", "surprise": 1}, "surprise"),
        ("openbao", "mapping"),
    ],
)
def test_parse_invalid_sections_raise_actionable_errors(raw, needle):
    with pytest.raises(CredentialsConfigError) as exc:
        parse_credentials_config(raw)
    assert needle in str(exc.value)


# ── build_credential_provider wiring ───────────────────────────────────


def test_builder_env_backend_returns_persona_scoped_provider(tmp_path: Path):
    (tmp_path / ".env").write_text("SCOPED=from-dotenv\n")
    provider = build_credential_provider("fixture", tmp_path, None)
    assert isinstance(provider, EnvCredentialProvider)
    assert provider.get_credential("SCOPED") == "from-dotenv"


def test_builder_unresolved_bootstrap_refs_degrade_to_env(
    tmp_path: Path, caplog
):
    config = OpenBaoConfig(
        url_env="NOPE_URL", role_id_env="NOPE_RID", secret_id_env="NOPE_SID"
    )
    with caplog.at_level("WARNING"):
        provider = build_credential_provider("fixture", tmp_path, config)
    assert isinstance(provider, EnvCredentialProvider)
    assert any("openbao" in r.getMessage() for r in caplog.records)


def test_builder_bootstrap_refs_resolve_through_persona_env(
    tmp_path: Path,
):
    # Bootstrap refs live in the persona .env — never raw os.environ.
    (tmp_path / ".env").write_text(
        "BAO_ADDR=https://bao.example.com\nBAO_RID=rid\nBAO_SID=sid\n"
    )
    config = OpenBaoConfig(
        url_env="BAO_ADDR", role_id_env="BAO_RID", secret_id_env="BAO_SID"
    )
    provider = build_credential_provider("fixture", tmp_path, config)
    assert isinstance(provider, OpenBaoCredentialProvider)


def test_persona_load_rejects_invalid_credentials_section(tmp_path: Path):
    persona_dir = tmp_path / "broken"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: broken\ncredentials:\n  backend: not-a-backend\n"
    )
    with pytest.raises(ValueError) as exc:
        PersonaRegistry(tmp_path).load("broken")
    assert "credentials" in str(exc.value)
    assert "not-a-backend" in str(exc.value)


def test_persona_load_with_openbao_but_no_bootstrap_degrades(tmp_path: Path):
    persona_dir = tmp_path / "baoful"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: baoful\n"
        "credentials:\n"
        "  backend: openbao\n"
        "  url_env: UNSET_BAO_URL\n"
        "  role_id_env: UNSET_BAO_RID\n"
        "  secret_id_env: UNSET_BAO_SID\n"
    )
    config = PersonaRegistry(tmp_path).load("baoful")
    # Degrades to the env tier — persona load never fails on a missing
    # vault (fresh standalone clone posture).
    assert isinstance(config.credentials, EnvCredentialProvider)


def test_injected_factory_still_wins_over_credentials_section(
    tmp_path: Path,
):
    persona_dir = tmp_path / "injected"
    persona_dir.mkdir()
    (persona_dir / "persona.yaml").write_text(
        "name: injected\n"
        "credentials:\n"
        "  backend: openbao\n"
        "  url_env: X\n"
        "  role_id_env: Y\n"
        "  secret_id_env: Z\n"
    )
    sentinel = EnvCredentialProvider(scoped={"K": "injected"})
    registry = PersonaRegistry(
        tmp_path, credential_provider_factory=lambda name, d: sentinel
    )
    config = registry.load("injected")
    assert config.credentials is sentinel
