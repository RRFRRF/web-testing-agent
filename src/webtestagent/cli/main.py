"""MVP Deep Agents Web Testing — CLI 入口。"""
from __future__ import annotations

import argparse
import locale
import os
import subprocess
import sys

from webtestagent.config.settings import init_env
from webtestagent.config.scenarios import get_default_url, load_scenario
from webtestagent.output.formatters import format_event_for_cli
from webtestagent.core.runner import prepare_run, execute_prepared_run


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

    prepared = prepare_run(url, scenario)

    print(f"[start] URL: {prepared.url}")
    print(f"[start] 场景: {prepared.scenario_desc}")
    print(f"[start] run_id: {prepared.run_context.run_id}")
    print(f"[start] outputs: {prepared.run_context.run_dir.as_posix()}")
    print(f"[start] playwright-cli: {prepared.cli_command}")
    print("[start] Agent 开始执行...\n")

    def on_event(event: dict[str, object]) -> None:
        if event.get("channel") == "system":
            return
        print(format_event_for_cli(event))

    result = execute_prepared_run(
        prepared,
        on_event=on_event,
        show_full_events=args.show_full_events,
    )

    print("\n===== 最终测试报告 =====\n")
    print(result.final_report)


if __name__ == "__main__":
    main()
