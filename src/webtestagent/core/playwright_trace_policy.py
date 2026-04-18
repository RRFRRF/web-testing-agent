from __future__ import annotations

from dataclasses import dataclass
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

EXCLUDED_ACTIONS = {
    "snapshot",
    "screenshot",
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


def decide_trace_command(command: str, *, trace_internal: bool = False) -> TraceDecision:
    normalized = command.strip()
    if trace_internal:
        return TraceDecision(False, None, normalized, "internal-trace-command")
    if not normalized:
        return TraceDecision(False, None, normalized, "empty-command")

    try:
        parts = shlex.split(normalized)
    except ValueError:
        return TraceDecision(False, None, normalized, "invalid-command-syntax")

    if parts[:1] == ["playwright-cli"]:
        cli_index = 0
    elif parts[:2] == ["npx", "playwright-cli"]:
        cli_index = 1
    else:
        return TraceDecision(False, None, normalized, "not-playwright-cli")

    command_type = parts[cli_index + 1] if len(parts) > cli_index + 1 else None
    if command_type is None:
        return TraceDecision(False, None, normalized, "missing-subcommand")
    if command_type in EXCLUDED_ACTIONS or command_type.startswith(
        ("cookie-", "localstorage-", "sessionstorage-")
    ):
        return TraceDecision(False, command_type, normalized, "excluded-subcommand")
    if command_type not in WHITELISTED_ACTIONS:
        return TraceDecision(False, command_type, normalized, "non-whitelisted-subcommand")
    return TraceDecision(True, command_type, normalized, "whitelisted-playwright-action")
