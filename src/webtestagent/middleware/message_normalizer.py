"""LangChain 消息归一化中间件。

将所有消息的 content 扁平化为纯文本字符串，
以兼容不支持多模态 content 结构的模型端点（如 GLM-5）。
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import wrap_model_call
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage


def flatten_content(content: Any) -> str:
    """将各种格式的 content 统一转换为纯文本。"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text).strip())
        return "\n".join(part for part in parts if part).strip()
    return ""


def message_content(message: Any) -> Any:
    """统一提取消息的 content 字段。"""
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def clone_message_with_text_content(message: BaseMessage) -> BaseMessage:
    """克隆消息，将 content 归一化为纯文本。"""
    text_content = flatten_content(message_content(message))

    if isinstance(message, HumanMessage):
        return HumanMessage(
            content=text_content, name=message.name, id=message.id,
            additional_kwargs=message.additional_kwargs,
        )

    if isinstance(message, SystemMessage):
        return SystemMessage(
            content=text_content, name=message.name, id=message.id,
            additional_kwargs=message.additional_kwargs,
        )

    if isinstance(message, ToolMessage):
        return ToolMessage(
            content=text_content,
            tool_call_id=message.tool_call_id,
            name=message.name,
            id=message.id,
            additional_kwargs=message.additional_kwargs,
            status=getattr(message, "status", "success"),
        )

    if isinstance(message, AIMessage):
        return AIMessage(
            content=text_content,
            name=message.name,
            id=message.id,
            additional_kwargs=message.additional_kwargs,
            response_metadata=message.response_metadata,
            tool_calls=message.tool_calls,
            invalid_tool_calls=getattr(message, "invalid_tool_calls", []),
        )

    return message


@wrap_model_call
def normalize_messages_for_compatible_endpoint(request, handler):
    """中间件：将所有消息 content 转换为纯文本后再发给模型。"""
    normalized_messages = [clone_message_with_text_content(msg) for msg in request.messages]
    return handler(request.override(messages=normalized_messages))
