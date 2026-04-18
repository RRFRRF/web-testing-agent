"""测试 core/agent_builder.py：模型构建、playwright-cli 检测。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from webtestagent.core.agent_builder import resolve_playwright_cli


# ── resolve_playwright_cli ──────────────────────────────


class TestResolvePlaywrightCli:
    """测试 playwright-cli 路径检测逻辑。"""

    def test_found_playwright_cli(self):
        """playwright-cli 在 PATH 中直接返回。"""
        with patch("webtestagent.core.agent_builder.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                "/usr/bin/playwright-cli" if name == "playwright-cli" else None
            )
            result = resolve_playwright_cli()
        assert result == "playwright-cli"

    def test_fallback_to_npx(self):
        """playwright-cli 不在 PATH，但 npx 在。"""
        with patch("webtestagent.core.agent_builder.shutil.which") as mock_which:
            mock_which.side_effect = lambda name: (
                None if name == "playwright-cli" else "/usr/bin/npx"
            )
            result = resolve_playwright_cli()
        assert result == "npx playwright-cli"

    def test_not_found_raises(self):
        """两者都不在 PATH 时抛出 RuntimeError。"""
        with patch("webtestagent.core.agent_builder.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="playwright-cli is not available"):
                resolve_playwright_cli()


# ── build_model ─────────────────────────────────────────


class TestBuildModel:
    """测试 build_model 构建逻辑。"""

    def test_build_model_calls_require_env(self):
        """build_model 调用 require_env 获取配置。"""
        from webtestagent.core.agent_builder import build_model

        with (
            patch(
                "webtestagent.core.agent_builder.require_env",
                side_effect=lambda key: {
                    "OPENAI_MODEL": "gpt-4",
                    "OPENAI_API_KEY": "sk-test",
                    "OPENAI_BASE_URL": "https://api.openai.com/v1",
                }[key],
            ),
            patch("webtestagent.core.agent_builder.ChatOpenAI") as mock_chat,
        ):
            build_model()
            mock_chat.assert_called_once_with(
                model="gpt-4",
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
                temperature=0,
            )


# ── build_agent ─────────────────────────────────────────


class TestBuildAgent:
    """测试 build_agent 组装逻辑。"""

    def test_build_agent_assembles_correctly(self):
        """build_agent 正确组装各组件。"""
        from webtestagent.core.agent_builder import build_agent

        mock_model = MagicMock()
        mock_tools = [MagicMock()]
        mock_agent = MagicMock()
        base_backend = MagicMock()

        with (
            patch(
                "webtestagent.core.agent_builder.build_model", return_value=mock_model
            ),
            patch(
                "webtestagent.core.agent_builder.resolve_playwright_cli",
                return_value="playwright-cli",
            ),
            patch(
                "webtestagent.core.agent_builder.build_browser_tools",
                return_value=mock_tools,
            ),
            patch(
                "webtestagent.core.agent_builder.create_deep_agent",
                return_value=mock_agent,
            ) as mock_create,
            patch(
                "webtestagent.core.agent_builder.LocalShellBackend",
                return_value=base_backend,
            ),
            patch(
                "webtestagent.core.agent_builder.TracingShellBackend",
                return_value="wrapped-backend",
            ),
            patch("webtestagent.core.agent_builder.MemorySaver"),
            patch("webtestagent.core.agent_builder.PlaywrightTraceRecorder") as mock_recorder,
        ):
            result = build_agent()
            assert result is mock_agent
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["model"] is mock_model
            assert call_kwargs.kwargs["tools"] == mock_tools

            backend_factory = call_kwargs.kwargs["backend"]
            runtime = SimpleNamespace(
                context={
                    "run_id": "r1",
                    "outputs_dir": "/tmp/out",
                    "manifest_path": "/tmp/out/manifest.json",
                }
            )
            assert backend_factory(runtime) == "wrapped-backend"
            mock_recorder.assert_called_once()

    def test_build_agent_returns_base_backend_without_run_context(self):
        from webtestagent.core.agent_builder import build_agent

        base_backend = MagicMock()

        with (
            patch("webtestagent.core.agent_builder.build_model", return_value=MagicMock()),
            patch(
                "webtestagent.core.agent_builder.resolve_playwright_cli",
                return_value="playwright-cli",
            ),
            patch(
                "webtestagent.core.agent_builder.build_browser_tools",
                return_value=[MagicMock()],
            ),
            patch(
                "webtestagent.core.agent_builder.create_deep_agent",
                return_value=MagicMock(),
            ) as mock_create,
            patch(
                "webtestagent.core.agent_builder.LocalShellBackend",
                return_value=base_backend,
            ),
            patch("webtestagent.core.agent_builder.TracingShellBackend") as mock_tracing,
            patch("webtestagent.core.agent_builder.PlaywrightTraceRecorder") as mock_recorder,
            patch("webtestagent.core.agent_builder.MemorySaver"),
        ):
            build_agent()
            backend_factory = mock_create.call_args.kwargs["backend"]
            runtime = SimpleNamespace(context=None)
            assert backend_factory(runtime) is base_backend
            mock_tracing.assert_not_called()
            mock_recorder.assert_not_called()
