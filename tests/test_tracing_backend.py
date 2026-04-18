from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from webtestagent.core.tracing_backend import TracingShellBackend


class FakeBackend:
    def __init__(self):
        self.calls = []

    def execute(self, command: str, *, timeout: int | None = None):
        self.calls.append((command, timeout))
        return SimpleNamespace(output="### Snapshot\nbutton", exit_code=0, truncated=False)


def test_traces_matching_playwright_commands_returns_only_summary(tmp_path):
    recorded = []

    class FakeRecorder:
        def record_command_trace(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(summary="trace saved", warnings=[])

    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=FakeRecorder(),
    )

    response = backend.execute("playwright-cli click e3")
    assert response.output == "trace saved"
    assert recorded[0]["command_type"] == "click"


def test_passthrough_non_playwright_commands(tmp_path):
    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=SimpleNamespace(record_command_trace=lambda **kwargs: None),
    )

    response = backend.execute("python script.py")
    assert response.output == "### Snapshot\nbutton"


def test_recorder_failure_does_not_break_original_response(tmp_path):
    class BrokenRecorder:
        def record_command_trace(self, **kwargs):
            raise RuntimeError("trace failed")

    backend = TracingShellBackend(backend=FakeBackend(), recorder=BrokenRecorder())
    response = backend.execute("playwright-cli press Enter")
    assert response.exit_code == 0
    assert "trace warning" in response.output


def test_internal_screenshot_reuses_resolved_cli_prefix(tmp_path):
    backend = FakeBackend()
    tracing_backend = TracingShellBackend(
        backend=backend,
        recorder=SimpleNamespace(record_command_trace=lambda **kwargs: None),
    )

    tracing_backend._run_internal_screenshot(
        Path("shots/screen.png"),
        "npx playwright-cli click e3",
    )

    assert backend.calls == [
        ("npx playwright-cli screenshot --filename=shots/screen.png", None)
    ]
