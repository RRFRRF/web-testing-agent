"""测试 middleware/message_normalizer.py：消息内容归一化。"""

from __future__ import annotations


from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from webtestagent.middleware.message_normalizer import (
    clone_message_with_text_content,
    flatten_content,
    message_content,
)


# ── flatten_content ──────────────────────────────────────


class TestFlattenContent:
    def test_string(self):
        assert flatten_content("hello world") == "hello world"

    def test_string_stripped(self):
        assert flatten_content("  hello  ") == "hello"

    def test_list_of_strings(self):
        assert flatten_content(["hello", "world"]) == "hello\nworld"

    def test_list_of_text_dicts(self):
        content = [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]
        assert flatten_content(content) == "part1\npart2"

    def test_list_mixed(self):
        content = ["plain", {"type": "text", "text": "dict"}]
        assert flatten_content(content) == "plain\ndict"

    def test_empty_list(self):
        assert flatten_content([]) == ""

    def test_none_content(self):
        assert flatten_content(None) == ""

    def test_int_content(self):
        assert flatten_content(42) == ""

    def test_dict_without_text_type(self):
        assert flatten_content([{"type": "image", "url": "x"}]) == ""


# ── message_content ──────────────────────────────────────


class TestMessageContent:
    def test_dict_message(self):
        assert message_content({"content": "hello"}) == "hello"

    def test_dict_missing_content(self):
        assert message_content({"role": "user"}) is None

    def test_object_with_content(self):
        msg = HumanMessage(content="hi")
        assert message_content(msg) == "hi"


# ── clone_message_with_text_content ──────────────────────


class TestCloneMessage:
    def test_human_message(self):
        msg = HumanMessage(content="hello")
        cloned = clone_message_with_text_content(msg)
        assert isinstance(cloned, HumanMessage)
        assert cloned.content == "hello"

    def test_system_message(self):
        msg = SystemMessage(content="system prompt")
        cloned = clone_message_with_text_content(msg)
        assert isinstance(cloned, SystemMessage)
        assert cloned.content == "system prompt"

    def test_ai_message(self):
        msg = AIMessage(content="response")
        cloned = clone_message_with_text_content(msg)
        assert isinstance(cloned, AIMessage)
        assert cloned.content == "response"

    def test_tool_message(self):
        msg = ToolMessage(content="tool result", tool_call_id="tc1")
        cloned = clone_message_with_text_content(msg)
        assert isinstance(cloned, ToolMessage)
        assert cloned.content == "tool result"

    def test_multimodal_flattened(self):
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "part1"},
                {"type": "text", "text": "part2"},
            ]
        )
        cloned = clone_message_with_text_content(msg)
        assert isinstance(cloned.content, str)
        assert "part1" in cloned.content
        assert "part2" in cloned.content

    def test_preserves_name(self):
        msg = HumanMessage(content="hi", name="user1")
        cloned = clone_message_with_text_content(msg)
        assert cloned.name == "user1"

    def test_ai_preserves_tool_calls(self):
        msg = AIMessage(
            content="", tool_calls=[{"name": "foo", "args": {}, "id": "tc1"}]
        )
        cloned = clone_message_with_text_content(msg)
        assert len(cloned.tool_calls) == 1
