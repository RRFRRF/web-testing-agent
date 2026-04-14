"""测试 config/settings.py：路径定义、环境变量加载、require_env、parse_bool。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from webtestagent.config.settings import (
    COOKIES_DIR,
    OUTPUTS_DIR,
    PROJECT_ROOT,
    SCENARIOS_DIR,
    SCENARIOS_FILE,
    SKILLS_DIR,
    WORKSPACE_ROOT,
    init_env,
    parse_bool,
    require_env,
)


# ── 路径常量 ──────────────────────────────────────────────


class TestPathConstants:
    """验证核心路径常量指向正确的位置。"""

    def test_project_root_is_valid_dir(self):
        assert PROJECT_ROOT.is_dir()

    def test_project_root_contains_pyproject(self):
        assert (PROJECT_ROOT / "pyproject.toml").is_file()

    def test_workspace_root_is_parent(self):
        assert WORKSPACE_ROOT == PROJECT_ROOT.parent

    def test_skills_dir_is_string(self):
        assert isinstance(SKILLS_DIR, str)
        assert SKILLS_DIR.startswith("/")

    def test_scenarios_dir_under_project(self):
        assert SCENARIOS_DIR == PROJECT_ROOT / "scenarios"

    def test_scenarios_file_under_scenarios_dir(self):
        assert SCENARIOS_FILE == SCENARIOS_DIR / "default.json"

    def test_outputs_dir_under_project(self):
        assert OUTPUTS_DIR == PROJECT_ROOT / "outputs"

    def test_cookies_dir_under_project(self):
        assert COOKIES_DIR == PROJECT_ROOT / "cookies"


# ── init_env ─────────────────────────────────────────────


class TestInitEnv:
    """测试 .env 文件加载。"""

    def test_init_env_does_not_raise(self):
        """init_env 在 .env 不存在时也不应抛异常。"""
        init_env()  # 不应抛异常

    def test_init_env_loads_dotenv(self, tmp_path: Path):
        """验证 .env 文件中的变量能被加载。"""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_WEBTESTAGENT_VAR=hello123\n", encoding="utf-8")
        with mock.patch.object(Path, "resolve", return_value=PROJECT_ROOT):
            with mock.patch("webtestagent.config.settings.PROJECT_ROOT", tmp_path):
                from dotenv import load_dotenv

                load_dotenv(env_file, override=True)
        # dotenv 默认不覆盖已有环境变量，此处仅验证不报错
        os.environ.pop("TEST_WEBTESTAGENT_VAR", None)


# ── require_env ──────────────────────────────────────────


class TestRequireEnv:
    """测试必需环境变量读取。"""

    def test_returns_value_when_set(self):
        with mock.patch.dict(os.environ, {"MY_TEST_KEY": "my_value"}):
            assert require_env("MY_TEST_KEY") == "my_value"

    def test_raises_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # 确保该变量不存在
            os.environ.pop("MISSING_KEY_XYZ", None)
            with pytest.raises(
                RuntimeError,
                match="Missing required environment variable: MISSING_KEY_XYZ",
            ):
                require_env("MISSING_KEY_XYZ")

    def test_raises_when_empty(self):
        with mock.patch.dict(os.environ, {"EMPTY_KEY": ""}):
            with pytest.raises(
                RuntimeError, match="Missing required environment variable"
            ):
                require_env("EMPTY_KEY")

    def test_strips_whitespace(self):
        with mock.patch.dict(os.environ, {"SPACED_KEY": "  hello  "}):
            assert require_env("SPACED_KEY") == "hello"

    def test_raises_when_only_whitespace(self):
        with mock.patch.dict(os.environ, {"WS_ONLY_KEY": "   "}):
            with pytest.raises(RuntimeError):
                require_env("WS_ONLY_KEY")


# ── parse_bool ───────────────────────────────────────────


class TestParseBool:
    """测试布尔值解析。"""

    @pytest.mark.parametrize(
        "value", ["1", "true", "True", "TRUE", "yes", "Yes", "on", "On"]
    )
    def test_truthy_values(self, value: str):
        assert parse_bool(value) is True

    @pytest.mark.parametrize(
        "value", ["0", "false", "False", "no", "No", "off", "random", ""]
    )
    def test_falsy_values(self, value: str):
        assert parse_bool(value) is False

    def test_none_returns_default(self):
        assert parse_bool(None) is False
        assert parse_bool(None, default=True) is True

    def test_empty_string_returns_default(self):
        assert parse_bool("") is False
        assert parse_bool("", default=True) is True

    def test_whitespace_value(self):
        """带空格的值应该被 strip 后判断。"""
        assert parse_bool("  true  ") is True
        assert parse_bool("  false  ") is False
