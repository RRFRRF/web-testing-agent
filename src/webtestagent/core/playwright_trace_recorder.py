"""Persist Playwright trace records and related artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from webtestagent.config.settings import now_iso
from webtestagent.core.artifacts import (
    build_preview,
    register_file_artifact,
    save_json_artifact,
    save_text_artifact,
    slugify_label,
)
from webtestagent.tools.browser_tools import INLINE_SNAPSHOT_MAX_CHARS

ScreenshotCommand = Callable[[Path], tuple[int, str]]


@dataclass(frozen=True)
class TraceRecordResult:
    step_index: int
    status: str
    summary: str
    trace_path: str
    snapshot_path: str | None
    screenshot_path: str | None
    stdout_path: str | None
    stderr_path: str | None
    warnings: list[str]


class PlaywrightTraceRecorder:
    def __init__(self, *, run_id: str, outputs_dir: Path, manifest_path: Path) -> None:
        self.run_id = run_id
        self.outputs_dir = outputs_dir
        self.manifest_path = manifest_path
        self.traces_dir = outputs_dir / "traces"
        self.snapshots_dir = outputs_dir / "snapshots"
        self.screenshots_dir = outputs_dir / "screenshots"
        self.console_dir = outputs_dir / "console"
        for path in (
            self.traces_dir,
            self.snapshots_dir,
            self.screenshots_dir,
            self.console_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def record_command_trace(
        self,
        *,
        phase: str,
        command: str,
        command_type: str,
        exit_code: int,
        output: str,
        screenshot_command: ScreenshotCommand | None = None,
        is_read_command: bool = False,
    ) -> TraceRecordResult:
        warnings: list[str] = []
        step_index = self._next_step_index()
        step_slug = f"{step_index:03d}-{phase}-{slugify_label(command_type)}"
        label = f"{phase}-{step_index:03d}-{slugify_label(command_type)}"

        # stdout
        stdout_record = save_text_artifact(
            manifest_path=self.manifest_path,
            run_id=self.run_id,
            artifact_dir=self.console_dir,
            artifact_type="trace-stdout",
            label=label,
            suffix=".stdout.txt",
            content=output,
        )

        # snapshot & screenshot share the same step_slug prefix
        snapshot_record = None
        screenshot_record = None

        if command_type == "snapshot":
            snapshot_text = self._extract_snapshot_text(output)
            if snapshot_text:
                snapshot_record = save_text_artifact(
                    manifest_path=self.manifest_path,
                    run_id=self.run_id,
                    artifact_dir=self.snapshots_dir,
                    artifact_type="trace-snapshot",
                    label=label,
                    suffix=".yaml",
                    content=snapshot_text,
                    filename=f"{step_slug}.yaml",
                )
            else:
                warnings.append("snapshot missing from playwright output")

        elif command_type == "screenshot":
            screenshot_path = self._extract_screenshot_path(output)
            if screenshot_path and Path(screenshot_path).exists():
                screenshot_record = register_file_artifact(
                    manifest_path=self.manifest_path,
                    run_id=self.run_id,
                    artifact_type="trace-screenshot",
                    label=label,
                    file_path=Path(screenshot_path),
                    preview=build_preview(output),
                )
            else:
                warnings.append("screenshot file not found in playwright output")

        else:
            # Normal action command: save snapshot from output + take extra screenshot
            snapshot_text = self._extract_snapshot_text(output)
            if snapshot_text:
                snapshot_record = save_text_artifact(
                    manifest_path=self.manifest_path,
                    run_id=self.run_id,
                    artifact_dir=self.snapshots_dir,
                    artifact_type="trace-snapshot",
                    label=label,
                    suffix=".yaml",
                    content=snapshot_text,
                    filename=f"{step_slug}.yaml",
                )
            else:
                warnings.append("snapshot missing from playwright output")

            if screenshot_command:
                target_path = self.screenshots_dir / f"{step_slug}.png"
                sc_exit, sc_output = screenshot_command(target_path)
                if sc_exit == 0 and target_path.exists():
                    screenshot_record = register_file_artifact(
                        manifest_path=self.manifest_path,
                        run_id=self.run_id,
                        artifact_type="trace-screenshot",
                        label=label,
                        file_path=target_path,
                        preview=build_preview(sc_output),
                    )
                else:
                    warnings.append(
                        f"screenshot failed: {sc_output.strip() or sc_exit}"
                    )

        status = "success"
        if exit_code != 0:
            status = "failed"
        elif warnings:
            status = "partial"

        trace_payload: dict[str, Any] = {
            "step_index": step_index,
            "phase": phase,
            "command": command,
            "command_type": command_type,
            "timestamp": now_iso(),
            "status": status,
            "snapshot_path": snapshot_record.path if snapshot_record else None,
            "snapshot_inline_summary": self._snapshot_summary(
                self._extract_snapshot_text(output)
            ),
            "snapshot_chars": len(self._extract_snapshot_text(output)),
            "screenshot_path": screenshot_record.path if screenshot_record else None,
            "stdout_path": stdout_record.path,
            "stderr_path": None,
            "warnings": warnings,
        }
        save_json_artifact(
            manifest_path=self.manifest_path,
            run_id=self.run_id,
            artifact_dir=self.traces_dir,
            artifact_type="trace",
            label=label,
            payload=trace_payload,
            filename=f"{step_slug}.json",
        )
        summary = (
            f"playwright trace saved: step {step_index} {command_type}, "
            f"screenshot={trace_payload['screenshot_path']}, "
            f"snapshot={trace_payload['snapshot_path']}"
        )
        return TraceRecordResult(
            step_index=step_index,
            status=status,
            summary=summary,
            trace_path=(self.traces_dir / f"{step_slug}.json").as_posix(),
            snapshot_path=trace_payload["snapshot_path"],
            screenshot_path=trace_payload["screenshot_path"],
            stdout_path=trace_payload["stdout_path"],
            stderr_path=None,
            warnings=warnings,
        )

    def _next_step_index(self) -> int:
        step_numbers: list[int] = []
        for trace_file in self.traces_dir.glob("*.json"):
            prefix = trace_file.stem.split("-", 1)[0]
            if prefix.isdigit():
                step_numbers.append(int(prefix))
        return (max(step_numbers) if step_numbers else 0) + 1

    def _extract_snapshot_text(self, output: str) -> str:
        marker = "### Snapshot"
        if marker not in output:
            return ""
        lines = output.split(marker, 1)[1].strip().splitlines()
        snapshot_lines: list[str] = []
        for line in lines:
            if line.startswith("### "):
                break
            snapshot_lines.append(line)
        return "\n".join(snapshot_lines).strip()

    def _extract_screenshot_path(self, output: str) -> str | None:
        for line in output.splitlines():
            match = re.search(r"saved to\s+(.+\.png)", line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _snapshot_summary(self, snapshot_text: str) -> str:
        if not snapshot_text:
            return ""
        if len(snapshot_text) < INLINE_SNAPSHOT_MAX_CHARS:
            return snapshot_text
        return "Snapshot too large to inline; read the saved artifact if you need the full DOM."
