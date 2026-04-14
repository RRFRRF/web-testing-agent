"""项目路径、环境变量加载、基础配置。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── 路径 ────────────────────────────────────────────────────
# 从 src/webtestagent/config/settings.py 回溯到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent
SKILLS_DIR = "/skills/"  # 相对于 backend root_dir（PROJECT_ROOT）

# ── 场景配置 ────────────────────────────────────────────────
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
SCENARIOS_FILE = SCENARIOS_DIR / "default.json"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# ── 登录态存储 ──────────────────────────────────────────────
COOKIES_DIR = PROJECT_ROOT / "cookies"


def init_env() -> None:
    """加载 .env 文件。"""
    load_dotenv(PROJECT_ROOT / ".env")


def require_env(name: str) -> str:
    """读取必需的环境变量，不存在则报错。"""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_bool(value: str | None, default: bool = False) -> bool:
    """解析布尔值字符串（环境变量等）。"""
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")
