"""LLM provider selection for Moonstocks analyzer."""
from __future__ import annotations

import os


def resolve_llm_provider() -> str:
    """Return 'openai' or 'anthropic'."""
    explicit = (os.environ.get("ANALYZER_LLM_PROVIDER") or "").strip().lower()
    if explicit in ("openai", "anthropic", "claude"):
        return "anthropic" if explicit in ("anthropic", "claude") else "openai"

    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    anthropic_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    prefer = (os.environ.get("ANALYZER_LLM_PREFER") or "").strip().lower()

    if prefer == "openai" and openai_key:
        return "openai"
    if prefer in ("anthropic", "claude") and anthropic_key:
        return "anthropic"
    if openai_key and not anthropic_key:
        return "openai"
    return "anthropic"
