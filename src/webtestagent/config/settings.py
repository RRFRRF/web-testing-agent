"""项目路径、环境变量加载、基础配置。"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from datetime import datetime
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


def configure_utf8_runtime() -> None:
    """配置运行时 UTF-8 编码，确保 subprocess / stdout / locale 一致。"""
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    if hasattr(locale, "getpreferredencoding"):
        locale.getpreferredencoding = lambda do_setlocale=True: "utf-8"  # type: ignore[assignment]
    if hasattr(locale, "getencoding"):
        locale.getencoding = lambda: "utf-8"  # type: ignore[assignment]
    if hasattr(subprocess, "_text_encoding"):
        subprocess._text_encoding = lambda: "utf-8"  # type: ignore[attr-defined]


def now_iso() -> str:
    """返回当前时间的 ISO 格式字符串。"""
    return datetime.now().isoformat(timespec="seconds")
