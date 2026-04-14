"""流式输出处理与最终结果提取。"""
from __future__ import annotations

import json
from typing import Any

from webtestagent.output.formatters import (
    format_event_for_cli,
    format_inline_text,
    make_json_safe,
    summarize_message,
)


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
