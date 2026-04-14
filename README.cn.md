# web-testing-agent

中文 | [English](README.md)

一个基于 Deep Agents 的最小化 Web 自动测试 MVP：Agent 能根据模糊场景或结构化步骤，在真实浏览器中执行 E2E 测试，自动把快照/截图等大体量证据落盘，并同时提供 CLI 与本地 Web 控制台两种使用方式。

## 功能特性

- 支持**模糊 scenario 描述**，由 agent 自主拆解测试步骤
- 支持**结构化 steps** 输入，适合稳定回归场景
- 使用真实浏览器执行测试，而不是只做静态分析
- `capture_snapshot` 会自动：
  - 保存 snapshot artifact
  - 额外保存一张配套 screenshot
  - 返回包含 snapshot/screenshot 路径的 JSON
- 其余页面交互默认优先走 `playwright-cli` 原生命令，避免过度封装让 agent 变笨
- 运行产物统一落盘到 `outputs/{run_id}/...`
- 内置本地 Web 控制台，可实时查看：
  - 当前 scenario
  - 最新截图
  - 运行日志

## 项目结构

```text
.
├─ src/webtestagent/          # 主 Python 包
│  ├─ config/                 # 环境变量、路径、场景加载
│  │  ├─ settings.py
│  │  └─ scenarios.py
│  ├─ core/                   # Agent 构建、运行核心、artifacts、运行上下文
│  │  ├─ agent_builder.py
│  │  ├─ runner.py
│  │  ├─ run_context.py
│  │  └─ artifacts.py
│  ├─ tools/                  # 浏览器工具封装
│  │  └─ browser_tools.py
│  ├─ prompts/                # system prompt 与 user prompt 定义
│  │  ├─ system.py
│  │  └─ user.py
│  ├─ middleware/             # LangChain 消息归一化中间件
│  │  └─ message_normalizer.py
│  ├─ output/                 # 流式事件解析与 CLI 格式化
│  │  ├─ formatters.py
│  │  └─ stream.py
│  ├─ cli/                    # CLI 入口
│  │  └─ main.py
│  └─ web/                    # 本地 Web 控制台
│     ├─ app.py
│     └─ static/index.html
├─ skills/                    # Agent 技能（e2e-test, playwright-cli）
├─ scenarios/                 # 场景配置文件
│  └─ default.json
├─ tests/                     # 测试目录（进行中）
└─ outputs/                   # 每次运行的 artifacts（已被 git 忽略）
```

## 运行要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js（用于 `playwright-cli` / `npx playwright-cli`）
- 可用的大模型兼容接口

### 必需环境变量

项目通过 `webtestagent.config.settings` / `webtestagent.core.agent_builder` 读取以下变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

可选变量：

- `TARGET_URL`：默认测试 URL
- `SCENARIO`：默认模糊场景
- `STEPS_JSON`：结构化步骤 JSON
- `WEBAPP_PORT`：Web 控制台端口，默认 `8765`

建议在项目根目录创建 `.env`：

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://your-compatible-endpoint/v1
OPENAI_MODEL=gpt-4.1
```

## Quickstart

### 1. 安装依赖

```bash
uv sync
```

### 2. 确保 playwright-cli 可用

项目会优先查找：

1. 全局 `playwright-cli`
2. 或 `npx playwright-cli`

如果未安装，可按你本地环境准备 Node 工具链后安装对应 CLI。

### 3. 运行一次默认测试（CLI）

```bash
uv run webtestagent
```

这会：

- 从 `scenarios/default.json` 读取默认 URL 和默认场景
- 创建新的 `run_id`
- 在 `outputs/{run_id}/` 下保存所有 artifacts
- 最后输出结构化测试报告

### 4. 启动本地 Web 控制台

```bash
uv run webtestagent-web
```

然后打开：

```text
http://127.0.0.1:8765
```

控制台当前采用最小三栏布局：

- 左侧：scenario / URL / 运行状态
- 中间：实时更新的最新 screenshot
- 右侧：更适合人看的运行日志

## CLI 用法

### 使用默认配置

```bash
uv run webtestagent
```

### 指定 URL

```bash
uv run webtestagent --url "https://www.12306.cn/index/"
```

### 传入模糊场景

```bash
uv run webtestagent --url "https://www.12306.cn/index/" --scenario "测试从天津到上海的购票查询流程，验证是否出现车次结果，并主动发现页面异常"
```

### 传入结构化步骤

```bash
uv run webtestagent --scenario '[
  {"type":"Context","text":"我打开 12306 首页"},
  {"type":"Action","text":"将出发地选择为天津"},
  {"type":"Action","text":"将目的地选择为上海"},
  {"type":"Outcome","text":"应出现车次搜索结果"}
]'
```

### 查看完整流式事件

```bash
uv run webtestagent --show-full-events
```

## Web 控制台用法

启动后，前端会通过 HTTP API + SSE 与后端通信。

主要能力：

- 发起新的测试 run
- 实时查看当前 run 的事件流
- 自动刷新最新 screenshot
- 读取 `outputs/{run_id}/manifest.json` 与 `report.md`

主要后端接口包括：

- `GET /api/defaults`
- `POST /api/run`
- `GET /api/runs`
- `GET /api/runs/{run_id}/manifest`
- `GET /api/runs/{run_id}/report`
- `GET /api/run/{run_id}/stream`
- `GET /outputs/...`

## Scenario 配置

默认配置文件是 `scenarios/default.json`。

当前支持两种输入模式：

### 1. 模糊场景描述

```json
{
  "default_url": "https://www.12306.cn/index/",
  "scenario": "测试从天津到上海的购票查询流程：选择出发地天津、目的地上海、出发日期明天，点击查询，验证是否出现车次结果"
}
```

### 2. 结构化步骤

```json
{
  "steps": [
    {"type": "Context", "text": "我打开 12306 首页"},
    {"type": "Action", "text": "将出发地选择为天津"},
    {"type": "Action", "text": "将目的地选择为上海"},
    {"type": "Outcome", "text": "页面应出现车次搜索结果"}
  ]
}
```

加载优先级如下：

1. CLI `--scenario`
2. 环境变量 `SCENARIO` / `STEPS_JSON`
3. `scenarios/default.json` 中的 `scenario`
4. `scenarios/default.json` 中的 `steps`

## Artifact 设计

所有运行产物会保存到：

```text
outputs/{run_id}/
```

典型目录结构：

```text
outputs/run-20260413-xxxx/
├─ manifest.json
├─ report.md
├─ snapshots/
├─ screenshots/
├─ console/
└─ network/
```

设计目标：

- 大结果优先落盘，不把超长 snapshot 直接塞进模型上下文
- Agent 只保留轻量摘要与路径
- 真正需要细节时，再通过文件系统工具读取 artifact

## Browser tools 约束

本项目刻意将自定义 browser tools 收窄到最小范围。

当前只保留：

- `capture_snapshot`
- `capture_screenshot`

其中：

- `capture_snapshot`：采集页面结构快照，并自动再截一张图
- `capture_screenshot`：只有 agent 判断需要额外截图时才调用
- 打开页面、点击、输入、选择等行为，默认优先使用 `playwright-cli` 原生命令

这样做的目的是：

- 保留交互灵活性
- 减少不必要封装
- 只在真正会撑爆上下文的证据采集环节做定制

## 12306 特殊策略

针对 12306 城市联想框，当前 prompt 与 skill 明确约束：

- 默认优先鼠标点击候选项
- 不默认使用 `Enter`
- 不默认使用 `ArrowDown + Enter`
- 对复杂联想框采用：聚焦 → 输入 → 立即抓取 → 点击候选 → 再验证 的节奏

这是为了避免出现“天津被误选成北京北”之类的问题。

## 常见命令

```bash
# CLI 默认运行
uv run webtestagent

# CLI 指定场景
uv run webtestagent --scenario "测试登录流程"

# 启动 Web 控制台
uv run webtestagent-web
```

## 当前实现说明

这是一个偏 MVP 的实现，重点在于：

- 验证 Deep Agents + 本地技能 + Playwright CLI 的组合形态
- 验证“文件系统优先”的 artifact 管理方式
- 验证在 Web 控制台中实时观察 agent 执行过程的最小可行方案

因此目前更偏向：

- 本地运行
- 单机调试
- 最小依赖
- 易于继续迭代

## License

MIT
