"""测试 config/scenarios.py：场景加载、步骤解析、session 默认值。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

from webtestagent.config.scenarios import (
    _parse_steps,
    build_default_steps,
    get_default_url,
    load_scenario,
    load_scenario_file,
    load_session_defaults,
)


# ── get_default_url ──────────────────────────────────────


class TestGetDefaultUrl:
    """测试默认 URL 获取。"""

    def test_returns_url_from_scenarios_file(self):
        """当 scenarios/default.json 存在时，返回其中的 default_url。"""
        url = get_default_url()
        assert isinstance(url, str)
        assert url.startswith("http")

    def test_fallback_when_file_missing(self):
        """当配置文件不存在时，返回 fallback URL。"""
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file", return_value={}
        ):
            assert get_default_url() == "https://www.12306.cn/index/"

    def test_uses_default_url_key(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={"default_url": "https://example.com"},
        ):
            assert get_default_url() == "https://example.com"


# ── build_default_steps ─────────────────────────────────


class TestBuildDefaultSteps:
    """测试默认步骤构建。"""

    def test_returns_list_of_dicts(self):
        steps = build_default_steps()
        assert isinstance(steps, list)
        assert len(steps) > 0
        for step in steps:
            assert "type" in step
            assert "text" in step

    def test_steps_have_valid_types(self):
        valid_types = {"Context", "Action", "Outcome"}
        steps = build_default_steps()
        for step in steps:
            assert step["type"] in valid_types

    def test_today_placeholder_replaced(self):
        """验证 {today} 占位符被替换为实际日期。"""
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={
                "steps": [
                    {"type": "Action", "text": "日期 {today}"},
                ]
            },
        ):
            steps = build_default_steps()
            assert date.today().isoformat() in steps[0]["text"]
            assert "{today}" not in steps[0]["text"]

    def test_fallback_when_no_steps_in_file(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file", return_value={}
        ):
            steps = build_default_steps()
            assert len(steps) >= 5  # fallback 有至少 5 步


# ── _parse_steps ────────────────────────────────────────


class TestParseSteps:
    """测试 JSON 步骤解析。"""

    def test_valid_steps(self):
        raw = json.dumps(
            [
                {"type": "Context", "text": "打开页面"},
                {"type": "Action", "text": "点击按钮"},
            ]
        )
        steps = _parse_steps(raw)
        assert len(steps) == 2
        assert steps[0] == {"type": "Context", "text": "打开页面"}

    def test_invalid_json_raises(self):
        with pytest.raises(RuntimeError, match="Invalid JSON"):
            _parse_steps("not json{{{")

    def test_empty_array_raises(self):
        with pytest.raises(RuntimeError, match="non-empty"):
            _parse_steps("[]")

    def test_non_array_raises(self):
        with pytest.raises(RuntimeError, match="non-empty"):
            _parse_steps('"hello"')

    def test_non_object_item_raises(self):
        with pytest.raises(RuntimeError, match="must be an object"):
            _parse_steps('["string_item"]')

    def test_missing_type_raises(self):
        with pytest.raises(RuntimeError, match="non-empty 'type'"):
            _parse_steps('[{"text": "hello"}]')

    def test_missing_text_raises(self):
        with pytest.raises(RuntimeError, match="non-empty 'type' and 'text'"):
            _parse_steps('[{"type": "Action"}]')

    def test_whitespace_stripped(self):
        raw = json.dumps([{"type": "  Action  ", "text": "  点击  "}])
        steps = _parse_steps(raw)
        assert steps[0]["type"] == "Action"
        assert steps[0]["text"] == "点击"


# ── load_scenario_file ──────────────────────────────────


class TestLoadScenarioFile:
    def test_loads_steps_and_url(self, tmp_path: Path):
        scenario_file = tmp_path / "steps.json"
        scenario_file.write_text(
            json.dumps(
                {
                    "url": "https://onebase.example",
                    "steps": [
                        {"type": "Action", "text": "填写日期 {today}"},
                        {"type": "Outcome", "text": "看到结果"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        url, scenario = load_scenario_file(scenario_file)
        assert url == "https://onebase.example"
        assert isinstance(scenario, list)
        assert date.today().isoformat() in scenario[0]["text"]

    def test_loads_plain_scenario(self, tmp_path: Path):
        scenario_file = tmp_path / "scenario.json"
        scenario_file.write_text(
            json.dumps(
                {
                    "default_url": "https://onebase.example/home",
                    "scenario": "验证 {today} 的搜索流程",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        url, scenario = load_scenario_file(scenario_file)
        assert url == "https://onebase.example/home"
        assert isinstance(scenario, str)
        assert date.today().isoformat() in scenario

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="Scenario file not found"):
            load_scenario_file(tmp_path / "missing.json")

    def test_invalid_json_raises(self, tmp_path: Path):
        scenario_file = tmp_path / "bad.json"
        scenario_file.write_text("not-json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Invalid JSON in scenario file"):
            load_scenario_file(scenario_file)

    def test_top_level_must_be_object(self, tmp_path: Path):
        scenario_file = tmp_path / "bad.json"
        scenario_file.write_text("[]", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Scenario file must be a JSON object"):
            load_scenario_file(scenario_file)

    def test_requires_scenario_or_steps(self, tmp_path: Path):
        scenario_file = tmp_path / "bad.json"
        scenario_file.write_text("{}", encoding="utf-8")
        with pytest.raises(
            RuntimeError,
            match="Scenario file must contain non-empty 'scenario' or 'steps'",
        ):
            load_scenario_file(scenario_file)

    def test_steps_cannot_be_empty(self, tmp_path: Path):
        scenario_file = tmp_path / "bad.json"
        scenario_file.write_text(
            json.dumps({"steps": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="non-empty JSON array"):
            load_scenario_file(scenario_file)

    def test_step_requires_type_and_text(self, tmp_path: Path):
        scenario_file = tmp_path / "bad.json"
        scenario_file.write_text(
            json.dumps({"steps": [{"type": "Action"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="non-empty 'type' and 'text'"):
            load_scenario_file(scenario_file)

    def test_blank_url_returns_none(self, tmp_path: Path):
        scenario_file = tmp_path / "blank-url.json"
        scenario_file.write_text(
            json.dumps(
                {
                    "url": "   ",
                    "scenario": "检查首页",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        url, scenario = load_scenario_file(scenario_file)
        assert url is None
        assert scenario == "检查首页"


# ── load_scenario ────────────────────────────────────────


class TestLoadScenario:
    """测试场景加载逻辑。"""

    def test_plain_string_returns_as_is(self):
        result = load_scenario("测试登录流程")
        assert result == "测试登录流程"

    def test_json_array_parsed_as_steps(self):
        raw = json.dumps(
            [
                {"type": "Context", "text": "打开页面"},
                {"type": "Outcome", "text": "验证结果"},
            ]
        )
        result = load_scenario(raw)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_empty_input_loads_from_file(self):
        result = load_scenario(None)
        assert isinstance(result, (str, list))

    def test_blank_string_loads_from_file(self):
        result = load_scenario("  ")
        assert isinstance(result, (str, list))

    def test_scenario_field_preferred_over_steps(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={
                "scenario": "模糊场景描述",
                "steps": [{"type": "Action", "text": "步骤"}],
            },
        ):
            result = load_scenario(None)
            assert result == "模糊场景描述"

    def test_fallback_to_steps_when_no_scenario(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={
                "steps": [{"type": "Action", "text": "步骤A"}],
            },
        ):
            result = load_scenario(None)
            assert isinstance(result, list)

    def test_today_replaced_in_scenario_text(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={"scenario": "日期 {today} 的测试"},
        ):
            result = load_scenario(None)
            assert isinstance(result, str)
            assert "{today}" not in result
            assert date.today().isoformat() in result


# ── load_session_defaults ───────────────────────────────


class TestLoadSessionDefaults:
    """测试 session 默认值加载。"""

    def test_returns_dict(self):
        result = load_session_defaults()
        assert isinstance(result, dict)

    def test_returns_empty_when_no_session_key(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file", return_value={}
        ):
            assert load_session_defaults() == {}

    def test_returns_session_block(self):
        with mock.patch(
            "webtestagent.config.scenarios._load_scenarios_file",
            return_value={"session": {"auto_load": True, "auto_save": False}},
        ):
            result = load_session_defaults()
            assert result["auto_load"] is True
            assert result["auto_save"] is False
