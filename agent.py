"""Deep Agent 构建：模型、后端、技能组装。"""
from __future__ import annotations

import shutil
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from config import PROJECT_ROOT, SKILLS_DIR, require_env
from messages import normalize_messages_for_compatible_endpoint
from prompts import SYSTEM_PROMPT


def build_model() -> ChatOpenAI:
    """构建 ChatOpenAI 模型实例。"""
    return ChatOpenAI(
        model=require_env("OPENAI_MODEL"),
        api_key=require_env("OPENAI_API_KEY"),
        base_url=require_env("OPENAI_BASE_URL"),
        temperature=0,
    )


def resolve_playwright_cli() -> str:
    """检测 playwright-cli 可用路径。"""
    cli = shutil.which("playwright-cli")
    if cli:
        return "playwright-cli"
    npx = shutil.which("npx")
    if npx:
        return "npx playwright-cli"
    raise RuntimeError(
        "playwright-cli is not available. "
        "Please install @playwright/cli globally or make npx available."
    )


def build_agent() -> Any:
    """创建并返回配置好的 Deep Agent。"""
    backend = LocalShellBackend(
        root_dir=str(PROJECT_ROOT),
        virtual_mode=True,
        env={
            "PLAYWRIGHT_CLI": resolve_playwright_cli(),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
        inherit_env=True,
    )
    return create_deep_agent(
        model=build_model(),
        tools=[],
        system_prompt=SYSTEM_PROMPT,
        backend=backend,
        skills=[SKILLS_DIR],
        middleware=[normalize_messages_for_compatible_endpoint],
        checkpointer=MemorySaver(),
    )
