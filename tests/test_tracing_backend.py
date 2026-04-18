from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from deepagents.backends.protocol import SandboxBackendProtocol

from webtestagent.core.tracing_backend import TracingShellBackend


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.id = "fake-backend"

    def ls(self, path: str):
        return f"ls:{path}"

    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        return f"read:{file_path}:{offset}:{limit}"

    def execute(self, command: str, *, timeout: int | None = None):
        self.calls.append((command, timeout))
        return SimpleNamespace(output="### Snapshot\nbutton", exit_code=0, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None):
        return self.execute(command, timeout=timeout)


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
    assert "### Snapshot\nbutton" in response.output
    assert "[trace saved]" in response.output
    assert recorded[0]["command_type"] == "click"
    assert recorded[0]["is_read_command"] is False
    assert recorded[0]["screenshot_command"] is not None


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


def test_internal_screenshot_uses_full_path_prefix(tmp_path):
    backend = FakeBackend()
    tracing_backend = TracingShellBackend(
        backend=backend,
        recorder=SimpleNamespace(record_command_trace=lambda **kwargs: None),
    )

    tracing_backend._run_internal_screenshot(
        Path("shots/screen.png"),
        r"C:\nvm4w\nodejs\playwright-cli.CMD click e3",
    )

    assert backend.calls == [
        (r"C:\nvm4w\nodejs\playwright-cli.CMD screenshot --filename=shots/screen.png", None)
    ]


def test_traces_full_path_playwright_commands(tmp_path):
    recorded = []

    class FakeRecorder:
        def record_command_trace(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(summary="trace saved", warnings=[])

    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=FakeRecorder(),
    )

    response = backend.execute(r"C:\nvm4w\nodejs\playwright-cli.CMD open https://example.com")
    assert "### Snapshot\nbutton" in response.output
    assert "[trace saved]" in response.output
    assert recorded[0]["command_type"] == "open"


def test_snapshot_command_traced_without_extra_screenshot(tmp_path):
    recorded = []

    class FakeRecorder:
        def record_command_trace(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(summary="trace saved", warnings=[])

    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=FakeRecorder(),
    )

    response = backend.execute("playwright-cli snapshot")
    assert "### Snapshot\nbutton" in response.output
    assert "[trace saved]" in response.output
    assert recorded[0]["command_type"] == "snapshot"
    assert recorded[0]["is_read_command"] is True
    assert recorded[0]["screenshot_command"] is None


def test_screenshot_command_traced_without_extra_screenshot(tmp_path):
    recorded = []

    class FakeRecorder:
        def record_command_trace(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(summary="trace saved", warnings=[])

    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=FakeRecorder(),
    )

    response = backend.execute("playwright-cli screenshot --filename=out.png")
    assert "### Snapshot\nbutton" in response.output
    assert "[trace saved]" in response.output
    assert recorded[0]["command_type"] == "screenshot"
    assert recorded[0]["is_read_command"] is True
    assert recorded[0]["screenshot_command"] is None


def test_backend_looks_like_sandbox_backend_protocol():
    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=SimpleNamespace(record_command_trace=lambda **kwargs: None),
    )

    assert backend.id == "fake-backend"
    assert isinstance(backend, SandboxBackendProtocol)


def test_async_execute_traces_playwright_commands():
    recorded = []

    class FakeRecorder:
        def record_command_trace(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(summary="trace saved", warnings=[])

    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=FakeRecorder(),
    )

    response = asyncio.run(backend.aexecute("playwright-cli fill input hello"))
    assert "[trace saved]" in response.output
    assert recorded[0]["command_type"] == "fill"


def test_proxies_ls_to_wrapped_backend():
    backend = TracingShellBackend(
        backend=FakeBackend(),
        recorder=SimpleNamespace(record_command_trace=lambda **kwargs: None),
    )

    assert backend.ls("/skills") == "ls:/skills"
