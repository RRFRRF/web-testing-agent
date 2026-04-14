"""端到端测试：CLI 和 Web 全链路，使用 FakeToolChatModel 模拟 LLM。

核心思路：
  - 用 FakeToolChatModel（支持 bind_tools）替代 ChatOpenAI
  - mock build_model() 返回 fake model
  - mock build_agent() 使用 fake model 创建 agent
  - 验证完整的 prepare_run → execute_prepared_run → manifest/report 生成
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent

from webtestagent.core.runner import prepare_run, execute_prepared_run, run_test


# ── FakeToolChatModel ──────────────────────────────────


class FakeToolChatModel(BaseChatModel):
    """支持 bind_tools 的 Fake ChatModel，直接返回预设响应。

    用法：
        model = FakeToolChatModel(responses=[
            AIMessage(content='# Test Report\\nAll checks passed.'),
        ])
        # model.bind_tools(tools) → no-op 返回 self
        # model.invoke(messages) → 按序返回 responses
    """

    responses: list = []
    _call_count: int = 0

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = min(self._call_count, len(self.responses) - 1)
        resp = self.responses[idx] if self.responses else AIMessage(content="done")
        self._call_count += 1
        return ChatResult(generations=[ChatGeneration(message=resp)])

    @property
    def _llm_type(self) -> str:
        return "fake-tool-chat"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolChatModel":
        """no-op：工具已绑定但不影响输出。"""
        return self


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def fake_model():
    """返回一个预设响应的 FakeToolChatModel。"""
    return FakeToolChatModel(
        responses=[
            AIMessage(
                content="# Test Report\n## Summary\nAll checks passed successfully.\n- Title: Example Domain\n- Status: 200"
            ),
        ]
    )


@pytest.fixture
def fake_agent(fake_model):
    """用 fake model 创建的 Deep Agent。"""
    return create_deep_agent(
        model=fake_model,
        tools=[],
        system_prompt="You are a web test agent. Execute tests and report results.",
        checkpointer=MemorySaver(),
    )


@pytest.fixture
def mock_build_agent(fake_agent):
    """mock runner 模块中的 build_agent() 返回 fake agent。"""
    with patch("webtestagent.core.runner.build_agent", return_value=fake_agent):
        with patch(
            "webtestagent.core.runner.resolve_playwright_cli",
            return_value="npx playwright-cli",
        ):
            yield fake_agent


# ── CLI E2E ────────────────────────────────────────────


class TestCLIE2E:
    """CLI 端到端测试：prepare_run → execute_prepared_run → 验证产物。"""

    def test_full_run_produces_artifacts(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        """完整 run 生成 manifest + report + 目录结构。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        prepared = prepare_run("https://example.com", "Verify the page title")
        result = execute_prepared_run(prepared)

        # 验证 RunResult
        assert result.url == "https://example.com"
        assert result.run_id.startswith("run-")
        assert result.final_report  # 非空报告

        # 验证产物文件
        assert result.manifest_path.exists()
        assert result.report_path.exists()

        # 验证 manifest 内容
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["target_url"] == "https://example.com"
        assert manifest["run_id"] == result.run_id
        assert "artifacts" in manifest

        # 验证 report 内容
        report = result.report_path.read_text(encoding="utf-8")
        assert "Test Report" in report or "passed" in report.lower() or len(report) > 0

    def test_run_with_events_callback(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        """run 通过 on_event 回调发出结构化事件。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        events: list[dict] = []

        def on_event(event: dict) -> None:
            events.append(event)

        prepared = prepare_run("https://example.com", "Check homepage")
        execute_prepared_run(prepared, on_event=on_event)

        # 应该有 start 和 complete 事件
        channels = [e.get("channel") for e in events]
        assert "system" in channels

        modes = [e.get("mode") for e in events if e.get("channel") == "system"]
        assert "start" in modes
        assert "complete" in modes

    def test_run_test_convenience(self, mock_build_agent, tmp_path: Path, monkeypatch):
        """run_test() 便捷函数正常工作。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        result = run_test("https://example.com", "Quick check")
        assert result.url == "https://example.com"
        assert result.manifest_path.exists()
        assert result.report_path.exists()

    def test_run_creates_correct_directory_structure(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        """run 创建正确的目录结构。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        result = run_test("https://example.com", "Directory check")

        # run_dir 应该在 OUTPUTS_DIR 下
        assert result.run_dir.parent == tmp_path
        assert result.run_dir.name.startswith("run-")

        # manifest 和 report 在 run_dir 内
        assert result.manifest_path.parent == result.run_dir
        assert result.report_path.parent == result.run_dir

    def test_run_with_structured_scenario(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        """结构化场景（list of dicts）正常工作。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        scenario = [
            {"type": "navigate", "text": "Go to https://example.com"},
            {"type": "assert", "text": "Title should be Example Domain"},
        ]
        result = run_test("https://example.com", scenario)
        assert result.manifest_path.exists()


# ── Web API E2E ────────────────────────────────────────


class TestWebAPIE2E:
    """Web API 端到端测试：POST /api/run → 事件流 → 产物。"""

    @pytest.fixture
    def app_with_mock(self, mock_build_agent, tmp_path, monkeypatch):
        """创建 FastAPI app，build_agent 已 mock。"""
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.web.services.run_store.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.web.routers.runs.OUTPUTS_DIR", tmp_path)
        from webtestagent.web.api import create_app
        from webtestagent.web.services.run_store import RunStore

        application = create_app()
        application.state.run_store = RunStore()
        return application

    @pytest.mark.anyio
    async def test_post_run_creates_session(self, app_with_mock, tmp_path, monkeypatch):
        """POST /api/run 创建 run session 并返回 201。"""
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "E2E test"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "run" in data
        run_data = data["run"]
        assert run_data["url"] == "https://example.com"
        assert run_data["run_id"].startswith("run-")
        assert run_data["status"] in ("queued", "running")

    @pytest.mark.anyio
    async def test_run_completes_and_appears_in_list(
        self, app_with_mock, tmp_path, monkeypatch
    ):
        """run 完成后出现在 GET /api/runs 列表中。"""
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 创建 run
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "List test"},
            )
            assert resp.status_code == 201
            run_id = resp.json()["run"]["run_id"]

            # 等待 run 完成（最多 10 秒）
            for _ in range(20):
                await asyncio_sleep(0.5)
                events_resp = await client.get(f"/api/runs/{run_id}/events")
                status = events_resp.json().get("status", "")
                if status in ("completed", "failed"):
                    break

            # 验证出现在列表中
            runs_resp = await client.get("/api/runs")
            assert runs_resp.status_code == 200
            run_ids = [r["run_id"] for r in runs_resp.json()["runs"]]
            assert run_id in run_ids

    @pytest.mark.anyio
    async def test_run_produces_manifest_and_report(
        self, app_with_mock, tmp_path, monkeypatch
    ):
        """run 完成后可以获取 manifest 和 report。"""
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "Artifact test"},
            )
            assert resp.status_code == 201
            run_id = resp.json()["run"]["run_id"]

            # 等待完成
            final_status = ""
            for _ in range(30):
                await asyncio_sleep(0.5)
                events_resp = await client.get(f"/api/runs/{run_id}/events")
                final_status = events_resp.json().get("status", "")
                if final_status in ("completed", "failed"):
                    break

            # run 应该已完成
            assert final_status == "completed", f"Run status: {final_status}"

            # 获取 manifest
            manifest_resp = await client.get(f"/api/runs/{run_id}/manifest")
            assert manifest_resp.status_code == 200
            manifest = manifest_resp.json()
            assert manifest["target_url"] == "https://example.com"

            # 获取 report
            report_resp = await client.get(f"/api/runs/{run_id}/report")
            assert report_resp.status_code == 200
            report = report_resp.text
            assert len(report) > 0


# ── 辅助 ───────────────────────────────────────────────


async def asyncio_sleep(seconds: float) -> None:
    """asyncio.sleep 的便捷包装。"""
    import asyncio

    await asyncio.sleep(seconds)
