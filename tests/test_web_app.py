from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from webtestagent.web.api import create_app
from webtestagent.web.state import append_event


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_get_state_returns_idle_by_default(client):
    response = client.get("/api/state")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
    assert data["run_id"] is None
    assert data["logs"] == []
    assert data["final_report"] is None
    assert data["url"] == "https://www.12306.cn/index/"
    assert "测试从天津到上海的购票查询流程" in data["scenario_input"]


def test_index_page_uses_single_run_workbench_contract(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "单次运行工作台" in html
    assert "最终报告" in html
    assert "/api/state" in html
    assert "/api/run" in html
    assert "/api/reset" in html
    assert "/api/defaults" not in html
    assert "/api/runs/" not in html
    assert "/api/run/" not in html
    assert "/api/ws/" not in html


def test_index_page_disables_form_during_run_and_keeps_reset_available(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "fieldset" in html
    assert "formFields.disabled = isRunning" in html
    assert "resetBtn.disabled = false" in html
    assert "正在运行，不能重置当前状态" in html


def test_index_page_has_clear_empty_states_for_screenshot_logs_and_report(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "尚未开始运行" in html
    assert "运行后会在这里显示最新截图" in html
    assert "当前还没有日志输出" in html
    assert "最终报告会在运行结束后显示在这里" in html


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_reset_allows_terminal_states(client, status):
    app_state = getattr(client.app.state, "current_run", None)
    assert app_state is not None

    app_state.status = status
    app_state.run_id = "run-1"
    app_state.error = "boom" if status == "failed" else None
    app_state.final_report = "report" if status == "completed" else None

    response = client.post("/api/reset")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
    assert data["run_id"] is None
    assert data["error"] is None
    assert data["final_report"] is None
    assert data["url"] == "https://www.12306.cn/index/"
    assert "测试从天津到上海的购票查询流程" in data["scenario_input"]


def test_reset_rejects_while_running(client):
    app_state = getattr(client.app.state, "current_run", None)
    assert app_state is not None
    app_state.status = "running"

    response = client.post("/api/reset")

    assert response.status_code == 409
    assert "running" in response.json()["detail"].lower()


def test_post_run_starts_single_run(client):
    def fake_start_run(state, *, url, scenario_input, session_payload):
        state.status = "running"
        state.run_id = "run-1"
        state.run_dir = "/tmp/run-1"
        state.manifest_path = "/tmp/run-1/manifest.json"
        state.url = url
        state.scenario_input = scenario_input
        return SimpleNamespace(
            run_context=SimpleNamespace(
                run_id="run-1",
                run_dir=Path("/tmp/run-1"),
                manifest_path=Path("/tmp/run-1/manifest.json"),
            ),
            url=url,
        )

    mock_thread = MagicMock()
    mock_thread.start = MagicMock()

    with (
        patch(
            "webtestagent.web.api.start_run",
            side_effect=fake_start_run,
            create=True,
        ) as mock_start,
        patch(
            "webtestagent.web.api.threading.Thread",
            return_value=mock_thread,
            create=True,
        ) as mock_thread_cls,
    ):
        response = client.post(
            "/api/run",
            json={"url": "https://example.com", "scenario": "test scenario"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "running"
    assert data["run_id"] == "run-1"
    mock_start.assert_called_once()
    mock_thread_cls.assert_called_once()
    mock_thread.start.assert_called_once()


def test_post_run_rejects_while_running(client):
    app_state = getattr(client.app.state, "current_run", None)
    assert app_state is not None
    app_state.status = "running"

    response = client.post(
        "/api/run",
        json={"url": "https://example.com", "scenario": "test scenario"},
    )

    assert response.status_code == 409
    assert "already running" in response.json()["detail"].lower()


def test_post_run_reserves_single_run_atomically(client):
    app_state = getattr(client.app.state, "current_run", None)
    assert app_state is not None

    def fake_start_run(state, *, url, scenario_input, session_payload):
        assert state.status == "preparing"
        return SimpleNamespace(
            run_context=SimpleNamespace(
                run_id="run-1",
                run_dir=Path("/tmp/run-1"),
                manifest_path=Path("/tmp/run-1/manifest.json"),
            ),
            url=url,
        )

    with (
        patch("webtestagent.web.api.start_run", side_effect=fake_start_run),
        patch("webtestagent.web.api.threading.Thread") as mock_thread_cls,
    ):
        mock_thread = MagicMock()
        mock_thread.start = MagicMock()
        mock_thread_cls.return_value = mock_thread
        response = client.post(
            "/api/run",
            json={"url": "https://example.com", "scenario": "test scenario"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "preparing"


def test_post_run_releases_reservation_when_start_fails(client):
    with patch(
        "webtestagent.web.api.start_run",
        side_effect=RuntimeError("prepare failed"),
        create=True,
    ):
        response = client.post(
            "/api/run",
            json={"url": "https://example.com", "scenario": "test scenario"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "prepare failed"

    state = client.app.state.current_run
    assert state.status == "idle"
    assert state.run_id is None


def test_outputs_route_is_available_before_first_run(client):
    response = client.get("/outputs/does-not-exist.png")

    assert response.status_code == 404


def test_outputs_route_serves_files_created_after_app_start(client, tmp_path, monkeypatch):
    asset = tmp_path / "run-1" / "screenshots" / "latest.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"png-data")

    with patch("webtestagent.web.api.OUTPUTS_DIR", tmp_path):
        app = create_app()

    with TestClient(app) as serving_client:
        response = serving_client.get("/outputs/run-1/screenshots/latest.png")

    assert response.status_code == 200
    assert response.content == b"png-data"


def test_append_event_keeps_trace_event_payload_and_uses_trace_screenshot(client, tmp_path):
    screenshot_path = "/outputs/run-1/screenshots/trace-step-1.png"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        f'{{"artifacts": [{{"type": "trace-screenshot", "path": "{screenshot_path}"}}]}}',
        encoding="utf-8",
    )
    state = client.app.state.current_run
    state.manifest_path = manifest_path.as_posix()
    event = {
        "type": "trace",
        "mode": "auto",
        "payload": {
            "command": "playwright-cli click e15",
            "artifact": {
                "type": "trace-screenshot",
                "path": screenshot_path,
            },
        },
    }

    append_event(state, event)

    response = client.get("/api/state")

    assert response.status_code == 200
    assert response.json()["latest_screenshot"] == screenshot_path
    assert response.json()["logs"] == [event]
