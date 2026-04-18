"""场景/步骤加载逻辑。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from webtestagent.config.settings import SCENARIOS_FILE

ScenarioValue = str | list[dict[str, str]]


def _load_scenarios_file() -> dict[str, Any]:
    """从 scenarios/default.json 加载默认场景。"""
    if SCENARIOS_FILE.exists():
        return json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    return {}


def _today() -> str:
    return date.today().isoformat()


def _replace_today(value: str) -> str:
    return value.replace("{today}", _today())


def get_default_url() -> str:
    """返回场景配置中的默认 URL，若不存在则 fallback。"""
    scenarios = _load_scenarios_file()
    return scenarios.get("default_url", "https://www.12306.cn/index/")


def get_default_scenario_input() -> str:
    """返回适合 Web 文本框展示的默认 scenario 输入。"""
    scenarios = _load_scenarios_file()
    scenario_text = scenarios.get("scenario")
    if isinstance(scenario_text, str) and scenario_text.strip():
        return _replace_today(scenario_text.strip())

    raw_steps = scenarios.get("steps")
    if raw_steps:
        return json.dumps(_normalize_steps(raw_steps), ensure_ascii=False, indent=2)

    return ""


def build_default_steps() -> list[dict[str, str]]:
    """从场景配置构建默认步骤列表，支持 {today} 占位符。"""
    scenarios = _load_scenarios_file()
    raw_steps = scenarios.get("steps")

    if not raw_steps:
        # fallback 硬编码
        return [
            {"type": "Context", "text": "我打开 12306 首页"},
            {"type": "Action", "text": "将出发地选择为天津"},
            {"type": "Action", "text": "将目的地选择为上海"},
            {"type": "Action", "text": f"将出发日期设置为今天（{_today()}）"},
            {"type": "Action", "text": "点击查询或搜索按钮"},
            {
                "type": "Outcome",
                "text": "页面应出现车次搜索结果、余票列表，或进入包含查询结果的页面",
            },
        ]

    return [
        {"type": step["type"], "text": _replace_today(step["text"])}
        for step in raw_steps
    ]


def _parse_steps(raw_json: str) -> list[dict[str, str]]:
    """解析 JSON 字符串为步骤列表（内部辅助）。"""
    try:
        steps = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in steps: {exc}") from exc

    return _normalize_steps(steps)


def _normalize_steps(steps: Any) -> list[dict[str, str]]:
    if not isinstance(steps, list) or not steps:
        raise RuntimeError("steps-json must be a non-empty JSON array")

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(steps, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Step {index} must be an object")
        step_type = str(item.get("type", "")).strip()
        text = str(item.get("text", "")).strip()
        if not step_type or not text:
            raise RuntimeError(f"Step {index} must contain non-empty 'type' and 'text'")
        normalized.append({"type": step_type, "text": _replace_today(text)})
    return normalized


def load_scenario_file(path: str | Path) -> tuple[str | None, ScenarioValue]:
    """从外部 JSON 文件加载场景，返回 (url, scenario)。"""
    scenario_path = Path(path)
    try:
        raw = scenario_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Scenario file not found: {scenario_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot read scenario file: {scenario_path} ({exc})") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in scenario file: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Scenario file must be a JSON object")

    url_value = data.get("url") or data.get("default_url")
    url = str(url_value).strip() if isinstance(url_value, str) and url_value.strip() else None

    scenario_text = data.get("scenario")
    if isinstance(scenario_text, str) and scenario_text.strip():
        return url, _replace_today(scenario_text.strip())

    raw_steps = data.get("steps")
    if raw_steps is not None:
        return url, _normalize_steps(raw_steps)

    raise RuntimeError("Scenario file must contain non-empty 'scenario' or 'steps'")


def load_scenario(raw_input: str | None) -> ScenarioValue:
    """加载测试场景，支持模糊描述（str）和结构化步骤（list）。

    优先级：
    1. raw_input 是 JSON 数组 → 解析为结构化步骤
    2. raw_input 是普通字符串 → 作为模糊场景描述
    3. raw_input 为空 → 从场景配置加载（优先 scenario 字段，fallback steps）
    """
    if raw_input:
        raw_input = raw_input.strip()
        # 尝试 JSON 数组解析
        if raw_input.startswith("["):
            return _parse_steps(raw_input)
        # 普通字符串作为模糊场景
        return raw_input

    # 从场景配置加载默认值
    data = _load_scenarios_file()

    # 优先使用 scenario 字段（模糊描述）
    scenario_text = data.get("scenario", "").strip()
    if scenario_text:
        return _replace_today(scenario_text)

    # fallback 到 steps 字段（结构化步骤）
    return build_default_steps()


def load_session_defaults() -> dict[str, Any]:
    """从 scenarios/default.json 读取 session 配置块。"""
    data = _load_scenarios_file()
    return data.get("session", {})
