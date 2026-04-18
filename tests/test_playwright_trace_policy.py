from webtestagent.core.playwright_trace_policy import TraceDecision, decide_trace_command


def test_matches_direct_playwright_click():
    decision = decide_trace_command("playwright-cli click e15")
    assert decision == TraceDecision(
        should_trace=True,
        command_type="click",
        normalized_command="playwright-cli click e15",
        reason="whitelisted-playwright-action",
    )


def test_matches_npx_prefixed_command():
    decision = decide_trace_command('npx playwright-cli type "abc"')
    assert decision.should_trace is True
    assert decision.command_type == "type"
    assert decision.is_read_command is False


def test_traces_snapshot_as_read_command():
    decision = decide_trace_command("playwright-cli snapshot")
    assert decision.should_trace is True
    assert decision.command_type == "snapshot"
    assert decision.reason == "traceable-read-command"
    assert decision.is_read_command is True


def test_traces_screenshot_as_read_command():
    decision = decide_trace_command("playwright-cli screenshot --filename=out.png")
    assert decision.should_trace is True
    assert decision.command_type == "screenshot"
    assert decision.reason == "traceable-read-command"
    assert decision.is_read_command is True


def test_rejects_non_playwright_commands():
    decision = decide_trace_command("python script.py")
    assert decision.should_trace is False
    assert decision.reason == "not-playwright-cli"


def test_rejects_internal_trace_commands():
    decision = decide_trace_command(
        "playwright-cli screenshot --filename=out.png",
        trace_internal=True,
    )
    assert decision.should_trace is False
    assert decision.reason == "internal-trace-command"


def test_rejects_missing_subcommand_for_direct_playwright_cli():
    decision = decide_trace_command("playwright-cli")
    assert decision == TraceDecision(
        should_trace=False,
        command_type=None,
        normalized_command="playwright-cli",
        reason="missing-subcommand",
    )


def test_rejects_missing_subcommand_for_npx_prefixed_playwright_cli():
    decision = decide_trace_command("npx playwright-cli")
    assert decision == TraceDecision(
        should_trace=False,
        command_type=None,
        normalized_command="npx playwright-cli",
        reason="missing-subcommand",
    )


def test_rejects_unclosed_quote_as_invalid_command_syntax():
    decision = decide_trace_command('playwright-cli type "abc')
    assert decision == TraceDecision(
        should_trace=False,
        command_type=None,
        normalized_command='playwright-cli type "abc',
        reason="invalid-command-syntax",
    )


def test_rejects_storage_prefixed_subcommand_with_excluded_reason():
    decision = decide_trace_command("playwright-cli cookie-get session")
    assert decision.should_trace is False
    assert decision.command_type == "cookie-get"
    assert decision.reason == "excluded-subcommand"


def test_rejects_non_whitelisted_subcommand_with_specific_reason():
    decision = decide_trace_command("playwright-cli pdf")
    assert decision.should_trace is False
    assert decision.command_type == "pdf"
    assert decision.reason == "non-whitelisted-subcommand"


def test_matches_full_path_playwright_cli():
    decision = decide_trace_command(
        r"C:\nvm4w\nodejs\playwright-cli.CMD open https://example.com"
    )
    assert decision.should_trace is True
    assert decision.command_type == "open"


def test_matches_unix_path_playwright_cli():
    decision = decide_trace_command(
        "/usr/local/bin/playwright-cli fill input username"
    )
    assert decision.should_trace is True
    assert decision.command_type == "fill"


def test_traces_snapshot_from_full_path_as_read_command():
    decision = decide_trace_command(
        r"C:\nvm4w\nodejs\playwright-cli.CMD snapshot"
    )
    assert decision.should_trace is True
    assert decision.command_type == "snapshot"
    assert decision.reason == "traceable-read-command"
    assert decision.is_read_command is True
