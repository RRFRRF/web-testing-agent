from __future__ import annotations

from dataclasses import dataclass
import os
import shlex

WHITELISTED_ACTIONS = {
    "open",
    "goto",
    "click",
    "dblclick",
    "type",
    "fill",
    "press",
    "hover",
    "drag",
    "select",
    "check",
    "uncheck",
    "go-back",
    "go-forward",
    "reload",
}

TRACEABLE_READ_COMMANDS = {
    "snapshot",
    "screenshot",
}

EXCLUDED_ACTIONS = {
    "eval",
    "console",
    "network",
    "tab-list",
}


@dataclass(frozen=True)
class TraceDecision:
    should_trace: bool
    command_type: str | None
    normalized_command: str
    reason: str
    is_read_command: bool = False


def _is_playwright_cli_part(part: str) -> bool:
    basename = os.path.basename(part).lower()
    return basename in ("playwright-cli", "playwright-cli.cmd")


def _find_cli_index(parts: list[str]) -> int | None:
    if not parts:
        return None
    if _is_playwright_cli_part(parts[0]):
        return 0
    if len(parts) >= 2 and parts[0].lower() == "npx" and _is_playwright_cli_part(parts[1]):
        return 1
    return None


def decide_trace_command(command: str, *, trace_internal: bool = False) -> TraceDecision:
    normalized = command.strip()
    if trace_internal:
        return TraceDecision(False, None, normalized, "internal-trace-command")
    if not normalized:
        return TraceDecision(False, None, normalized, "empty-command")

    try:
        parts = shlex.split(normalized, posix=False)
    except ValueError:
        return TraceDecision(False, None, normalized, "invalid-command-syntax")

    cli_index = _find_cli_index(parts)
    if cli_index is None:
        return TraceDecision(False, None, normalized, "not-playwright-cli")

    command_type = parts[cli_index + 1] if len(parts) > cli_index + 1 else None
    if command_type is None:
        return TraceDecision(False, None, normalized, "missing-subcommand")
    if command_type in EXCLUDED_ACTIONS or command_type.startswith(
        ("cookie-", "localstorage-", "sessionstorage-")
    ):
        return TraceDecision(False, command_type, normalized, "excluded-subcommand")
    if command_type in TRACEABLE_READ_COMMANDS:
        return TraceDecision(
            True, command_type, normalized, "traceable-read-command", is_read_command=True
        )
    if command_type not in WHITELISTED_ACTIONS:
        return TraceDecision(False, command_type, normalized, "non-whitelisted-subcommand")
    return TraceDecision(True, command_type, normalized, "whitelisted-playwright-action")
