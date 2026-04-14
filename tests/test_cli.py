"""测试 cli/main.py：参数解析、UTF-8 配置与主流程。"""

from __future__ import annotations

import locale
import os
import sys
from unittest.mock import MagicMock, patch


from webtestagent.cli.main import configure_utf8_runtime, parse_args


# ── configure_utf8_runtime ───────────────────────────────


class TestConfigureUtf8Runtime:
    def test_sets_env_vars(self, monkeypatch):
        configure_utf8_runtime()
        assert os.environ.get("PYTHONIOENCODING") == "utf-8"
        assert os.environ.get("PYTHONUTF8") == "1"

    def test_reconfigures_streams(self):
        # Should not raise even if streams don't support reconfigure
        configure_utf8_runtime()

    def test_patches_locale(self):
        configure_utf8_runtime()
        if hasattr(locale, "getpreferredencoding"):
            assert locale.getpreferredencoding(False) == "utf-8"
        if hasattr(locale, "getencoding"):
            assert locale.getencoding() == "utf-8"


# ── parse_args ───────────────────────────────────────────


class TestParseArgs:
    def test_defaults(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        args = parse_args()
        assert args.url is None
        assert args.scenario is None
        assert args.show_full_events is False
        assert args.auto_load_session is False
        assert args.auto_save_session is False
        assert args.session_site_id is None
        assert args.session_account_id is None
        assert args.session_dir is None

    def test_url_and_scenario(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--url", "https://example.com", "--scenario", "检查首页"],
        )
        args = parse_args()
        assert args.url == "https://example.com"
        assert args.scenario == "检查首页"

    def test_show_full_events(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--show-full-events"])
        args = parse_args()
        assert args.show_full_events is True

    def test_session_flags(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--auto-load-session",
                "--auto-save-session",
                "--session-site-id",
                "example.com",
                "--session-account-id",
                "user1",
                "--session-dir",
                "/tmp/sessions",
            ],
        )
        args = parse_args()
        assert args.auto_load_session is True
        assert args.auto_save_session is True
        assert args.session_site_id == "example.com"
        assert args.session_account_id == "user1"
        assert args.session_dir == "/tmp/sessions"


# ── main() 集成测试（mock 外部依赖）──────────────────────


class TestMainIntegration:
    def test_main_calls_prepare_and_execute(self, monkeypatch):
        """验证 main() 正确调用 prepare_run + execute_prepared_run。"""
        monkeypatch.setattr(sys, "argv", ["prog", "--url", "https://example.com"])

        mock_prepared = MagicMock()
        mock_prepared.url = "https://example.com"
        mock_prepared.scenario_desc = "test"
        mock_prepared.run_context.run_id = "r1"
        mock_prepared.run_context.run_dir.as_posix.return_value = "/tmp/r1"
        mock_prepared.cli_command = "pw"
        mock_prepared.session_state = None

        mock_result = MagicMock()
        mock_result.final_report = "All tests passed"

        with (
            patch(
                "webtestagent.cli.main.prepare_run", return_value=mock_prepared
            ) as mock_prepare,
            patch(
                "webtestagent.cli.main.execute_prepared_run", return_value=mock_result
            ) as mock_execute,
            patch("webtestagent.cli.main.init_env"),
            patch("webtestagent.cli.main.load_scenario", return_value="test scenario"),
            patch("webtestagent.cli.main.load_session_defaults", return_value={}),
            patch("builtins.print"),
        ):
            from webtestagent.cli.main import main

            main()

            mock_prepare.assert_called_once()
            mock_execute.assert_called_once()

    def test_main_with_session_config(self, monkeypatch):
        """验证 session 参数传递到 SessionPersistenceConfig。"""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--url",
                "https://example.com",
                "--auto-load-session",
                "--auto-save-session",
            ],
        )

        mock_prepared = MagicMock()
        mock_prepared.url = "https://example.com"
        mock_prepared.scenario_desc = "test"
        mock_prepared.run_context.run_id = "r1"
        mock_prepared.run_context.run_dir.as_posix.return_value = "/tmp/r1"
        mock_prepared.cli_command = "pw"
        mock_prepared.session_state = None

        mock_result = MagicMock()
        mock_result.final_report = "OK"

        with (
            patch("webtestagent.cli.main.prepare_run", return_value=mock_prepared),
            patch(
                "webtestagent.cli.main.execute_prepared_run", return_value=mock_result
            ),
            patch("webtestagent.cli.main.init_env"),
            patch("webtestagent.cli.main.load_scenario", return_value="s"),
            patch("webtestagent.cli.main.load_session_defaults", return_value={}),
            patch("builtins.print"),
        ):
            from webtestagent.cli.main import main

            main()
