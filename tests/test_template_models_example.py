"""The commented `models:` example in the persona template must parse.

personas/_template/persona.yaml documents the P19/P20 registry schema
as a commented-out example (GX10 local-inference node + cloud tier).
This test uncomments that block and runs it through the real
`parse_model_registry` so schema drift in the template fails CI
instead of misleading the next persona author. (`personas/_template/`
is public-by-design — an allowed read prefix per the privacy guard.)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from assistant.core.capabilities.models import parse_model_registry

TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "personas"
    / "_template"
    / "persona.yaml"
)


def _extract_commented_models_block() -> str:
    """Uncomment the contiguous comment block starting at `# models:`."""
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    start = lines.index("# models:")
    block: list[str] = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(line[2:] if line.startswith("# ") else line[1:])
    return "\n".join(block)


def test_template_models_example_parses_as_valid_registry() -> None:
    parsed = yaml.safe_load(_extract_commented_models_block())
    registry = parse_model_registry(parsed["models"])

    # The documented GX10 fleet story: chat + embedding local entries…
    gx10_chat = registry.entries["gx10-chat"]
    assert gx10_chat.dialect == "openai-compatible"
    assert gx10_chat.endpoint
    assert gx10_chat.health is not None
    assert {"cheap", "local-only", "private-data-ok"} <= set(gx10_chat.tags)

    gx10_embed = registry.entries["gx10-embed"]
    assert gx10_embed.health is not None
    assert "private-data-ok" in gx10_embed.tags

    # …cloud fallback both ways…
    assert registry.fallbacks["gx10-chat"] == ["sonnet"]
    assert registry.fallbacks["sonnet"] == ["gx10-chat"]

    # …and the P20 consumer bindings.
    for consumer in ("scheduler", "memory", "embeddings", "default"):
        assert consumer in registry.bindings
    assert registry.bindings["embeddings"] == "gx10-embed"
    assert registry.bindings["scheduler"] == "gx10-chat"
