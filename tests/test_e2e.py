"""端到端测试：runner 与单 run Web API 的最小链路回归。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from webtestagent.core.runner import execute_prepared_run, prepare_run, run_test
from webtestagent.web.state import CurrentRunState


class FakeAgent:
    """最小 fake agent，模拟 stream/get_state 接口。"""

    def __init__(self, final_text: str):
        self._final_text = final_text

    def stream(self, *_args, **_kwargs):
        yield ("updates", {"agent": {"messages": [AIMessage(content="step1")]}})

    def get_state(self, _config):
        return SimpleNamespace(values={"messages": [AIMessage(content=self._final_text)]})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_agent():
    return FakeAgent("# Test Report\nAll checks passed successfully.")


@pytest.fixture
def mock_build_agent(fake_agent):
    with patch("webtestagent.core.runner.build_agent", return_value=fake_agent):
        with patch(
            "webtestagent.core.runner.resolve_playwright_cli",
            return_value="npx playwright-cli",
        ):
            yield fake_agent


class TestCLIE2E:
    def test_full_run_produces_artifacts(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        prepared = prepare_run("https://example.com", "Verify the page title")
        result = execute_prepared_run(prepared)

        assert result.url == "https://example.com"
        assert result.run_id.startswith("run-")
        assert result.final_report
        assert result.manifest_path.exists()
        assert result.report_path.exists()

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["target_url"] == "https://example.com"
        assert manifest["run_id"] == result.run_id
        assert "artifacts" in manifest

        report = result.report_path.read_text(encoding="utf-8")
        assert "Test Report" in report or "passed" in report.lower()

    def test_run_with_events_callback(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        events: list[dict] = []

        def on_event(event: dict) -> None:
            events.append(event)

        prepared = prepare_run("https://example.com", "Check homepage")
        execute_prepared_run(prepared, on_event=on_event)

        channels = [e.get("channel") for e in events]
        assert "system" in channels

        modes = [e.get("mode") for e in events if e.get("channel") == "system"]
        assert "start" in modes
        assert "complete" in modes

    def test_run_test_convenience(self, mock_build_agent, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        result = run_test("https://example.com", "Quick check")
        assert result.url == "https://example.com"
        assert result.manifest_path.exists()
        assert result.report_path.exists()

    def test_run_creates_correct_directory_structure(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        result = run_test("https://example.com", "Directory check")

        assert result.run_dir.parent == tmp_path
        assert result.run_dir.name.startswith("run-")
        assert result.manifest_path.parent == result.run_dir
        assert result.report_path.parent == result.run_dir

    def test_run_with_structured_scenario(
        self, mock_build_agent, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)

        scenario = [
            {"type": "navigate", "text": "Go to https://example.com"},
            {"type": "assert", "text": "Title should be Example Domain"},
        ]
        result = run_test("https://example.com", scenario)
        assert result.manifest_path.exists()


class TestWebAPIE2E:
    @pytest.fixture
    def app_with_mock(self, mock_build_agent, tmp_path, monkeypatch):
        monkeypatch.setattr("webtestagent.config.settings.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr("webtestagent.web.api.OUTPUTS_DIR", tmp_path)
        from webtestagent.web.api import create_app

        application = create_app()
        application.state.current_run = CurrentRunState()
        return application

    @pytest.mark.anyio
    async def test_post_run_creates_current_run(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "E2E test"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["status"] in ("preparing", "running")

    @pytest.mark.anyio
    async def test_run_completes_and_appears_in_state(self, app_with_mock):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "State test"},
            )
            assert resp.status_code == 201

            final_status = ""
            for _ in range(30):
                await asyncio_sleep(0.2)
                state_resp = await client.get("/api/state")
                final_status = state_resp.json().get("status", "")
                if final_status in ("completed", "failed"):
                    break

        assert final_status == "completed"

    @pytest.mark.anyio
    async def test_run_produces_manifest_and_report_files(
        self, app_with_mock, tmp_path
    ):
        transport = ASGITransport(app=app_with_mock)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "Artifact test"},
            )
            assert resp.status_code == 201

            state = {}
            for _ in range(30):
                await asyncio_sleep(0.2)
                state_resp = await client.get("/api/state")
                state = state_resp.json()
                if state.get("status") in ("completed", "failed"):
                    break

        assert state.get("status") == "completed"
        manifest_path = Path(state["manifest_path"])
        report_path = manifest_path.parent / "report.md"
        assert manifest_path.exists()
        assert report_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["target_url"] == "https://example.com"
        report = report_path.read_text(encoding="utf-8")
        assert len(report) > 0


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
