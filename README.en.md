# web-testing-agent

[中文](README.md) | English

A minimal web testing MVP built on Deep Agents. The agent can execute real end-to-end browser tests from either fuzzy scenarios or structured steps, save large artifacts such as snapshots and screenshots to disk, and provide both a CLI workflow and a lightweight local web console.

## Highlights

- Supports **fuzzy scenario descriptions** that the agent can decompose into executable test actions
- Supports **structured test steps** for more deterministic regression-style runs
- Uses a real browser instead of only static reasoning
- `capture_snapshot` automatically:
  - saves the snapshot artifact
  - saves a companion screenshot
  - returns JSON containing both snapshot and screenshot paths
- Other browser interactions intentionally stay on raw `playwright-cli` commands to keep the agent flexible
- All run artifacts are persisted under `outputs/{run_id}/...`
- Includes a local web console for:
  - current scenario
  - live-updating screenshot preview
  - readable execution logs

## Project Layout

```text
.
├─ agent.py               # Builds the Deep Agent: model, backend, skills, tools
├─ browser_tools.py       # Artifact-first snapshot / screenshot helpers
├─ config.py              # Env loading, default URL, scenario/steps loading
├─ main.py                # CLI entry point
├─ output.py              # Stream event normalization and CLI formatting
├─ prompts.py             # System prompt and user prompt templates
├─ runner.py              # Shared run pipeline used by CLI and Web UI
├─ webapp.py              # Local web console backend using Python stdlib
├─ web/
│  └─ index.html          # Console frontend
├─ skills/
│  └─ e2e-test/           # E2E testing methodology skill
├─ scenarios.json         # Default target URL and scenario/steps
└─ outputs/               # Run artifacts (ignored by git)
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js (for `playwright-cli` / `npx playwright-cli`)
- An OpenAI-compatible LLM endpoint

### Required Environment Variables

The project reads these variables via `config.py` and `agent.py`:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Optional variables:

- `TARGET_URL`: default target URL
- `SCENARIO`: default fuzzy scenario
- `STEPS_JSON`: structured test steps in JSON
- `WEBAPP_PORT`: local web console port, default `8765`

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
uv run python main.py
```

This will:

- load the default URL and scenario from `scenarios.json`
- create a new `run_id`
- save artifacts under `outputs/{run_id}/`
- print the final structured test report

### 4. Start the local web console

```bash
uv run python webapp.py
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
uv run python main.py
```

### Pass a target URL

```bash
uv run python main.py --url "https://www.12306.cn/index/"
```

### Pass a fuzzy scenario

```bash
uv run python main.py --url "https://www.12306.cn/index/" --scenario "Test the train ticket search flow from Tianjin to Shanghai, verify that results appear, and proactively report visible issues"
```

### Pass structured steps

```bash
uv run python main.py --scenario '[
  {"type":"Context","text":"Open the 12306 homepage"},
  {"type":"Action","text":"Set departure city to Tianjin"},
  {"type":"Action","text":"Set destination city to Shanghai"},
  {"type":"Outcome","text":"Train results should appear"}
]'
```

### Show full stream events

```bash
uv run python main.py --show-full-events
```

## Web Console

The frontend talks to the backend through HTTP APIs and SSE.

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

The default config file is `scenarios.json`.

Two input styles are supported:

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

Loading priority:

1. CLI `--scenario`
2. `SCENARIO` / `STEPS_JSON`
3. `scenario` in `scenarios.json`
4. `steps` in `scenarios.json`

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
uv run python main.py

# Run CLI with a scenario
uv run python main.py --scenario "Test the login flow"

# Start the web console
uv run python webapp.py
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
