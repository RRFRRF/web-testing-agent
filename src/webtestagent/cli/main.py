"""MVP Deep Agents Web Testing — CLI 入口。"""
from __future__ import annotations

import argparse
import locale
import os
import subprocess
import sys

from webtestagent.config.settings import init_env, parse_bool
from webtestagent.config.scenarios import get_default_url, load_scenario, load_session_defaults
from webtestagent.output.formatters import format_event_for_cli
from webtestagent.core.runner import prepare_run, execute_prepared_run
from webtestagent.core.session import SessionPersistenceConfig


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
    # session 持久化
    parser.add_argument("--auto-load-session", action="store_true", help="Auto-load session state before run")
    parser.add_argument("--auto-save-session", action="store_true", help="Auto-save session state after run")
    parser.add_argument("--session-site-id", help="Override site ID for session storage")
    parser.add_argument("--session-account-id", help="Account identifier for multi-account sites")
    parser.add_argument("--session-dir", help="Override session storage directory")
    return parser.parse_args()


# ── 主流程 ────────────────────────────────────────────────

def main() -> None:
    configure_utf8_runtime()
    init_env()

    args = parse_args()
    url = (args.url or os.getenv("TARGET_URL") or get_default_url()).strip()
    raw_scenario = args.scenario or os.getenv("SCENARIO") or os.getenv("STEPS_JSON")
    scenario = load_scenario(raw_scenario)

    # ── session 配置（CLI > env > scenarios/default.json） ──────
    session_defaults = load_session_defaults()
    from pathlib import Path

    session_config = SessionPersistenceConfig(
        auto_load=(
            args.auto_load_session
            or parse_bool(os.getenv("AUTO_LOAD_SESSION"))
            or bool(session_defaults.get("auto_load"))
        ),
        auto_save=(
            args.auto_save_session
            or parse_bool(os.getenv("AUTO_SAVE_SESSION"))
            or bool(session_defaults.get("auto_save"))
        ),
        site_id=args.session_site_id or os.getenv("SESSION_SITE_ID") or session_defaults.get("site_id"),
        account_id=args.session_account_id or os.getenv("SESSION_ACCOUNT_ID") or session_defaults.get("account_id"),
        storage_dir=(
            Path(args.session_dir) if args.session_dir
            else Path(session_defaults["storage_dir"]) if session_defaults.get("storage_dir")
            else None
        ),
    )

    prepared = prepare_run(url, scenario, session_config=session_config)

    print(f"[start] URL: {prepared.url}")
    print(f"[start] 场景: {prepared.scenario_desc}")
    print(f"[start] run_id: {prepared.run_context.run_id}")
    print(f"[start] outputs: {prepared.run_context.run_dir.as_posix()}")
    print(f"[start] playwright-cli: {prepared.cli_command}")
    if prepared.session_state:
        ss = prepared.session_state
        print(f"[start] session: site={ss.site_id} account={ss.account_id or '_default'} "
              f"load={'OK' if ss.load_applied else 'skip'} save={'on' if ss.enabled_save else 'off'}")
    print("[start] Agent 开始执行...\n")

    def on_event(event: dict[str, object]) -> None:
        channel = event.get("channel")
        if channel == "system" and event.get("mode") not in ("session-save",):
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
