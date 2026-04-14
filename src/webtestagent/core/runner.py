"""共享测试运行核心：供 CLI 与 Web 控制台复用。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from webtestagent.core.agent_builder import build_agent, resolve_playwright_cli
from webtestagent.core.artifacts import build_preview, ensure_manifest, register_file_artifact, update_manifest_target_url
from webtestagent.config.settings import init_env
from webtestagent.output.stream import events_from_stream_chunk, final_result_from_state
from webtestagent.output.formatters import extract_text
from webtestagent.prompts.user import build_prompt
from webtestagent.core.run_context import RunContext, create_run_context
from webtestagent.core.session import (
    ResolvedSessionState,
    SessionPersistenceConfig,
    load_session_state,
    resolve_session,
    save_session_state,
    session_manifest_data,
)


Scenario = str | list[dict[str, str]]
EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class PreparedRun:
    url: str
    scenario: Scenario
    scenario_desc: str
    prompt: str
    run_context: RunContext
    cli_command: str
    config: dict[str, Any]
    agent: Any
    thread_id: str
    session_state: ResolvedSessionState | None = None


@dataclass
class RunResult:
    url: str
    scenario: Scenario
    scenario_desc: str
    run_id: str
    run_dir: Path
    manifest_path: Path
    report_path: Path
    cli_command: str
    final_result: Any
    final_report: str


def describe_scenario(scenario: Scenario) -> str:
    """返回适合展示的场景描述。"""
    if isinstance(scenario, str):
        return scenario
    return f"{len(scenario)} 个结构化步骤"


def build_thread_id(run_id: str) -> str:
    """为本次运行构建独立 thread_id。"""
    return f"mvp-web-test-run-{run_id}"


def inject_run_environment(run_context: RunContext) -> None:
    """注入当前运行上下文到环境变量，兼容 browser tools 回退逻辑。"""
    os.environ["RUN_ID"] = run_context.run_id
    os.environ["OUTPUTS_DIR"] = run_context.run_dir.as_posix()
    os.environ["MANIFEST_PATH"] = run_context.manifest_path.as_posix()


def prepare_run(
    url: str,
    scenario: Scenario,
    *,
    thread_id: str | None = None,
    session_config: SessionPersistenceConfig | None = None,
) -> PreparedRun:
    """准备一次测试运行，但不立即消费流。"""
    init_env()

    run_context = create_run_context()
    inject_run_environment(run_context)
    ensure_manifest(run_context.manifest_path, run_id=run_context.run_id, target_url=url)
    update_manifest_target_url(run_context.manifest_path, run_id=run_context.run_id, target_url=url)

    # ── session 解析与前置导入 ─────────────────────────────
    session_state: ResolvedSessionState | None = None
    if session_config and (session_config.auto_load or session_config.auto_save):
        session_state = resolve_session(session_config, url)

        # 更新 manifest session 元数据
        _update_manifest_session_block(
            run_context.manifest_path,
            run_id=run_context.run_id,
            session_data=session_manifest_data(session_state),
        )

        # 前置导入
        if session_state.enabled_load:
            success, message = load_session_state(session_state)
            _update_manifest_session_load(
                run_context.manifest_path,
                run_id=run_context.run_id,
                attempted=True,
                applied=success,
                message=message,
            )

    prompt = build_prompt(
        url, scenario,
        outputs_dir=run_context.run_dir.as_posix(),
        session_state=session_state,
    )
    cli_command = resolve_playwright_cli()
    agent = build_agent()
    resolved_thread_id = thread_id or build_thread_id(run_context.run_id)
    config: dict[str, Any] = {
        "configurable": {"thread_id": resolved_thread_id},
        "context": {
            "run_id": run_context.run_id,
            "outputs_dir": run_context.run_dir.as_posix(),
            "manifest_path": run_context.manifest_path.as_posix(),
            "target_url": url,
        },
    }

    # 注入 session 上下文
    if session_state:
        config["context"].update({
            "session_auto_load": session_state.enabled_load,
            "session_auto_save": session_state.enabled_save,
            "session_site_id": session_state.site_id,
            "session_account_id": session_state.account_id,
            "session_load_applied": session_state.load_applied,
        })

    return PreparedRun(
        url=url,
        scenario=scenario,
        scenario_desc=describe_scenario(scenario),
        prompt=prompt,
        run_context=run_context,
        cli_command=cli_command,
        config=config,
        agent=agent,
        thread_id=resolved_thread_id,
        session_state=session_state,
    )


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit_event(callback: EventCallback | None, event: dict[str, Any]) -> None:
    """向调用方发出结构化事件。"""
    if callback is None:
        return
    payload = {"timestamp": _timestamp(), **event}
    callback(payload)


def save_final_report(prepared: PreparedRun, final_report: str) -> Path:
    """将最终报告落盘，并注册到 manifest。"""
    report_path = prepared.run_context.run_dir / "report.md"
    report_path.write_text(final_report, encoding="utf-8")
    register_file_artifact(
        manifest_path=prepared.run_context.manifest_path,
        run_id=prepared.run_context.run_id,
        artifact_type="report",
        label="final-report",
        file_path=report_path,
        preview=build_preview(final_report),
    )
    return report_path


def execute_prepared_run(
    prepared: PreparedRun,
    *,
    on_event: EventCallback | None = None,
    show_full_events: bool = False,
) -> RunResult:
    """执行一次已准备好的测试运行。"""
    inject_run_environment(prepared.run_context)
    emit_event(
        on_event,
        {
            "channel": "system",
            "mode": "start",
            "summary": f"开始执行 run {prepared.run_context.run_id}",
            "payload": {
                "url": prepared.url,
                "scenario": prepared.scenario_desc,
                "run_id": prepared.run_context.run_id,
                "outputs": prepared.run_context.run_dir.as_posix(),
                "playwright_cli": prepared.cli_command,
                "thread_id": prepared.thread_id,
            },
        },
    )

    final_result: Any = None
    try:
        for chunk in prepared.agent.stream(
            {"messages": [{"role": "user", "content": prepared.prompt}]},
            config=prepared.config,
            stream_mode=["updates"],
        ):
            if not isinstance(chunk, tuple):
                final_result = chunk
            for event in events_from_stream_chunk(chunk, show_full_events=show_full_events):
                emit_event(on_event, event)

        if final_result is None:
            final_result = final_result_from_state(prepared.agent, prepared.config)

        final_report = extract_text(final_result)
        report_path = save_final_report(prepared, final_report)
        emit_event(
            on_event,
            {
                "channel": "system",
                "mode": "complete",
                "summary": "测试运行完成",
                "payload": {
                    "run_id": prepared.run_context.run_id,
                    "report_path": report_path.as_posix(),
                    "manifest_path": prepared.run_context.manifest_path.as_posix(),
                },
            },
        )
        return RunResult(
            url=prepared.url,
            scenario=prepared.scenario,
            scenario_desc=prepared.scenario_desc,
            run_id=prepared.run_context.run_id,
            run_dir=prepared.run_context.run_dir,
            manifest_path=prepared.run_context.manifest_path,
            report_path=report_path,
            cli_command=prepared.cli_command,
            final_result=final_result,
            final_report=final_report,
        )
    except Exception as exc:
        emit_event(
            on_event,
            {
                "channel": "system",
                "mode": "error",
                "summary": f"测试运行失败：{exc}",
                "payload": {
                    "run_id": prepared.run_context.run_id,
                    "error": str(exc),
                },
            },
        )
        raise
    finally:
        # ── session 后置保存（成功和失败都尝试） ─────────────
        if prepared.session_state and prepared.session_state.enabled_save:
            save_ok, save_msg = save_session_state(
                prepared.session_state, prepared.run_context.run_id
            )
            _update_manifest_session_save(
                prepared.run_context.manifest_path,
                run_id=prepared.run_context.run_id,
                attempted=True,
                succeeded=save_ok,
                message=save_msg,
            )
            emit_event(
                on_event,
                {
                    "channel": "system",
                    "mode": "session-save",
                    "summary": f"Session save: {'OK' if save_ok else 'FAILED'} - {save_msg}",
                    "payload": {
                        "run_id": prepared.run_context.run_id,
                        "succeeded": save_ok,
                        "message": save_msg,
                    },
                },
            )


def run_test(
    url: str,
    scenario: Scenario,
    *,
    thread_id: str | None = None,
    on_event: EventCallback | None = None,
    show_full_events: bool = False,
    session_config: SessionPersistenceConfig | None = None,
) -> RunResult:
    """准备并执行一次完整测试运行。"""
    prepared = prepare_run(url, scenario, thread_id=thread_id, session_config=session_config)
    return execute_prepared_run(prepared, on_event=on_event, show_full_events=show_full_events)


# ── manifest session 辅助 ──────────────────────────────────

import json as _json


def _read_manifest_raw(manifest_path: Path, *, run_id: str) -> dict[str, Any]:
    """读取 manifest 原始数据。"""
    if manifest_path.exists():
        return _json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"run_id": run_id}


def _write_manifest_raw(manifest_path: Path, data: dict[str, Any]) -> None:
    """写入 manifest。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    temp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(manifest_path)


def _update_manifest_session_block(
    manifest_path: Path, *, run_id: str, session_data: dict[str, Any]
) -> None:
    data = _read_manifest_raw(manifest_path, run_id=run_id)
    data["session"] = session_data
    _write_manifest_raw(manifest_path, data)


def _update_manifest_session_load(
    manifest_path: Path, *, run_id: str, attempted: bool, applied: bool, message: str
) -> None:
    data = _read_manifest_raw(manifest_path, run_id=run_id)
    session = data.get("session", {})
    session["load"] = {"attempted": attempted, "applied": applied, "message": message}
    data["session"] = session
    _write_manifest_raw(manifest_path, data)


def _update_manifest_session_save(
    manifest_path: Path, *, run_id: str, attempted: bool, succeeded: bool, message: str
) -> None:
    data = _read_manifest_raw(manifest_path, run_id=run_id)
    session = data.get("session", {})
    session["save"] = {"attempted": attempted, "succeeded": succeeded, "message": message}
    data["session"] = session
    _write_manifest_raw(manifest_path, data)
