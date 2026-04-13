"""MVP Deep Agents Web Testing — 入口。"""
from __future__ import annotations

import argparse
import locale
import os
import subprocess
import sys

from agent import build_agent, resolve_playwright_cli
from config import get_default_url, init_env, load_scenario
from output import extract_text, print_stream_event, final_result_from_state
from prompts import build_prompt


# ── UTF-8 运行时修补（Windows 中文环境） ─────────────────────

def configure_utf8_runtime() -> None:
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


# ── CLI 参数 ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal Deep Agents web testing MVP")
    parser.add_argument("--url", help="Target URL")
    parser.add_argument("--scenario", help="Test scenario: a plain text description or a JSON steps array")
    parser.add_argument("--show-full-events", action="store_true", help="Print full stream events without truncation")
    return parser.parse_args()


# ── 主流程 ────────────────────────────────────────────────

def main() -> None:
    configure_utf8_runtime()
    init_env()

    args = parse_args()
    url = (args.url or os.getenv("TARGET_URL") or get_default_url()).strip()
    raw_scenario = args.scenario or os.getenv("SCENARIO") or os.getenv("STEPS_JSON")
    scenario = load_scenario(raw_scenario)
    prompt = build_prompt(url, scenario)
    cli_command = resolve_playwright_cli()
    agent = build_agent()
    config = {"configurable": {"thread_id": "mvp-web-test-run"}}

    scenario_desc = scenario if isinstance(scenario, str) else f"{len(scenario)} 个结构化步骤"
    print(f"[start] URL: {url}")
    print(f"[start] 场景: {scenario_desc}")
    print(f"[start] playwright-cli: {cli_command}")
    print("[start] Agent 开始执行...\n")

    final_result = None
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
        stream_mode=["updates"],
    ):
        if not isinstance(chunk, tuple):
            final_result = chunk
        print_stream_event(chunk, show_full_events=args.show_full_events)

    if final_result is None:
        final_result = final_result_from_state(agent, config)

    print("\n===== 最终测试报告 =====\n")
    print(extract_text(final_result))


if __name__ == "__main__":
    main()
