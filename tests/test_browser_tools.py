"""测试 tools/browser_tools.py：Playwright CLI 封装与 artifact 落盘。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from webtestagent.tools.browser_tools import (
    ArtifactCaptureInput,
    BrowserActionInput,
    OpenPageInput,
    _artifact_dir,
    _get_run_values,
    _manifest_path,
    _playwright_prefix,
    _register_command_result,
    _register_existing_file,
    _run_playwright,
    _runtime_context,
    build_browser_tools,
    capture_console,
    capture_network,
    capture_screenshot,
    capture_snapshot,
    open_page,
    run_browser_command,
)


# ── Pydantic 输入模型 ─────────────────────────────────────


class TestInputModels:
    def test_open_page_input(self):
        m = OpenPageInput(url="https://example.com")
        assert m.url == "https://example.com"

    def test_artifact_capture_input(self):
        m = ArtifactCaptureInput(label="home")
        assert m.label == "home"

    def test_browser_action_input(self):
        m = BrowserActionInput(command="click .btn", label="click-btn")
        assert m.command == "click .btn"
        assert m.label == "click-btn"


# ── _runtime_context ─────────────────────────────────────


class TestRuntimeContext:
    def test_none_config(self):
        assert _runtime_context(None) == {}

    def test_non_dict_config(self):
        assert _runtime_context("not-a-dict") == {}

    def test_dict_with_context(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp"}}
        assert _runtime_context(config) == {"run_id": "r1", "outputs_dir": "/tmp"}

    def test_dict_without_context(self):
        assert _runtime_context({"other": 1}) == {}

    def test_context_not_dict(self):
        config = {"context": "bad"}
        assert _runtime_context(config) == {}


# ── _get_run_values ──────────────────────────────────────


class TestGetRunValues:
    def test_from_config_context(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp/out"}}
        run_id, outputs_dir = _get_run_values(config)
        assert run_id == "r1"
        assert outputs_dir == Path("/tmp/out")

    def test_fallback_env_vars(self, monkeypatch):
        monkeypatch.setenv("RUN_ID", "env-run")
        monkeypatch.setenv("OUTPUTS_DIR", "/env/out")
        run_id, outputs_dir = _get_run_values(None)
        assert run_id == "env-run"
        assert outputs_dir == Path("/env/out")

    def test_default_adhoc(self, monkeypatch):
        monkeypatch.delenv("RUN_ID", raising=False)
        monkeypatch.delenv("OUTPUTS_DIR", raising=False)
        run_id, outputs_dir = _get_run_values(None)
        assert run_id == "adhoc-run"
        assert "adhoc-run" in str(outputs_dir)


# ── _artifact_dir / _manifest_path ───────────────────────


class TestArtifactHelpers:
    def test_artifact_dir_created(self, tmp_path):
        result = _artifact_dir(tmp_path, "screenshots")
        assert result == tmp_path / "screenshots"
        assert result.exists()

    def test_artifact_dir_nested(self, tmp_path):
        result = _artifact_dir(tmp_path, "deep/nested")
        assert result.exists()

    def test_manifest_path(self, tmp_path):
        assert _manifest_path(tmp_path) == tmp_path / "manifest.json"


# ── _playwright_prefix ───────────────────────────────────


class TestPlaywrightPrefix:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_CLI", raising=False)
        with patch("shutil.which", return_value="/usr/bin/playwright-cli"):
            result = _playwright_prefix()
        assert result == ["/usr/bin/playwright-cli"]

    def test_env_var_simple(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI", "my-pw")
        with patch("shutil.which", return_value="/usr/bin/my-pw"):
            result = _playwright_prefix()
        assert result == ["/usr/bin/my-pw"]

    def test_env_var_with_spaces(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI", "npx playwright-cli")
        result = _playwright_prefix()
        assert result == ["npx", "playwright-cli"]

    def test_env_var_empty_falls_back(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI", "  ")
        # Empty/whitespace env var is treated as unset, falls back to "playwright-cli"
        with patch("shutil.which", return_value=None) as mock_which:
            mock_which.side_effect = [None, None]
            result = _playwright_prefix()
        assert result == ["playwright-cli"]

    def test_not_found_no_cmd_extension(self, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_CLI", raising=False)
        with patch("shutil.which", return_value=None) as mock_which:
            # First call: which("playwright-cli") -> None
            # Second call: which("playwright-cli.cmd") -> None
            mock_which.side_effect = [None, None]
            result = _playwright_prefix()
        assert result == ["playwright-cli"]

    def test_cmd_extension_on_windows(self, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_CLI", raising=False)
        with patch("shutil.which", return_value=None) as mock_which:
            mock_which.side_effect = [None, "C:\\playwright-cli.cmd"]
            result = _playwright_prefix()
        assert result == ["C:\\playwright-cli.cmd"]


# ── _run_playwright ──────────────────────────────────────


class TestRunPlaywright:
    def test_calls_subprocess(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            result = _run_playwright(["echo", "hi"])
            mock_run.assert_called_once()
            assert result.returncode == 0


# ── _register_command_result / _register_existing_file ───


class TestRegisterResults:
    def test_register_command_result(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        # Ensure manifest dir exists
        tmp_path.mkdir(parents=True, exist_ok=True)
        result = _register_command_result(
            config=config,
            artifact_type="snapshot",
            label="home",
            artifact_subdir="snapshots",
            suffix=".yaml",
            content="page-snapshot-data",
        )
        assert "snapshot" in result
        assert "home" in result

    def test_register_existing_file(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello", encoding="utf-8")
        result = _register_existing_file(
            config=config,
            artifact_type="screenshot",
            label="after-click",
            file_path=file_path,
            preview="Screenshot saved",
        )
        assert "screenshot" in result
        assert "after-click" in result


# ── open_page ────────────────────────────────────────────


class TestOpenPage:
    def test_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="page opened", stderr=""
            )
            result = open_page("https://example.com", config)
            assert "open" in result

    def test_failure_raises(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp"}}
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="connection refused"
            )
            with pytest.raises(RuntimeError, match="Failed to open page"):
                open_page("https://bad.url", config)


# ── capture_snapshot ─────────────────────────────────────


class TestCaptureSnapshot:
    def test_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
            patch(
                "webtestagent.tools.browser_tools._capture_screenshot_record"
            ) as mock_ss,
        ):
            # snapshot call succeeds
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="snapshot-data", stderr=""
            )
            mock_ss.return_value = {
                "artifact_type": "screenshot",
                "label": "home-auto",
                "path": "/tmp/ss.png",
                "size_bytes": 1024,
                "preview": "ok",
            }
            result = capture_snapshot("home", config)
            parsed = json.loads(result)
            assert parsed["snapshot"]["artifact_type"] == "snapshot"
            assert parsed["screenshot"] is not None

    def test_screenshot_error_graceful(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
            patch(
                "webtestagent.tools.browser_tools._capture_screenshot_record"
            ) as mock_ss,
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="snapshot-data", stderr=""
            )
            mock_ss.side_effect = RuntimeError("screenshot failed")
            result = capture_snapshot("home", config)
            parsed = json.loads(result)
            assert parsed["screenshot"] is None
            assert parsed["screenshot_error"] is not None

    def test_failure_raises(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp"}}
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            )
            with pytest.raises(RuntimeError, match="Failed to capture snapshot"):
                capture_snapshot("home", config)


# ── capture_console / capture_network ────────────────────


class TestCaptureConsoleNetwork:
    def test_capture_console_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="log: hello", stderr=""
            )
            result = capture_console("after-click", config)
            assert "console" in result

    def test_capture_console_failure(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp"}}
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="fail"
            )
            with pytest.raises(RuntimeError, match="Failed to capture console"):
                capture_console("label", config)

    def test_capture_network_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="GET /api 200", stderr=""
            )
            result = capture_network("check-api", config)
            assert "network" in result

    def test_capture_network_failure(self):
        config = {"context": {"run_id": "r1", "outputs_dir": "/tmp"}}
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="fail"
            )
            with pytest.raises(RuntimeError, match="Failed to capture network"):
                capture_network("label", config)


# ── capture_screenshot ───────────────────────────────────


class TestCaptureScreenshot:
    def test_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        with patch(
            "webtestagent.tools.browser_tools._capture_screenshot_record"
        ) as mock_ss:
            mock_ss.return_value = {
                "artifact_type": "screenshot",
                "label": "home",
                "path": "/tmp/ss.png",
                "size_bytes": 2048,
                "preview": "ok",
            }
            result = capture_screenshot("home", config)
            parsed = json.loads(result)
            assert parsed["artifact_type"] == "screenshot"


# ── run_browser_command ──────────────────────────────────


class TestRunBrowserCommand:
    def test_success(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="done", stderr=""
            )
            result = run_browser_command("click .btn", "click-btn", config)
            assert "command" in result

    def test_nonzero_returncode_still_registered(self, tmp_path):
        config = {"context": {"run_id": "r1", "outputs_dir": str(tmp_path)}}
        tmp_path.mkdir(parents=True, exist_ok=True)
        with (
            patch("webtestagent.tools.browser_tools._run_playwright") as mock_pw,
            patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["pw"],
            ),
        ):
            mock_pw.return_value = subprocess.CompletedProcess(
                args=[], returncode=2, stdout="", stderr="not found"
            )
            result = run_browser_command("bad-cmd", "test", config)
            assert "command" in result


# ── build_browser_tools ──────────────────────────────────


class TestBuildBrowserTools:
    def test_returns_tools(self):
        tools = build_browser_tools()
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "capture_snapshot" in names
        assert "capture_screenshot" in names

    def test_tools_are_structured(self):
        tools = build_browser_tools()
        for t in tools:
            assert callable(t.func)
            assert t.args_schema is not None

    def test_only_agent_facing_tools_exposed(self):
        """确认设计意图：只暴露 agent 直接调用的 2 个工具。
        open_page/capture_console/capture_network/run_browser_command
        是内部辅助函数，由 capture_snapshot 间接调用，不直接暴露给 agent。
        """
        tools = build_browser_tools()
        exposed = {t.name for t in tools}
        assert exposed == {"capture_snapshot", "capture_screenshot"}
