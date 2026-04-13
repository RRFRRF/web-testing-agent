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


# ── 流式事件转换 ───────────────────────────────────────────

def events_from_stream_chunk(chunk: Any, *, show_full_events: bool = False) -> list[dict[str, Any]]:
    """将 agent.stream() 的 chunk 转成结构化事件列表。"""
    events: list[dict[str, Any]] = []

    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        mode, payload = chunk
        safe_payload = make_json_safe(payload)

        if mode == "messages":
            target = payload[0] if isinstance(payload, (list, tuple)) and payload else payload
            summary = summarize_message(target)
            if summary:
                events.append(
                    {
                        "channel": "model",
                        "mode": mode,
                        "summary": summary,
                        "payload": make_json_safe(target),
                    }
                )
            return events

        if mode == "updates" and isinstance(payload, dict):
            for node_name, node_payload in payload.items():
                if node_payload is None:
                    continue
                safe_node_payload = make_json_safe(node_payload)
                if show_full_events:
                    summary = json.dumps(safe_node_payload, ensure_ascii=False, indent=2)
                elif isinstance(node_payload, dict):
                    messages = node_payload.get("messages")
                    if isinstance(messages, list) and messages:
                        summary = summarize_message(messages[-1])
                    else:
                        summary = format_inline_text(json.dumps(safe_node_payload, ensure_ascii=False))
                else:
                    summary = format_inline_text(json.dumps(safe_node_payload, ensure_ascii=False))
                events.append(
                    {
                        "channel": "node",
                        "mode": mode,
                        "node": node_name,
                        "summary": summary,
                        "payload": safe_node_payload,
                    }
                )
            return events

        if show_full_events:
            summary = json.dumps(safe_payload, ensure_ascii=False, indent=2)
        else:
            summary = format_inline_text(json.dumps(safe_payload, ensure_ascii=False))
        events.append(
            {
                "channel": mode,
                "mode": mode,
                "summary": summary,
                "payload": safe_payload,
            }
        )
        return events

    safe_chunk = make_json_safe(chunk)
    if show_full_events:
        summary = json.dumps(safe_chunk, ensure_ascii=False, indent=2)
    else:
        summary = format_inline_text(json.dumps(safe_chunk, ensure_ascii=False))
    events.append(
        {
            "channel": "event",
            "mode": "event",
            "summary": summary,
            "payload": safe_chunk,
        }
    )
    return events


# ── 流式打印 ──────────────────────────────────────────────

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


def print_stream_event(chunk: Any, *, show_full_events: bool = False) -> None:
    """将 agent.stream() 的 chunk 格式化输出到控制台。"""
    for event in events_from_stream_chunk(chunk, show_full_events=show_full_events):
        print(format_event_for_cli(event))


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
