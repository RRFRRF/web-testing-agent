# web-testing-agent

[中文](README.cn.md) | English

A minimal web testing MVP built on Deep Agents. The agent can execute real end-to-end browser tests from either fuzzy scenarios or structured steps, save large artifacts such as snapshots and screenshots to disk, reuse browser login state across runs via Playwright storage state, and provide both a CLI workflow and a lightweight local web console.

## Highlights

- Supports **fuzzy scenario descriptions** that the agent can decompose into executable test actions
- Supports **structured test steps** for more deterministic regression-style runs
- Uses a real browser instead of only static reasoning
- `capture_snapshot` automatically:
  - saves the snapshot artifact
  - saves a companion screenshot
  - returns JSON containing both snapshot and screenshot paths
- Other browser interactions intentionally stay on raw `playwright-cli` commands to keep the agent flexible
- Supports **session persistence** via `playwright-cli state-load` / `state-save`
- Reused browser state is stored under `cookies/{site_id}/{account_id}/state.json` and is intentionally kept out of `outputs/`
- All run artifacts are persisted under `outputs/{run_id}/...`
- Includes a local web console for:
  - current scenario
  - live-updating screenshot preview
  - readable execution logs

## Project Layout

```text
.
├─ src/webtestagent/          # Main Python package
│  ├─ config/                 # Env loading, paths, scenario/steps loading
│  │  ├─ settings.py
│  │  └─ scenarios.py
│  ├─ core/                   # Agent builder, run pipeline, artifacts, run context, session persistence
│  │  ├─ agent_builder.py
│  │  ├─ runner.py
│  │  ├─ run_context.py
│  │  ├─ artifacts.py
│  │  └─ session.py
│  ├─ tools/                  # Browser tool wrappers
│  │  └─ browser_tools.py
│  ├─ prompts/                # System and user prompt definitions
│  │  ├─ system.py
│  │  └─ user.py
│  ├─ middleware/             # LangChain message normalization
│  │  └─ message_normalizer.py
│  ├─ output/                 # Stream event parsing and CLI formatting
│  │  ├─ formatters.py
│  │  └─ stream.py
│  ├─ cli/                    # CLI entry point
│  │  └─ main.py
│  └─ web/                    # Local web console
│     ├─ app.py
│     └─ static/index.html
├─ skills/                    # Agent skills (e2e-test, playwright-cli)
├─ scenarios/                 # Scenario config files
│  └─ default.json
├─ tests/                     # Test suite (in progress)
├─ cookies/                   # Reusable Playwright storage state (ignored by git)
└─ outputs/                   # Run artifacts (ignored by git)
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js (for `playwright-cli` / `npx playwright-cli`)
- An OpenAI-compatible LLM endpoint

### Required Environment Variables

The project reads these variables via `webtestagent.config.settings` and `webtestagent.core.agent_builder`:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Optional variables:

- `TARGET_URL`: default target URL
- `SCENARIO`: default fuzzy scenario
- `STEPS_JSON`: structured test steps in JSON
- `WEBAPP_PORT`: local web console port, default `8765`
- `AUTO_LOAD_SESSION`: auto-load saved browser state before run
- `AUTO_SAVE_SESSION`: auto-save browser state after run
- `SESSION_SITE_ID`: override the derived site identifier for session storage
- `SESSION_ACCOUNT_ID`: account identifier for multi-account sites

If you need to override the session storage directory, use the CLI flag `--session-dir`.

Recommended `.env` file in the project root:

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://your-compatible-endpoint/v1
OPENAI_MODEL=gpt-4.1
```

## Quickstart

### 1. Install dependencies

```bash
uv sync
```

### 2. Make sure `playwright-cli` is available

The project will try:

1. global `playwright-cli`
2. or `npx playwright-cli`

If neither is available, install the Playwright CLI through your local Node.js toolchain.

### 3. Run the default test from the CLI

```bash
uv run webtestagent
```

This will:

- load the default URL and scenario from `scenarios/default.json`
- create a new `run_id`
- save artifacts under `outputs/{run_id}/`
- print the final structured test report

### 4. Start the local web console

```bash
uv run webtestagent-web
```

Then open:

```text
http://127.0.0.1:8765
```

The console uses a minimal three-panel layout:

- left: scenario / URL / run status
- center: latest screenshot preview
- right: readable execution logs

## CLI Usage

### Run with defaults

```bash
uv run webtestagent
```

### Pass a target URL

```bash
uv run webtestagent --url "https://www.12306.cn/index/"
```

### Pass a fuzzy scenario

```bash
uv run webtestagent --url "https://www.12306.cn/index/" --scenario "Test the train ticket search flow from Tianjin to Shanghai, verify that results appear, and proactively report visible issues"
```

### Pass structured steps inline

```bash
uv run webtestagent --scenario '[
  {"type":"Context","text":"Open the 12306 homepage"},
  {"type":"Action","text":"Set departure city to Tianjin"},
  {"type":"Action","text":"Set destination city to Shanghai"},
  {"type":"Outcome","text":"Train results should appear"}
]'
```

### Pass a scenario JSON file

```bash
uv run webtestagent --scenario-path "scenarios/onebase-order-check.json"
```

The scenario file must be a JSON object and contain at least one of:

- `scenario`: non-empty string
- `steps`: non-empty array

It may also include:

- `url`
- `default_url`

For a teammate-oriented OneBase workflow tutorial, see [`test4ob.md`](test4ob.md).

### Session persistence

```bash
# Save browser state after the run
uv run webtestagent --url "https://www.12306.cn/index/" --auto-save-session
```

```bash
# Load a previously saved browser state before the run
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session
```

```bash
# Load and save in the same run
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session --auto-save-session
```

```bash
# Specify account id for multi-account sites
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session --session-account-id alice
```

The session state is stored outside `outputs/` under:

```text
cookies/{site_id}/{account_id}/state.json
cookies/{site_id}/{account_id}/meta.json
```

Resolution priority for session settings:

1. CLI flags such as `--auto-load-session`
2. Environment variables such as `AUTO_LOAD_SESSION`
3. `session` block in `scenarios/default.json`
4. Built-in defaults

## Web Console

Main capabilities:

- start a new test run
- stream live run events
- refresh the latest screenshot automatically
- read `outputs/{run_id}/manifest.json` and `report.md`

Main endpoints:

- `GET /api/defaults`
- `POST /api/run`
- `GET /api/runs`
- `GET /api/runs/{run_id}/manifest`
- `GET /api/runs/{run_id}/report`
- `GET /api/run/{run_id}/stream`
- `GET /outputs/...`

## Scenario Configuration

The default config file is `scenarios/default.json`.

Current input styles:

### 1. Fuzzy scenario

```json
{
  "default_url": "https://www.12306.cn/index/",
  "scenario": "Test the ticket search flow from Tianjin to Shanghai: select Tianjin as departure, Shanghai as destination, choose tomorrow as the departure date, click search, and verify that train results appear"
}
```

### 2. Structured steps

```json
{
  "steps": [
    {"type": "Context", "text": "Open the 12306 homepage"},
    {"type": "Action", "text": "Set departure city to Tianjin"},
    {"type": "Action", "text": "Set destination city to Shanghai"},
    {"type": "Outcome", "text": "Train results should appear"}
  ]
}
```

### 3. External scenario file for `--scenario-path`

```json
{
  "url": "https://your-onebase.example.com/app/orders",
  "steps": [
    {"type": "Context", "text": "I am on the order management page"},
    {"type": "Action", "text": "Search for order OB-001"},
    {"type": "Outcome", "text": "The matching record should appear in the list"}
  ]
}
```

Scenario file rules:

- top level must be a JSON object
- must contain non-empty `scenario` or non-empty `steps`
- if `steps` is used, every item must contain non-empty `type` and `text`
- `{today}` placeholders are supported in both `scenario` and `steps[*].text`

Loading priority for scenario content:

1. CLI `--scenario-path`
2. CLI `--scenario`
3. `SCENARIO` / `STEPS_JSON` env vars
4. `scenario` in `scenarios/default.json`
5. `steps` in `scenarios/default.json`

URL priority:

1. CLI `--url`
2. scenario file `url` / `default_url`
3. `TARGET_URL`
4. `scenarios/default.json`

## Artifact Strategy

All run artifacts are saved under:

```text
outputs/{run_id}/
```

Typical structure:

```text
outputs/run-20260413-xxxx/
├─ manifest.json
├─ report.md
├─ snapshots/
├─ screenshots/
├─ console/
└─ network/
```

Design goals:

- keep large outputs on disk instead of stuffing raw snapshots into model context
- preserve only lightweight summaries and file paths in active context
- let the agent read raw artifact files only when needed

## Browser Tool Scope

This project intentionally keeps custom browser tools minimal.

Currently only:

- `capture_snapshot`
- `capture_screenshot`

Behavior:

- `capture_snapshot`: captures a page snapshot and automatically saves an additional screenshot
- `capture_screenshot`: used only when the agent decides an extra screenshot is helpful
- page open / click / type / select actions should generally stay on native `playwright-cli` commands

Why:

- keeps browser interactions flexible
- avoids unnecessary abstractions
- customizes only the artifact-heavy steps that would otherwise bloat context

## Session Persistence (Login State Reuse)

The project supports **run-level login state persistence** via Playwright CLI's `state-load` / `state-save`. This lets you log in once and reuse the session across multiple runs, without relying on the agent to manually save cookies.

### How It Works

- **Before run**: if `--auto-load-session` is set and a saved state exists, `playwright-cli state-load` is called automatically
- **After run**: if `--auto-save-session` is set, `playwright-cli state-save` is called automatically (even if the run fails)
- The agent is informed via prompt context, but does **not** control the load/save logic itself

### Cookies Directory

Login states are stored under `cookies/` (ignored by git):

```text
cookies/
├── <site_id>/
│   ├── _default/
│   │   ├── state.json       # Playwright storage state
│   │   └── meta.json        # Desensitized metadata
│   └── <account_id>/
│       ├── state.json
│       └── meta.json
```

`site_id` is derived from the URL automatically (e.g. `https://www.12306.cn/` → `12306-cn`), or overridden with `--session-site-id`.

`meta.json` contains: `storage_mode`, `site_id`, `account_id`, `created_at`, `updated_at`, `last_loaded_at`, `last_run_id`.

### CLI Flags

| Flag | Description |
|------|-------------|
| `--auto-load-session` | Auto-load saved login state before run |
| `--auto-save-session` | Auto-save login state after run |
| `--session-site-id` | Override site ID (default: derived from URL) |
| `--session-account-id` | Account identifier for multi-account sites |
| `--session-dir` | Override cookies directory |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AUTO_LOAD_SESSION` | `true`/`false` |
| `AUTO_SAVE_SESSION` | `true`/`false` |
| `SESSION_SITE_ID` | Override site ID |
| `SESSION_ACCOUNT_ID` | Account identifier |

Priority: CLI flags > env vars > `scenarios/default.json` session block > defaults.

### Example Commands

```bash
# First run: log in and auto-save the session
uv run webtestagent --url "https://www.12306.cn/index/" --auto-save-session

# Later runs: auto-load the saved session (skip login)
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session

# Both: load if available, save after run
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session --auto-save-session

# Multi-account: specify which account to use
uv run webtestagent --url "https://www.12306.cn/index/" --auto-load-session --session-account-id alice
```

### Account Auto-Discovery

When `--session-account-id` is not specified:

- **0 accounts** found → skip load, save to `_default`
- **1 account** found → auto-use that account
- **Multiple accounts** found → skip load (ambiguous), log warning, save to `_default`

### Web Console

The web console includes a collapsible "Session Persistence" section with:

- Auto-load / auto-save checkboxes
- Account ID input

The `/api/defaults` endpoint returns session defaults from `scenarios/default.json`.

### Security

- `cookies/` is in `.gitignore` and never served via the web console
- Manifest records only desensitized session metadata (site, account, load/save status)
- Raw cookie content is never exposed through API or static routes

## Special Handling for 12306

For the 12306 city autocomplete flow, the prompt and skill explicitly enforce:

- prefer clicking candidate items with the mouse
- do not use `Enter` by default
- do not use `ArrowDown + Enter` by default
- use a staged pattern for complex autocomplete widgets: focus → type → capture → click candidate → verify again

This helps avoid issues such as Tianjin being mistakenly rewritten as Beijing North.

## Common Commands

```bash
# Run default CLI flow
uv run webtestagent

# Run CLI with a scenario
uv run webtestagent --scenario "Test the login flow"

# Start the web console
uv run webtestagent-web
```

## Project Status

This is still an MVP-oriented implementation. The focus is on validating:

- the Deep Agents + local skills + Playwright CLI setup
- an artifact-first filesystem workflow
- a minimal local web console for observing agent execution in real time

So the project is currently optimized for:

- local development
- single-machine debugging
- minimal dependencies
- easy iteration

## License

MIT
