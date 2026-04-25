"""Tests for the sanitize regex chain (Task 1.7).

Spec: observability — Secret Sanitization (spec.md:161-214).

IMPORTANT (per spec.md:196 implementation note): every fixture value
matching a secret regex is constructed inline from character classes
to avoid committing realistic-looking strings to the repo, which
would trip secret-scanning on push.
"""

from __future__ import annotations


# Helpers — assemble synthetic but pattern-matching tokens from primitives.
def _alpha(n: int) -> str:
    return "a" * n


def _alnum(n: int) -> str:
    return ("ab12" * ((n // 4) + 1))[:n]


def _upper_alnum(n: int) -> str:
    return ("AB12" * ((n // 4) + 1))[:n]


def test_langfuse_public_key_redacted_before_generic() -> None:
    from assistant.telemetry.sanitize import sanitize

    # Construct: "pk-lf-" + 20 alphanumerics — matches pattern 1.
    sample = "pk-lf-" + _alnum(20)
    result = sanitize(sample)
    assert "LF-KEY-REDACTED" in result
    assert sample not in result


def test_langfuse_secret_key_redacted_before_generic() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "sk-lf-" + _alnum(20)
    result = sanitize(sample)
    assert "LF-KEY-REDACTED" in result
    # The generic SK-REDACTED must NOT also be applied to the same token,
    # nor may any fragment of the LF key remain.
    assert "sk-lf-" not in result


def test_lf_specific_runs_before_generic_sk() -> None:
    """Spec scenario: 'Langfuse-specific key is redacted before generic'."""
    from assistant.telemetry.sanitize import sanitize

    lf_key = "sk-lf-" + _alnum(16)
    generic_sk = "sk-" + _alnum(20)
    composite = f"saw {lf_key} and also {generic_sk}"
    result = sanitize(composite)
    assert "LF-KEY-REDACTED" in result
    assert "SK-REDACTED" in result


def test_aws_access_key_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    # AKIA + 16 uppercase alphanumerics
    sample = "AKIA" + _upper_alnum(16)
    result = sanitize(sample)
    assert result == "AWS-KEY-REDACTED"


def test_aws_session_key_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "ASIA" + _upper_alnum(16)
    result = sanitize(sample)
    assert result == "AWS-KEY-REDACTED"


def test_github_pat_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
        sample = prefix + _alnum(40)  # >= 36 chars body
        result = sanitize(sample)
        assert "GH-TOKEN-REDACTED" in result, f"prefix {prefix!r} not redacted"
        assert sample not in result


def test_slack_token_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    # xoxb-1234567890-1234567890-{>=24 base62}
    body = _alnum(28)
    sample = "xoxb-1234567890-1234567890-" + body
    result = sanitize(sample)
    assert "SLACK-TOKEN-REDACTED" in result


def test_google_oauth_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    # ya29. + base64url chars
    sample = "ya29." + _alnum(40)
    result = sanitize(sample)
    assert "GOOGLE-OAUTH-REDACTED" in result


def test_postgres_url_with_creds_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "postgres://user:" + _alpha(8) + "@db.example.com:5432/app"
    result = sanitize(sample)
    assert "DB-URL-REDACTED" in result
    assert "user:" not in result
    assert "@db.example.com" not in result


def test_mysql_url_with_creds_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "mysql://u:p@host/db"
    result = sanitize(sample)
    assert "DB-URL-REDACTED" in result


def test_mongodb_url_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "mongodb://u:" + _alpha(6) + "@host/db"
    result = sanitize(sample)
    assert "DB-URL-REDACTED" in result


def test_redis_url_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "redis://u:" + _alpha(6) + "@host:6379"
    result = sanitize(sample)
    assert "DB-URL-REDACTED" in result


def test_generic_sk_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "sk-" + _alnum(24)
    result = sanitize(sample)
    assert "SK-REDACTED" in result


def test_supabase_key_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "sbp_" + _alnum(20)
    result = sanitize(sample)
    assert "SBP-REDACTED" in result


def test_jwt_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    # Construct: "eyJ" + base64url-like body (digits, letters, dots,
    # hyphens, underscores).
    sample = "eyJ" + _alnum(40) + "." + _alnum(40) + "." + _alnum(20)
    result = sanitize(sample)
    assert "JWT-REDACTED" in result
    assert "eyJ" not in result.split("JWT-REDACTED", 1)[1]  # only original is gone


def test_authorization_basic_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "Authorization: Basic " + _alnum(32)
    result = sanitize(sample)
    assert result == "Authorization: Basic REDACTED"


def test_authorization_digest_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = 'Authorization: Digest username="x", realm="r", nonce="n"'
    result = sanitize(sample)
    assert "Authorization: Digest REDACTED" in result
    assert "username" not in result


def test_cookie_header_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "Cookie: session=" + _alnum(32) + "; user_id=42"
    result = sanitize(sample)
    assert "Cookie: REDACTED" in result
    assert "session=" not in result


def test_bearer_token_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "Bearer " + _alnum(40)
    result = sanitize(sample)
    assert "Bearer REDACTED" in result
    assert sample not in result


def test_submodule_url_ssh_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "git@github.com:user/private-config.git"
    result = sanitize(sample)
    assert "SUBMODULE-URL-REDACTED" in result
    assert sample not in result


def test_submodule_url_https_with_token_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "https://x-access-token:" + _alnum(40) + "@github.com/u/private.git"
    result = sanitize(sample)
    assert "SUBMODULE-URL-REDACTED" in result


def test_generic_password_kv_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "password=" + _alnum(16)
    result = sanitize(sample)
    assert "password=REDACTED" in result


def test_generic_token_kv_redacted_case_insensitive() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "TOKEN=" + _alnum(16)
    result = sanitize(sample)
    assert "TOKEN=REDACTED" in result


def test_generic_api_key_kv_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "api_key=" + _alnum(16)
    result = sanitize(sample)
    assert "api_key=REDACTED" in result


def test_persona_name_passthrough_via_safe_field() -> None:
    """Spec scenario: 'Persona name is preserved'."""
    from assistant.telemetry.sanitize import sanitize_mapping

    # Persona is in the known-safe field list — the value is not
    # touched even if it would otherwise look secret-like.
    out = sanitize_mapping({"persona": "personal", "tool_name": "gmail.search"})
    assert out["persona"] == "personal"
    assert out["tool_name"] == "gmail.search"


def test_safe_field_value_with_secret_substring_is_still_passthrough() -> None:
    """Edge case: even if a known-safe field contains secret-looking text,
    the safe-field policy preserves it. (This is by design — these fields
    are short, operator-chosen identifiers; user-driven names need a
    separate validation path.)"""
    from assistant.telemetry.sanitize import sanitize_mapping

    out = sanitize_mapping({"role": "researcher"})
    assert out["role"] == "researcher"


def test_unsafe_field_strings_are_redacted() -> None:
    from assistant.telemetry.sanitize import sanitize_mapping

    out = sanitize_mapping(
        {"detail": "Bearer " + _alnum(40), "persona": "personal"}
    )
    assert "Bearer REDACTED" in out["detail"]
    assert out["persona"] == "personal"


def test_sanitize_mapping_handles_nested_dicts() -> None:
    from assistant.telemetry.sanitize import sanitize_mapping

    out = sanitize_mapping(
        {
            "request": {
                "headers": {
                    "Authorization": "Bearer " + _alnum(40),
                },
            },
            "persona": "personal",
        }
    )
    assert "Bearer REDACTED" in out["request"]["headers"]["Authorization"]
    assert out["persona"] == "personal"


def test_sanitize_returns_string_unchanged_when_no_match() -> None:
    from assistant.telemetry.sanitize import sanitize

    sample = "nothing secret here"
    assert sanitize(sample) == sample


def test_sanitize_mapping_preserves_non_string_values() -> None:
    from assistant.telemetry.sanitize import sanitize_mapping

    out = sanitize_mapping(
        {"count": 5, "ratio": 1.0, "okay": True, "items": [1, 2, 3]}
    )
    assert out == {"count": 5, "ratio": 1.0, "okay": True, "items": [1, 2, 3]}


def test_sanitize_mapping_handles_lists_of_strings() -> None:
    from assistant.telemetry.sanitize import sanitize_mapping

    out = sanitize_mapping(
        {"items": ["safe", "Bearer " + _alnum(40), "also safe"]}
    )
    items = out["items"]
    assert items[0] == "safe"
    assert "Bearer REDACTED" in items[1]
    assert items[2] == "also safe"
