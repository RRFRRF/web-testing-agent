"""流式输出处理、格式化与最终结果提取。"""
from __future__ import annotations

import json
from typing import Any

from messages import flatten_content, message_content


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


# ── 流式打印 ──────────────────────────────────────────────

def print_stream_event(chunk: Any, *, show_full_events: bool = False) -> None:
    """将 agent.stream() 的 chunk 格式化输出到控制台。"""
    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        mode, payload = chunk
        if mode == "messages":
            target = payload[0] if isinstance(payload, (list, tuple)) and payload else payload
            summary = summarize_message(target)
            if summary:
                print(f"[model] {summary}")
            return

        if mode == "updates" and isinstance(payload, dict):
            for node_name, node_payload in payload.items():
                if node_payload is None:
                    continue
                print(f"[node] {node_name}")
                if show_full_events:
                    print(json.dumps(make_json_safe(node_payload), ensure_ascii=False, indent=2))
                    continue
                if isinstance(node_payload, dict):
                    messages = node_payload.get("messages")
                    if isinstance(messages, list) and messages:
                        print(f"  -> {summarize_message(messages[-1])}")
                    else:
                        print(f"  -> {format_inline_text(json.dumps(make_json_safe(node_payload), ensure_ascii=False))}")
                else:
                    print(f"  -> {format_inline_text(json.dumps(make_json_safe(node_payload), ensure_ascii=False))}")
            return

        if show_full_events:
            print(f"[{mode}] {json.dumps(make_json_safe(payload), ensure_ascii=False, indent=2)}")
            return
        print(f"[{mode}] {format_inline_text(json.dumps(make_json_safe(payload), ensure_ascii=False))}")
        return

    if show_full_events:
        print(f"[event] {json.dumps(make_json_safe(chunk), ensure_ascii=False, indent=2)}")
        return
    print(f"[event] {format_inline_text(json.dumps(make_json_safe(chunk), ensure_ascii=False))}")


# ── 最终结果 ──────────────────────────────────────────────

def final_result_from_state(agent: Any, config: dict[str, Any]) -> Any:
    """从 agent state 快照中提取最终结果。"""
    snapshot = agent.get_state(config)
    values = getattr(snapshot, "values", None)
    if isinstance(values, dict):
        return values
    if values is None:
        return {}
    return {"messages": values}
