"""测试 prompts/system.py 和 prompts/user.py。"""

from __future__ import annotations


from webtestagent.prompts.system import SYSTEM_PROMPT
from webtestagent.prompts.user import build_prompt
from webtestagent.core.session import ResolvedSessionState


# ── SYSTEM_PROMPT ────────────────────────────────────────


class TestSystemPrompt:
    def test_not_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_contains_key_concepts(self):
        assert "测试" in SYSTEM_PROMPT
        assert "capture_snapshot" in SYSTEM_PROMPT
        assert "playwright-cli" in SYSTEM_PROMPT
        assert "12306" in SYSTEM_PROMPT

    def test_stripped(self):
        assert SYSTEM_PROMPT == SYSTEM_PROMPT.strip()


# ── build_prompt ─────────────────────────────────────────


class TestBuildPrompt:
    def test_basic_string_scenario(self):
        prompt = build_prompt(
            url="https://example.com",
            scenario="测试登录功能",
            outputs_dir="/tmp/outputs",
        )
        assert "https://example.com" in prompt
        assert "测试登录功能" in prompt
        assert "/tmp/outputs" in prompt
        assert "<test-task>" in prompt

    def test_structured_steps_scenario(self):
        steps = [
            {"type": "Context", "text": "打开首页"},
            {"type": "Action", "text": "点击登录"},
            {"type": "Outcome", "text": "验证成功"},
        ]
        prompt = build_prompt(
            url="https://example.com", scenario=steps, outputs_dir="/tmp/out"
        )
        assert "[Context]" in prompt
        assert "[Action]" in prompt
        assert "[Outcome]" in prompt
        assert "1." in prompt

    def test_session_load_applied(self):
        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="example-com",
            account_id="user1",
            resolved_by="explicit",
            load_applied=True,
        )
        prompt = build_prompt(
            url="https://example.com",
            scenario="test",
            outputs_dir="/tmp",
            session_state=state,
        )
        assert "已自动导入" in prompt
        assert "example-com" in prompt

    def test_session_load_failed(self):
        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="example-com",
            resolved_by="auto-none",
            load_applied=False,
        )
        prompt = build_prompt(
            url="https://example.com",
            scenario="test",
            outputs_dir="/tmp",
            session_state=state,
        )
        assert "未成功" in prompt

    def test_session_save_enabled(self):
        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=True,
            site_id="example-com",
            resolved_by="auto-none",
        )
        prompt = build_prompt(
            url="https://example.com",
            scenario="test",
            outputs_dir="/tmp",
            session_state=state,
        )
        assert "自动保存" in prompt

    def test_no_session(self):
        prompt = build_prompt("https://example.com", "test", outputs_dir="/tmp/out")
        # Without session, the prompt should not contain session-specific instructions
        # "保存" appears in the base prompt text, but "自动保存" should not
        assert "https://example.com" in prompt
        assert "自动保存" not in prompt
