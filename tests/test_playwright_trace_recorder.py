"""测试 core/playwright_trace_recorder.py：trace 产物持久化。"""

from __future__ import annotations

import json
from pathlib import Path

from webtestagent.core.playwright_trace_recorder import PlaywrightTraceRecorder


def _successful_screenshot(path: Path) -> tuple[int, str]:
    path.write_bytes(b"png")
    return 0, f"saved to {path}"


def _make_output_with_snapshot(snapshot_content: str = "button: Search") -> str:
    return (
        "### Page\n- Page URL: https://example.com\n"
        f"### Snapshot\n{snapshot_content}\n"
        "### Result\nDone"
    )


def test_record_action_trace_persists_trace_json_snapshot_and_console(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    result = recorder.record_command_trace(
        phase="action",
        command="playwright-cli click e15",
        command_type="click",
        exit_code=0,
        output=_make_output_with_snapshot("button: Search"),
        screenshot_command=_successful_screenshot,
    )

    assert result.status == "success"
    assert result.trace_path.endswith(".json")
    assert result.snapshot_path is not None
    assert result.screenshot_path is not None
    assert result.stdout_path is not None
    assert result.summary.startswith("playwright trace saved")
    assert len(list((tmp_path / "traces").glob("*.json"))) == 1


def test_record_command_trace_keeps_warning_when_screenshot_fails(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    result = recorder.record_command_trace(
        phase="action",
        command="playwright-cli press Enter",
        command_type="press",
        exit_code=0,
        output="### Snapshot\nsmall snapshot",
        screenshot_command=lambda path: (1, "boom"),
    )

    assert result.status == "partial"
    assert "screenshot failed" in result.warnings[0]


def test_record_command_trace_uses_step_consistent_trace_filename_and_manifest_path(
    tmp_path: Path,
):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    first = recorder.record_command_trace(
        phase="action",
        command="playwright-cli click e15",
        command_type="click",
        exit_code=0,
        output="### Snapshot\nbutton: Search",
        screenshot_command=_successful_screenshot,
    )
    second = recorder.record_command_trace(
        phase="action",
        command="playwright-cli press Enter",
        command_type="press",
        exit_code=0,
        output="### Snapshot\nbutton: Submit",
        screenshot_command=_successful_screenshot,
    )

    assert first.step_index == 1
    assert second.step_index == 2
    assert first.trace_path == (tmp_path / "traces" / "001-action-click.json").as_posix()
    assert second.trace_path == (tmp_path / "traces" / "002-action-press.json").as_posix()

    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert first.trace_path in manifest
    assert second.trace_path in manifest


def test_record_command_trace_stops_snapshot_at_next_markdown_section(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    result = recorder.record_command_trace(
        phase="action",
        command="playwright-cli click e15",
        command_type="click",
        exit_code=0,
        output=(
            "### Page\n- Page URL: https://example.com\n"
            "### Snapshot\nbutton: Search\n"
            "### Console\n- info: done"
        ),
        screenshot_command=_successful_screenshot,
    )

    snapshot_file = Path(result.snapshot_path)
    assert snapshot_file.read_text(encoding="utf-8") == "button: Search"


def test_record_initial_trace_marks_failed_command_output(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    result = recorder.record_command_trace(
        phase="initial",
        command="playwright-cli open https://example.com",
        command_type="open",
        exit_code=1,
        output="cannot open page",
        screenshot_command=lambda path: (1, "skip"),
    )

    assert result.status == "failed"
    assert result.stdout_path is not None


def test_snapshot_and_screenshot_share_step_prefix(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    recorder.record_command_trace(
        phase="action",
        command="playwright-cli click e1",
        command_type="click",
        exit_code=0,
        output=_make_output_with_snapshot("- button [ref=e1]: Submit"),
        screenshot_command=_successful_screenshot,
    )

    snapshot_file = tmp_path / "snapshots" / "001-action-click.yaml"
    screenshot_file = tmp_path / "screenshots" / "001-action-click.png"
    trace_file = tmp_path / "traces" / "001-action-click.json"

    assert snapshot_file.exists()
    assert screenshot_file.exists()
    assert trace_file.exists()
    assert snapshot_file.stem == "001-action-click"
    assert screenshot_file.stem == "001-action-click"
    assert trace_file.stem == "001-action-click"


def test_snapshot_content_is_actual_text_not_link(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    recorder.record_command_trace(
        phase="action",
        command="playwright-cli click e1",
        command_type="click",
        exit_code=0,
        output=_make_output_with_snapshot("- button [ref=e1]: Submit"),
        screenshot_command=_successful_screenshot,
    )

    snapshot_file = tmp_path / "snapshots" / "001-action-click.yaml"
    content = snapshot_file.read_text(encoding="utf-8")
    assert "button [ref=e1]: Submit" in content
    assert "[Snapshot](" not in content


def test_record_snapshot_command_saves_snapshot_only(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    result = recorder.record_command_trace(
        phase="action",
        command="playwright-cli snapshot",
        command_type="snapshot",
        exit_code=0,
        output=_make_output_with_snapshot("- heading [ref=e1]: Welcome"),
        is_read_command=True,
    )

    assert result.status == "success"
    assert result.snapshot_path is not None
    assert result.screenshot_path is None

    snapshot_file = Path(result.snapshot_path.lstrip("/"))
    assert snapshot_file.exists()
    content = snapshot_file.read_text(encoding="utf-8")
    assert "heading [ref=e1]: Welcome" in content


def test_record_screenshot_command_saves_screenshot_only(tmp_path: Path):
    recorder = PlaywrightTraceRecorder(
        run_id="run-1",
        outputs_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
    )

    screenshot_path = tmp_path / "screenshots" / "custom.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"PNG_DATA")

    output = f"Screenshot saved to {screenshot_path}\n### Result\nDone"
    result = recorder.record_command_trace(
        phase="action",
        command=f"playwright-cli screenshot --filename={screenshot_path}",
        command_type="screenshot",
        exit_code=0,
        output=output,
        is_read_command=True,
    )

    assert result.status == "success"
    assert result.screenshot_path is not None
    assert result.snapshot_path is None
