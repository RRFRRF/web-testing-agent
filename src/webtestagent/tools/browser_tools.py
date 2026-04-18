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

from webtestagent.core.artifacts import (
    format_artifact_response,
    register_file_artifact,
    save_text_artifact,
    slugify_label,
)

INLINE_SNAPSHOT_MAX_CHARS = 9000


class OpenPageInput(BaseModel):
    url: str = Field(description="要打开的目标 URL")


class ArtifactCaptureInput(BaseModel):
    label: str = Field(
        description="本次采集的简短标签，例如 home、after-search、error-state"
    )


class BrowserActionInput(BaseModel):
    command: str = Field(
        description="要执行的 playwright-cli 子命令，不含 playwright-cli 前缀"
    )
    label: str = Field(description="本次动作的标签")


def _runtime_context(config: RunnableConfig | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    context = config.get("context")
    if isinstance(context, dict):
        return context
    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        nested_context = configurable.get("context")
        if isinstance(nested_context, dict):
            return nested_context
    return {}


def _get_run_values(config: RunnableConfig | None) -> tuple[str, Path]:
    context = _runtime_context(config)
    run_id_value = context.get("run_id")
    outputs_dir_value = context.get("outputs_dir")
    if not run_id_value or not outputs_dir_value:
        raise RuntimeError(
            "Missing run context in tool config: run_id and outputs_dir are required"
        )
    return str(run_id_value), Path(str(outputs_dir_value))


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


def _extract_artifact_path(summary: str) -> str | None:
    for line in summary.splitlines():
        if line.startswith("- path: "):
            return line.removeprefix("- path: ").strip()
    return None


def open_page(url: str, config: RunnableConfig) -> str:
    """Legacy/internal unused helper: open a page in headed mode and persist command output."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"URL must start with http:// or https://: {url!r}")
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
    filename = f"{next_index:03d}-{slugify_label(label) or 'screenshot'}.png"
    file_path = screenshots_dir / filename

    result = _run_playwright(
        [*_playwright_prefix(), "screenshot", f"--filename={file_path.as_posix()}"]
    )
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture screenshot: {output.strip()}")
    if not file_path.exists():
        raise RuntimeError(
            f"Screenshot command succeeded but file was not created: {file_path.as_posix()}"
        )

    preview = (
        f"Screenshot saved to {file_path.as_posix()}\nCommand output:\n{output.strip()}"
    )
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
    """Capture a snapshot, always persist snapshot+screenshot, and inline small snapshots."""
    result = _run_playwright([*_playwright_prefix(), "snapshot"])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    snapshot_text = output.strip()
    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture snapshot: {snapshot_text}")

    snapshot_summary = _register_command_result(
        config=config,
        artifact_type="snapshot",
        label=label,
        artifact_subdir="snapshots",
        suffix=".yaml",
        content=snapshot_text,
    )
    snapshot_path = _extract_artifact_path(snapshot_summary)
    is_full_inline = len(snapshot_text) < INLINE_SNAPSHOT_MAX_CHARS

    screenshot_label = f"{label}-auto"
    screenshot: dict[str, Any] | None = None
    screenshot_error: str | None = None
    try:
        screenshot = _capture_screenshot_record(label=screenshot_label, config=config)
    except Exception as exc:
        screenshot_error = str(exc)

    snapshot_payload = {
        "artifact_type": "snapshot",
        "label": label,
        "path": snapshot_path,
        "summary": (
            snapshot_text
            if is_full_inline
            else "Snapshot too large to inline; read the saved artifact if you need the full DOM."
        ),
        "is_full_inline": is_full_inline,
        "content": snapshot_text if is_full_inline else None,
        "content_chars": len(snapshot_text),
    }

    return json.dumps(
        {
            "snapshot": snapshot_payload,
            "screenshot": screenshot,
            "screenshot_error": screenshot_error,
        },
        ensure_ascii=False,
        indent=2,
    )
def capture_console(label: str, config: RunnableConfig) -> str:
    """Legacy/internal unused helper: capture console output and persist it."""
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
    """Legacy/internal unused helper: capture network output and persist it."""
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
    """Legacy/internal unused helper: run a raw playwright-cli command and persist the result."""
    # 拒绝含 -- 的命令，防止注入 playwright-cli flag
    if "--" in command:
        raise ValueError(
            f"Command must not contain '--' (potential flag injection): {command!r}"
        )
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
            description="Capture a page snapshot, always save the snapshot artifact plus an automatic companion screenshot, inline the full snapshot content when it is under 9000 characters, and otherwise return the saved path with a summary.",
            func=capture_snapshot,
            args_schema=ArtifactCaptureInput,
        ),
        StructuredTool.from_function(
            name="capture_screenshot",
            description="Capture an on-demand screenshot when a separate screenshot is useful, save it to outputs/{run_id}/screenshots/, and return JSON with the saved file path.",
            func=capture_screenshot,
            args_schema=ArtifactCaptureInput,
        ),
    ]
