"""项目路径、环境变量加载、基础配置。"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ── 路径 ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parent
SKILLS_DIR = "/skills/"  # 相对于 backend root_dir（PROJECT_ROOT）

# ── 场景配置 ────────────────────────────────────────────────
SCENARIOS_FILE = PROJECT_ROOT / "scenarios.json"


def init_env() -> None:
    """加载 .env 文件。"""
    load_dotenv(PROJECT_ROOT / ".env")


def require_env(name: str) -> str:
    """读取必需的环境变量，不存在则报错。"""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ── 场景/步骤加载 ────────────────────────────────────────────

def _load_scenarios_file() -> dict[str, Any]:
    """从 scenarios.json 加载默认场景。"""
    if SCENARIOS_FILE.exists():
        return json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    return {}


def get_default_url() -> str:
    """返回 scenarios.json 中的默认 URL，若不存在则 fallback。"""
    scenarios = _load_scenarios_file()
    return scenarios.get("default_url", "https://www.12306.cn/index/")


def build_default_steps() -> list[dict[str, str]]:
    """从 scenarios.json 构建默认步骤列表，支持 {today} 占位符。"""
    today = date.today().isoformat()
    scenarios = _load_scenarios_file()
    raw_steps = scenarios.get("steps")

    if not raw_steps:
        # fallback 硬编码
        return [
            {"type": "Context", "text": "我打开 12306 首页"},
            {"type": "Action", "text": "将出发地选择为天津"},
            {"type": "Action", "text": "将目的地选择为上海"},
            {"type": "Action", "text": f"将出发日期设置为今天（{today}）"},
            {"type": "Action", "text": "点击查询或搜索按钮"},
            {"type": "Outcome", "text": "页面应出现车次搜索结果、余票列表，或进入包含查询结果的页面"},
        ]

    return [
        {"type": step["type"], "text": step["text"].replace("{today}", today)}
        for step in raw_steps
    ]


def _parse_steps(raw_json: str) -> list[dict[str, str]]:
    """解析 JSON 字符串为步骤列表（内部辅助）。"""
    try:
        steps = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in steps: {exc}") from exc

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
        normalized.append({"type": step_type, "text": text})
    return normalized


def load_scenario(raw_input: str | None) -> str | list[dict[str, str]]:
    """加载测试场景，支持模糊描述（str）和结构化步骤（list）。

    优先级：
    1. raw_input 是 JSON 数组 → 解析为结构化步骤
    2. raw_input 是普通字符串 → 作为模糊场景描述
    3. raw_input 为空 → 从 scenarios.json 加载（优先 scenario 字段，fallback steps）
    """
    if raw_input:
        raw_input = raw_input.strip()
        # 尝试 JSON 数组解析
        if raw_input.startswith("["):
            return _parse_steps(raw_input)
        # 普通字符串作为模糊场景
        return raw_input

    # 从 scenarios.json 加载默认值
    data = _load_scenarios_file()
    today = date.today().isoformat()

    # 优先使用 scenario 字段（模糊描述）
    scenario_text = data.get("scenario", "").strip()
    if scenario_text:
        return scenario_text.replace("{today}", today)

    # fallback 到 steps 字段（结构化步骤）
    return build_default_steps()
