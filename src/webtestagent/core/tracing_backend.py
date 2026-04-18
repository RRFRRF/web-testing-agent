from __future__ import annotations

from typing import Any
import shlex

from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol

from webtestagent.core.playwright_trace_policy import decide_trace_command


class TracingShellBackend(SandboxBackendProtocol):
    def __init__(self, *, backend: Any, recorder: Any) -> None:
        self._backend = backend
        self._recorder = recorder

    @property
    def id(self) -> str:
        return getattr(self._backend, "id")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def ls(self, path: str):
        return self._backend.ls(path)

    async def als(self, path: str):
        return await self._backend.als(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        return self._backend.read(file_path, offset=offset, limit=limit)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000):
        return await self._backend.aread(file_path, offset=offset, limit=limit)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None):
        return self._backend.grep(pattern, path=path, glob=glob)

    async def agrep(self, pattern: str, path: str | None = None, glob: str | None = None):
        return await self._backend.agrep(pattern, path=path, glob=glob)

    def glob(self, pattern: str, path: str = "/"):
        return self._backend.glob(pattern, path=path)

    async def aglob(self, pattern: str, path: str = "/"):
        return await self._backend.aglob(pattern, path=path)

    def write(self, file_path: str, content: str):
        return self._backend.write(file_path, content)

    async def awrite(self, file_path: str, content: str):
        return await self._backend.awrite(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ):
        return self._backend.edit(
            file_path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ):
        return await self._backend.aedit(
            file_path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    def upload_files(self, files):
        return self._backend.upload_files(files)

    async def aupload_files(self, files):
        return await self._backend.aupload_files(files)

    def download_files(self, paths):
        return self._backend.download_files(paths)

    async def adownload_files(self, paths):
        return await self._backend.adownload_files(paths)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
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
            annotated = f"{response.output.rstrip()}\n\n[{result.summary}]"
            return type(response)(
                output=annotated,
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

    async def aexecute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        response = await self._backend.aexecute(command, timeout=timeout)
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
            annotated = f"{response.output.rstrip()}\n\n[{result.summary}]"
            return type(response)(
                output=annotated,
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
