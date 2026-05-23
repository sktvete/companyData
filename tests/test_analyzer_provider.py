"""Moonstocks analyzer LLM provider selection."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ANALYZER_ROOT = Path(__file__).resolve().parents[1] / "moonstocks-ai-analyzer"
sys.path.insert(0, str(ANALYZER_ROOT))

from analyzer_provider import resolve_llm_provider  # noqa: E402


class AnalyzerProviderTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "ANALYZER_LLM_PROVIDER",
            "ANALYZER_LLM_PREFER",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ):
            os.environ.pop(key, None)

    def test_explicit_openai(self) -> None:
        os.environ["ANALYZER_LLM_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        self.assertEqual(resolve_llm_provider(), "openai")

    def test_auto_openai_when_only_openai_key(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        self.assertEqual(resolve_llm_provider(), "openai")

    def test_default_anthropic_when_both_keys(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant"
        self.assertEqual(resolve_llm_provider(), "anthropic")

    def test_prefer_openai(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant"
        os.environ["ANALYZER_LLM_PREFER"] = "openai"
        self.assertEqual(resolve_llm_provider(), "openai")


if __name__ == "__main__":
    unittest.main()
