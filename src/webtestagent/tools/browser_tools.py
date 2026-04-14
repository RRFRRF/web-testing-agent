"""封装 playwright-cli 的轻量 browser tools。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from webtestagent.core.artifacts import format_artifact_response, register_file_artifact, save_text_artifact
from webtestagent.config.settings import OUTPUTS_DIR


class OpenPageInput(BaseModel):
    url: str = Field(description="要打开的目标 URL")


class ArtifactCaptureInput(BaseModel):
    label: str = Field(description="本次采集的简短标签，例如 home、after-search、error-state")


class BrowserActionInput(BaseModel):
    command: str = Field(description="要执行的 playwright-cli 子命令，不含 playwright-cli 前缀")
    label: str = Field(description="本次动作的标签")


def _runtime_context(config: RunnableConfig | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    context = config.get("context")
    if isinstance(context, dict):
        return context
    return {}


def _get_run_values(config: RunnableConfig | None) -> tuple[str, Path]:
    context = _runtime_context(config)
    run_id = str(context.get("run_id") or os.getenv("RUN_ID") or "adhoc-run")
    outputs_dir_raw = context.get("outputs_dir") or os.getenv("OUTPUTS_DIR") or str(OUTPUTS_DIR / run_id)
    return run_id, Path(outputs_dir_raw)


def _artifact_dir(outputs_dir: Path, name: str) -> Path:
    path = outputs_dir / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(outputs_dir: Path) -> Path:
    return outputs_dir / "manifest.json"


def _run_playwright(command_parts: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command_parts,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _playwright_prefix() -> list[str]:
    cli = (os.getenv("PLAYWRIGHT_CLI") or "playwright-cli").strip()
    if not cli:
        return ["playwright-cli"]

    if " " in cli:
        return cli.split()

    resolved = shutil.which(cli)
    if resolved:
        return [resolved]

    cmd_resolved = shutil.which(f"{cli}.cmd")
    if cmd_resolved:
        return [cmd_resolved]

    return [cli]


def _register_command_result(
    *,
    config: RunnableConfig | None,
    artifact_type: str,
    label: str,
    artifact_subdir: str,
    suffix: str,
    content: str,
) -> str:
    run_id, outputs_dir = _get_run_values(config)
    artifact_dir = _artifact_dir(outputs_dir, artifact_subdir)
    record = save_text_artifact(
        manifest_path=_manifest_path(outputs_dir),
        run_id=run_id,
        artifact_dir=artifact_dir,
        artifact_type=artifact_type,
        label=label,
        suffix=suffix,
        content=content,
    )
    return format_artifact_response(record)


def _register_existing_file(
    *,
    config: RunnableConfig | None,
    artifact_type: str,
    label: str,
    file_path: Path,
    preview: str,
) -> str:
    run_id, outputs_dir = _get_run_values(config)
    record = register_file_artifact(
        manifest_path=_manifest_path(outputs_dir),
        run_id=run_id,
        artifact_type=artifact_type,
        label=label,
        file_path=file_path,
        preview=preview,
    )
    return format_artifact_response(record)


def open_page(url: str, config: RunnableConfig) -> str:
    """在有头模式下打开目标页面。"""
    result = _run_playwright([*_playwright_prefix(), "open", url, "--headed"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to open page: {output.strip()}")
    return _register_command_result(
        config=config,
        artifact_type="open",
        label="open-page",
        artifact_subdir="console",
        suffix=".txt",
        content=output.strip(),
    )


def _capture_screenshot_record(*, label: str, config: RunnableConfig) -> dict[str, Any]:
    run_id, outputs_dir = _get_run_values(config)
    screenshots_dir = _artifact_dir(outputs_dir, "screenshots")
    existing = []
    if screenshots_dir.exists():
        existing = sorted(screenshots_dir.glob("*.png"))
    next_index = len(existing) + 1
    filename = f"{next_index:03d}-{label.strip().replace(' ', '-').lower() or 'screenshot'}.png"
    file_path = screenshots_dir / filename

    result = _run_playwright([*_playwright_prefix(), "screenshot", f"--filename={file_path.as_posix()}"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture screenshot: {output.strip()}")
    if not file_path.exists():
        raise RuntimeError(f"Screenshot command succeeded but file was not created: {file_path.as_posix()}")

    preview = f"Screenshot saved to {file_path.as_posix()}\nCommand output:\n{output.strip()}"
    record = register_file_artifact(
        manifest_path=_manifest_path(outputs_dir),
        run_id=run_id,
        artifact_type="screenshot",
        label=label,
        file_path=file_path,
        preview=preview,
    )
    return {
        "artifact_type": record.type,
        "label": record.label,
        "path": record.path,
        "size_bytes": record.size_bytes,
        "preview": record.preview,
    }


def capture_snapshot(label: str, config: RunnableConfig) -> str:
    """采集 snapshot，并默认同时截图，将原始结果落盘。"""
    result = _run_playwright([*_playwright_prefix(), "snapshot"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture snapshot: {output.strip()}")
    snapshot_response = _register_command_result(
        config=config,
        artifact_type="snapshot",
        label=label,
        artifact_subdir="snapshots",
        suffix=".yaml",
        content=output.strip(),
    )

    snapshot_path = None
    for line in snapshot_response.splitlines():
        if line.startswith("- path: "):
            snapshot_path = line.removeprefix("- path: ").strip()
            break

    screenshot_label = f"{label}-auto"
    screenshot: dict[str, Any] | None = None
    screenshot_error: str | None = None
    try:
        screenshot = _capture_screenshot_record(label=screenshot_label, config=config)
    except Exception as exc:
        screenshot_error = str(exc)

    return json.dumps(
        {
            "snapshot": {
                "artifact_type": "snapshot",
                "label": label,
                "path": snapshot_path,
                "summary": snapshot_response,
            },
            "screenshot": screenshot,
            "screenshot_error": screenshot_error,
        },
        ensure_ascii=False,
        indent=2,
    )


def capture_console(label: str, config: RunnableConfig) -> str:
    """采集 console 输出并落盘。"""
    result = _run_playwright([*_playwright_prefix(), "console"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture console logs: {output.strip()}")
    return _register_command_result(
        config=config,
        artifact_type="console",
        label=label,
        artifact_subdir="console",
        suffix=".txt",
        content=output.strip(),
    )


def capture_network(label: str, config: RunnableConfig) -> str:
    """采集 network 输出并落盘。"""
    result = _run_playwright([*_playwright_prefix(), "network"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture network logs: {output.strip()}")
    return _register_command_result(
        config=config,
        artifact_type="network",
        label=label,
        artifact_subdir="network",
        suffix=".txt",
        content=output.strip(),
    )


def capture_screenshot(label: str, config: RunnableConfig) -> str:
    """按需截图并把图片路径注册进 manifest。"""
    record = _capture_screenshot_record(label=label, config=config)
    return json.dumps(record, ensure_ascii=False, indent=2)


def run_browser_command(command: str, label: str, config: RunnableConfig) -> str:
    """执行自定义 playwright-cli 子命令，并将输出落盘。

    适用于必要时执行轻量命令，但推荐优先使用专门工具。
    """
    result = _run_playwright([*_playwright_prefix(), *command.split()])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    content = json.dumps(
        {
            "command": command,
            "returncode": result.returncode,
            "output": output.strip(),
        },
        ensure_ascii=False,
        indent=2,
    )
    return _register_command_result(
        config=config,
        artifact_type="command",
        label=label,
        artifact_subdir="console",
        suffix=".json",
        content=content,
    )


def build_browser_tools() -> list[StructuredTool]:
    """构建提供给 Deep Agent 的 browser tools。"""
    return [
        StructuredTool.from_function(
            name="capture_snapshot",
            description="Capture a page snapshot, automatically save a companion screenshot, persist both artifacts under outputs/{run_id}/, and return JSON containing the snapshot summary plus screenshot path.",
            func=capture_snapshot,
            args_schema=ArtifactCaptureInput,
        ),
        StructuredTool.from_function(
            name="capture_screenshot",
            description="Capture an on-demand screenshot when the agent decides a separate screenshot is useful, save it to outputs/{run_id}/screenshots/, and return JSON with the saved file path.",
            func=capture_screenshot,
            args_schema=ArtifactCaptureInput,
        ),
    ]
