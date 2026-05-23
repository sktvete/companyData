import json
import logging
import os
from dataclasses import is_dataclass
from datetime import datetime, timezone
from typing import IO

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

logger = logging.getLogger(__name__)


def _serialize_block(block: object) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": block.thinking}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "is_error": block.is_error,
            "content": block.content,
        }
    return {"type": type(block).__name__, "repr": repr(block)}


def serialize_message(message: object) -> dict:
    if isinstance(message, SystemMessage):
        return {
            "type": "system",
            "subtype": message.subtype,
            "data": message.data,
        }
    if isinstance(message, AssistantMessage):
        return {
            "type": "assistant",
            "model": message.model,
            "stop_reason": message.stop_reason,
            "content": [_serialize_block(b) for b in message.content],
        }
    if isinstance(message, UserMessage):
        if isinstance(message.content, str):
            content: object = message.content
        else:
            content = [_serialize_block(b) for b in message.content]
        return {"type": "user", "content": content}
    if isinstance(message, ResultMessage):
        return {
            "type": "result",
            "subtype": message.subtype,
            "is_error": message.is_error,
            "num_turns": message.num_turns,
            "duration_ms": message.duration_ms,
            "total_cost_usd": message.total_cost_usd,
            "result": message.result,
        }
    return {"type": type(message).__name__, "repr": repr(message)}


def open_run_log(ticker_exchange: str, prompt: str) -> IO[str]:
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join("logs", f"{ticker_exchange}-{ts}.log")
    fh = open(path, "w", encoding="utf-8")
    header = {
        "type": "run_start",
        "ticker_exchange": ticker_exchange,
        "timestamp": ts,
        "prompt": prompt,
    }
    fh.write(json.dumps(header) + "\n")
    fh.flush()
    return fh


def write_log(fh: IO[str], entry: dict) -> None:
    try:
        fh.write(json.dumps(entry, default=repr) + "\n")
        fh.flush()
    except Exception:
        logger.exception("Failed to write log entry")
