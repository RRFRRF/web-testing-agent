from __future__ import annotations

from typing import Any
import shlex

from webtestagent.core.playwright_trace_policy import decide_trace_command


class TracingShellBackend:
    def __init__(self, *, backend: Any, recorder: Any) -> None:
        self._backend = backend
        self._recorder = recorder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def execute(self, command: str, *, timeout: int | None = None):
        response = self._backend.execute(command, timeout=timeout)
        decision = decide_trace_command(command)
        if not decision.should_trace:
            return response

        try:
            screenshot_command = None
            if not decision.is_read_command:
                screenshot_command = lambda file_path: self._run_internal_screenshot(
                    file_path,
                    decision.normalized_command,
                )

            result = self._recorder.record_command_trace(
                phase="action",
                command=decision.normalized_command,
                command_type=decision.command_type or "unknown",
                exit_code=response.exit_code,
                output=response.output,
                screenshot_command=screenshot_command,
                is_read_command=decision.is_read_command,
            )
            return type(response)(
                output=result.summary,
                exit_code=response.exit_code,
                truncated=response.truncated,
            )
        except Exception as exc:
            output = f"{response.output.rstrip()}\n\ntrace warning: {exc}".strip()
            return type(response)(
                output=output,
                exit_code=response.exit_code,
                truncated=response.truncated,
            )

    def _run_internal_screenshot(self, file_path, command: str):
        cli_prefix = self._resolve_cli_prefix(command)
        internal = self._backend.execute(
            f"{cli_prefix} screenshot --filename={file_path.as_posix()}",
            timeout=None,
        )
        return internal.exit_code, internal.output

    def _resolve_cli_prefix(self, command: str) -> str:
        parts = shlex.split(command, posix=False)
        if len(parts) >= 2 and parts[0].lower() == "npx":
            return f"{parts[0]} {parts[1]}"
        return parts[0]
