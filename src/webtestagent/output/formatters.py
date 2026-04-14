"""格式化工具与文本提取。"""
from __future__ import annotations

import json
from typing import Any

from webtestagent.middleware.message_normalizer import flatten_content, message_content


# ── 格式化工具 ──────────────────────────────────────────────

def format_inline_text(value: str, *, limit: int = 120) -> str:
    """将多行文本压缩为一行，超长截断。"""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def make_json_safe(value: Any) -> Any:
    """将任意对象递归转换为 JSON 可序列化的结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return make_json_safe(model_dump())
    return str(value)


# ── 文本提取 ──────────────────────────────────────────────

def extract_text(result: Any) -> str:
    """从 agent 最终结果中提取可读文本。"""
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                text = flatten_content(message_content(message))
                if text:
                    return text
        return json.dumps(make_json_safe(result), ensure_ascii=False, indent=2)

    content = getattr(result, "content", None)
    text = flatten_content(content)
    if text:
        return text

    return str(result)


def summarize_message(message: Any) -> str:
    """摘要一条消息用于控制台输出。"""
    content = flatten_content(message_content(message))
    if content:
        return format_inline_text(content)

    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list) and tool_calls:
        names = []
        for call in tool_calls:
            if isinstance(call, dict):
                name = call.get("name") or call.get("function", {}).get("name")
            else:
                name = getattr(call, "name", None)
            if name:
                names.append(str(name))
        if names:
            return f"tool_calls: {', '.join(names)}"

    return format_inline_text(json.dumps(make_json_safe(message), ensure_ascii=False))


# ── CLI 事件格式化 ────────────────────────────────────────

def format_event_for_cli(event: dict[str, Any]) -> str:
    """将结构化事件转成 CLI 可读文本。"""
    channel = str(event.get("channel") or "event")
    summary = str(event.get("summary") or "")

    if channel == "model":
        return f"[model] {summary}"

    if channel == "node":
        node_name = str(event.get("node") or "unknown")
        return f"[node] {node_name}\n  -> {summary}"

    return f"[{channel}] {summary}"
