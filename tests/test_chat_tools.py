"""Tests for chat tool helpers."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import chat_tools


class TestEvaluateMath(unittest.TestCase):
    def test_basic(self) -> None:
        r = chat_tools.evaluate_math_expression("(1 + 2) * 3")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"], 9)

    def test_div_and_pow(self) -> None:
        r = chat_tools.evaluate_math_expression("2 ** 10")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"], 1024)
        r2 = chat_tools.evaluate_math_expression("7 // 3")
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["result"], 2)

    def test_rejects_names(self) -> None:
        r = chat_tools.evaluate_math_expression("sqrt(4)")
        self.assertFalse(r["ok"])

    def test_div_zero(self) -> None:
        r = chat_tools.evaluate_math_expression("1/0")
        self.assertFalse(r["ok"])
        self.assertIn("zero", str(r.get("error", "")).lower())


class TestExecuteChatTool(unittest.TestCase):
    def test_evaluate_math_branch(self) -> None:
        out = chat_tools.execute_chat_tool(
            "evaluate_math",
            {"expression": "40 + 2"},
            eodhd_snapshot=lambda _s, _d: "{}",
            default_symbol="",
        )
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"], 42)

    def test_fetch_web_page_branch(self) -> None:
        def fake_fetch(u: str):
            return {
                "ok": True,
                "url": u,
                "title": "T",
                "content_type": "text/html",
                "text": "hello",
            }

        with patch.object(chat_tools, "fetch_web_page", side_effect=fake_fetch):
            out = chat_tools.execute_chat_tool(
                "fetch_web_page",
                {"url": "https://example.com/a"},
                eodhd_snapshot=lambda _s, _d: "{}",
                default_symbol="",
            )
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "hello")


class TestFetchWebPage(unittest.TestCase):
    def test_rejects_file_scheme(self) -> None:
        r = chat_tools.fetch_web_page("file:///etc/passwd")
        self.assertFalse(r["ok"])

    def test_rejects_loopback_ip(self) -> None:
        r = chat_tools.fetch_web_page("http://127.0.0.1/")
        self.assertFalse(r["ok"])

    @patch.object(chat_tools.requests, "get")
    def test_fetches_html_body(self, mock_get: Mock) -> None:
        resp = Mock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        resp.encoding = "utf-8"

        def iter_content(chunk_size: int = 65536):
            yield b"<html><head><title>Hi</title></head><body><p>Hello  world</p></body></html>"

        resp.iter_content = iter_content
        resp.close = Mock()
        mock_get.return_value = resp

        r = chat_tools.fetch_web_page("https://example.com/x")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r.get("title"), "Hi")
        self.assertIn("Hello world", r.get("text") or "")

    def test_live_example_com(self) -> None:
        try:
            r = chat_tools.fetch_web_page("https://example.com/")
        except OSError:
            self.skipTest("network unavailable")
        if not r.get("ok"):
            self.skipTest(f"fetch failed: {r.get('error')}")
        self.assertIn("Example Domain", r.get("text") or "")


if __name__ == "__main__":
    unittest.main()
