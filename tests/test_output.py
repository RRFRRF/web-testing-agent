"""测试 output/formatters.py 和 output/stream.py。"""

from __future__ import annotations


from langchain_core.messages import AIMessage, HumanMessage

from webtestagent.output.formatters import (
    extract_text,
    format_event_for_cli,
    format_inline_text,
    make_json_safe,
    summarize_message,
)
from webtestagent.output.stream import events_from_stream_chunk, final_result_from_state


# ── format_inline_text ───────────────────────────────────


class TestFormatInlineText:
    def test_short_text(self):
        assert format_inline_text("hello") == "hello"

    def test_multiline_collapsed(self):
        assert format_inline_text("line1\nline2") == "line1 line2"

    def test_truncation(self):
        long = "a" * 200
        result = format_inline_text(long, limit=100)
        assert result.endswith("...")
        assert len(result) < 200

    def test_custom_limit(self):
        assert format_inline_text("a" * 50, limit=30).endswith("...")


# ── make_json_safe ───────────────────────────────────────


class TestMakeJsonSafe:
    def test_primitives(self):
        assert make_json_safe(None) is None
        assert make_json_safe(42) == 42
        assert make_json_safe("hello") == "hello"
        assert make_json_safe(True) is True

    def test_list(self):
        assert make_json_safe([1, "a", None]) == [1, "a", None]

    def test_tuple_to_list(self):
        assert make_json_safe((1, 2)) == [1, 2]

    def test_dict(self):
        assert make_json_safe({"a": 1}) == {"a": 1}

    def test_nested(self):
        result = make_json_safe({"x": [1, {"y": 2}]})
        assert result == {"x": [1, {"y": 2}]}

    def test_object_with_model_dump(self):
        msg = HumanMessage(content="hi")
        result = make_json_safe(msg)
        assert isinstance(result, dict)

    def test_fallback_to_str(self):
        class Weird:
            pass

        result = make_json_safe(Weird())
        assert isinstance(result, str)


# ── extract_text ─────────────────────────────────────────


class TestExtractText:
    def test_string(self):
        assert extract_text("hello") == "hello"

    def test_dict_with_messages(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="response text")]
        result = extract_text({"messages": msgs})
        assert result == "response text"

    def test_dict_no_messages(self):
        result = extract_text({"key": "value"})
        assert "key" in result

    def test_object_with_content(self):
        result = extract_text(AIMessage(content="from ai"))
        assert result == "from ai"


# ── summarize_message ────────────────────────────────────


class TestSummarizeMessage:
    def test_text_message(self):
        result = summarize_message(HumanMessage(content="hello world"))
        assert "hello" in result

    def test_tool_calls_message(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "capture_snapshot", "args": {}, "id": "tc1"}],
        )
        result = summarize_message(msg)
        assert "capture_snapshot" in result

    def test_empty_message(self):
        msg = AIMessage(content="")
        result = summarize_message(msg)
        assert isinstance(result, str)


# ── format_event_for_cli ─────────────────────────────────


class TestFormatEventForCli:
    def test_model_channel(self):
        event = {"channel": "model", "summary": "thinking..."}
        assert format_event_for_cli(event) == "[model] thinking..."

    def test_node_channel(self):
        event = {"channel": "node", "node": "agent", "summary": "step done"}
        result = format_event_for_cli(event)
        assert "[node]" in result
        assert "agent" in result

    def test_other_channel(self):
        event = {"channel": "system", "summary": "started"}
        assert format_event_for_cli(event) == "[system] started"


# ── events_from_stream_chunk ─────────────────────────────


class TestEventsFromStreamChunk:
    def test_messages_mode(self):
        chunk = ("messages", [HumanMessage(content="test")])
        events = events_from_stream_chunk(chunk)
        assert len(events) >= 1
        assert events[0]["channel"] == "model"

    def test_updates_mode(self):
        chunk = ("updates", {"agent": {"messages": [AIMessage(content="ok")]}})
        events = events_from_stream_chunk(chunk)
        assert len(events) >= 1
        assert events[0]["channel"] == "node"

    def test_updates_with_none_payload(self):
        chunk = ("updates", {"agent": None})
        events = events_from_stream_chunk(chunk)
        assert len(events) == 0

    def test_unknown_tuple_mode(self):
        chunk = ("custom", {"data": 123})
        events = events_from_stream_chunk(chunk)
        assert len(events) >= 1

    def test_non_tuple_chunk(self):
        events = events_from_stream_chunk({"raw": "data"})
        assert len(events) >= 1

    def test_show_full_events(self):
        chunk = ("updates", {"node1": {"key": "val"}})
        events = events_from_stream_chunk(chunk, show_full_events=True)
        assert len(events) >= 1


# ── final_result_from_state ──────────────────────────────


class TestFinalResultFromState:
    def test_dict_values(self):
        class FakeSnapshot:
            values = {"messages": ["result"]}

        class FakeAgent:
            def get_state(self, config):
                return FakeSnapshot()

        agent = FakeAgent()
        result = final_result_from_state(agent, {})
        assert result == {"messages": ["result"]}

    def test_none_values(self):
        class FakeSnapshot:
            values = None

        class FakeAgent:
            def get_state(self, config):
                return FakeSnapshot()

        result = final_result_from_state(FakeAgent(), {})
        assert result == {}

    def test_non_dict_values(self):
        class FakeSnapshot:
            values = ["msg1", "msg2"]

        class FakeAgent:
            def get_state(self, config):
                return FakeSnapshot()

        result = final_result_from_state(FakeAgent(), {})
        assert "messages" in result
