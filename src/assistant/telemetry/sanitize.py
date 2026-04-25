"""Secret-redaction regex chain (D5).

Applied at every emission site (LangfuseProvider — and defensively
NoopProvider, though the noop never sends data anywhere). The chain
is **ordered most-specific-first** so e.g. ``sk-lf-*`` is captured
under the Langfuse-specific marker before the generic ``sk-*`` rule
runs.

The pattern list MUST match the 15-pattern authoritative list in
``observability`` spec section "Secret Sanitization". If you add a
new pattern, update the spec and ``test_sanitize.py`` together.

The set of "known-safe" semantic fields is small and intentional;
adding a name to it makes the field exempt from sanitization across
every span emitted by the assistant — only do so when the field is
guaranteed to hold short, operator-chosen identifiers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Fields whose values are passed through verbatim (no sanitization).
# Their values are short, operator-chosen identifiers expected to be
# safe (persona/role names, tool names, model identifiers, etc.).
SAFE_FIELDS: frozenset[str] = frozenset(
    {
        "persona",
        "role",
        "parent_role",
        "sub_role",
        "tool_name",
        "model",
        "name",
        "outcome",
        "op",
        "tool_kind",
    }
)

# Ordered list — MUST match the spec. Each entry is (compiled regex,
# replacement). The replacement may use back-references (e.g. ``\1``
# for the catch-all ``key=value`` rule).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 1. Langfuse-specific keys — must run before the generic sk-/pk- rules.
    (re.compile(r"(pk|sk)-lf-[A-Za-z0-9]+"), "LF-KEY-REDACTED"),
    # 2. AWS access keys.
    (re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}"), "AWS-KEY-REDACTED"),
    # 3. GitHub PATs.
    (
        re.compile(r"(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,255}"),
        "GH-TOKEN-REDACTED",
    ),
    # 4. Slack tokens.
    (
        re.compile(r"xox[abprs]-[0-9]+-[0-9]+-[A-Za-z0-9_-]{24,}"),
        "SLACK-TOKEN-REDACTED",
    ),
    # 5. Google OAuth access tokens.
    (re.compile(r"ya29\.[A-Za-z0-9_-]+"), "GOOGLE-OAUTH-REDACTED"),
    # 6. Database URLs with embedded creds.
    (
        re.compile(
            r"(postgres|postgresql|mysql|mongodb|redis)://[^\s:]+:[^\s@]+@[^\s]+"
        ),
        "DB-URL-REDACTED",
    ),
    # 7. Generic OpenAI-style secret keys.
    (re.compile(r"sk-[A-Za-z0-9]+"), "SK-REDACTED"),
    # 8. Supabase keys.
    (re.compile(r"sbp_[A-Za-z0-9]+"), "SBP-REDACTED"),
    # 9. JWTs.
    (re.compile(r"eyJ[A-Za-z0-9_\-\.]+"), "JWT-REDACTED"),
    # 10. Authorization: Basic ...
    (
        re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]+"),
        "Authorization: Basic REDACTED",
    ),
    # 11. Authorization: Digest ...
    (
        re.compile(r"Authorization:\s*Digest\s+[^\r\n]+"),
        "Authorization: Digest REDACTED",
    ),
    # 12. Cookie: ...
    (re.compile(r"Cookie:\s*[^\r\n]+"), "Cookie: REDACTED"),
    # 13. Bearer tokens.
    (re.compile(r"Bearer +[A-Za-z0-9_\-\.=]+"), "Bearer REDACTED"),
    # 14. Private submodule URLs (SSH form OR HTTPS-with-creds form).
    (
        re.compile(r"(git@[^\s:]+:[^\s]+\.git|https://[^\s@]+@[^\s]+\.git)"),
        "SUBMODULE-URL-REDACTED",
    ),
    # 15. Catch-all key=value.
    (
        re.compile(r"(?i)(password|token|secret|key|api[_-]?key)=[^\s&]+"),
        r"\1=REDACTED",
    ),
]


def sanitize(value: str) -> str:
    """Apply the 15-pattern ordered redaction chain to ``value``.

    Pure function — no I/O, deterministic. Pattern order is the spec's
    most-specific-first ordering so e.g. ``sk-lf-*`` is captured under
    the Langfuse marker before the generic ``sk-*`` rule runs.
    """
    if not isinstance(value, str):
        return value
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def sanitize_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively sanitize string values in a mapping.

    - String values for known-safe fields (``SAFE_FIELDS``) pass
      through unmodified.
    - String values for any other field are run through ``sanitize()``.
    - Nested dicts are recursed.
    - Lists of strings are walked element-wise (string elements are
      sanitized; non-strings are left alone).
    - Non-string scalars (int, float, bool, None) are unchanged.
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        out[key] = _sanitize_value(key, value)
    return out


def _sanitize_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        if key in SAFE_FIELDS:
            return value
        return sanitize(value)
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]
    return value
