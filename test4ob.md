# OneBase 场景编写与 CLI 回归教程

本文面向需要在 OneBase 上手动编写自动化用例的同学，目标是让大家能够：

1. 配好本地运行环境；
2. 首次登录并保存 session；
3. 手写自己的 scenario JSON；
4. 通过 CLI 自动加载 session，反复执行自己写的场景；
5. 重点验证 OneBase 上常见自动化流程是否可执行，例如：表单填写、表项删除、搜索、基础页面流转。

---

## 1. 适用场景

这套流程适合验证 OneBase 上这类页面操作是否能稳定自动化：

- 新增/编辑表单并提交
- 删除某条测试数据
- 搜索、筛选、切换列表
- 打开详情页再返回列表
- 多步页面流转后校验结果

不建议直接拿生产敏感数据做删除或写入测试。优先准备测试账号、测试环境、测试数据。

---

## 2. 环境准备

### 2.1 安装基础依赖

需要具备：

- Python 3.11+
- `uv`
- Node.js
- 可用的 `playwright-cli`，或可通过 `npx playwright-cli` 调用

安装 Python 依赖：

```bash
uv sync
```

### 2.2 配置 `.env`

在项目根目录创建 `.env`：

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://your-compatible-endpoint/v1
OPENAI_MODEL=gpt-4.1
```

这 3 个变量是必需的。

常用可选变量：

```bash
TARGET_URL=https://your-onebase.example.com
SCENARIO=验证首页加载
STEPS_JSON=[{"type":"Action","text":"点击查询"}]
AUTO_LOAD_SESSION=false
AUTO_SAVE_SESSION=false
SESSION_SITE_ID=onebase-test
SESSION_ACCOUNT_ID=test-user
```

说明：

- `TARGET_URL`：默认目标地址
- `SCENARIO`：默认自然语言场景
- `STEPS_JSON`：默认结构化步骤 JSON
- `AUTO_LOAD_SESSION` / `AUTO_SAVE_SESSION`：默认 session 行为
- `SESSION_SITE_ID` / `SESSION_ACCOUNT_ID`：session 存储命名

如果你需要覆盖 session 存储目录，当前代码支持的是 CLI 参数 `--session-dir`，不是环境变量。

### 2.3 检查 CLI 是否可用

```bash
uv run webtestagent --help
```

如果命令能正常输出帮助信息，说明 CLI 已可用。

---

## 3. 首次登录并保存 session

首次运行的目标不是做完整回归，而是把 OneBase 的登录态保存下来，供后续自动化场景复用。

推荐第一次运行时：

- 使用明确的目标 URL
- 开启 `--auto-save-session`
- 显式指定 `--session-site-id`
- 显式指定 `--session-account-id`

示例：

```bash
uv run webtestagent \
  --url "https://www.12306.cn/index/【改为onebase的url】" \
  --scenario "打开页面 执行登录 自动填写账号{}密码{}验证码基于截图自动填写，然后退出" \
  --auto-save-session \
  --session-site-id onebase-test \
  --session-account-id zhangsan
```

运行完成后，登录态会保存在：

```text
cookies/onebase-test/zhangsan/state.json
cookies/onebase-test/zhangsan/meta.json
```

后续只要继续使用同一个：

- `session-site-id`
- `session-account-id`

就可以自动复用这份 session。

---

## 4. 编写自己的 scenario JSON

## 4.1 推荐格式

虽然代码同时支持：

- `scenario`: 自然语言描述
- `steps`: 结构化步骤数组

但对于 OneBase 手写用例，**推荐统一写成 `url + steps`**，因为表单填写、删除、搜索这类流程更适合精确描述。

推荐文件结构：

```json
{
  "url": "https://your-onebase.example.com/app/orders",
  "steps": [
    {"type": "Context", "text": "我已经进入订单管理页面"},
    {"type": "Action", "text": "在搜索框输入测试订单号 OB-001 并执行搜索"},
    {"type": "Action", "text": "打开搜索结果中的第一条记录详情"},
    {"type": "Outcome", "text": "页面应显示该订单的详情信息"}
  ]
}
```

### 4.2 必填字段要求

scenario 文件顶层必须是一个 JSON object。

至少满足下面二选一：

- 提供非空 `scenario`
- 提供非空 `steps`

如果使用 `steps`，每个步骤至少包含：

- `type`
- `text`

例如：

```json
{"type": "Action", "text": "点击搜索按钮"}
```

### 4.3 `type` 怎么写

建议沿用这三类：

- `Context`：上下文说明
- `Action`：执行动作
- `Outcome`：预期结果

示例：

```json
[
  {"type": "Context", "text": "我已进入商品列表页"},
  {"type": "Action", "text": "在关键字输入框中输入测试商品"},
  {"type": "Action", "text": "点击搜索按钮"},
  {"type": "Outcome", "text": "列表中应出现名称包含测试商品的记录"}
]
```

### 4.4 支持 `{today}` 占位符

如果你的场景里需要当天日期，可以直接写 `{today}`：

```json
{
  "url": "https://your-onebase.example.com/app/form",
  "steps": [
    {"type": "Action", "text": "将申请日期填写为 {today}"},
    {"type": "Outcome", "text": "表单中显示今天的日期"}
  ]
}
```

运行时会自动替换成当天日期，例如 `2026-04-15`。

---

## 5. OneBase 场景示例

下面给一个更完整的示例，适合验证“搜索 + 编辑表单 + 删除测试数据”这类自动化流程。

文件：`scenarios/onebase-order-check.json`

```json
{
  "url": "https://your-onebase.example.com/app/orders",
  "steps": [
    {"type": "Context", "text": "我已登录 OneBase，并进入订单管理页面"},
    {"type": "Action", "text": "在搜索框输入订单号 OB-TEST-001 并点击搜索"},
    {"type": "Outcome", "text": "列表中应出现订单号为 OB-TEST-001 的记录"},

    {"type": "Action", "text": "打开该记录的编辑页面"},
    {"type": "Action", "text": "将备注字段修改为 自动化回归 {today}"},
    {"type": "Action", "text": "点击保存按钮"},
    {"type": "Outcome", "text": "页面应提示保存成功，且备注字段显示最新内容"},

    {"type": "Action", "text": "返回列表并删除订单号为 OB-TEST-001 的测试数据"},
    {"type": "Outcome", "text": "页面应提示删除成功，列表中不再出现该记录"}
  ]
}
```

建议：

- 删除动作只针对测试数据
- 搜索关键字尽量唯一，避免误删
- 表单字段名、按钮文案、页面名尽量写明确

---

## 6. 使用 CLI 跑自己写的场景

现在 CLI 已支持 `--scenario-path`，可以直接传入一个 JSON scenario 文件。

### 6.1 使用文件中的 URL

```bash
uv run webtestagent \
  --scenario-path "scenarios/onebase-order-check.json" \
  --auto-load-session \
  --session-site-id onebase-test \
  --session-account-id zhangsan
```

这条命令会：

- 读取 `scenarios/onebase-order-check.json`
- 自动加载 `cookies/onebase-test/zhangsan/state.json`
- 执行你手写的 steps

### 6.2 用 `--url` 覆盖文件里的 URL

如果同一份场景要在不同环境复用，可以在命令行覆盖：

```bash
uv run webtestagent \
  --url "https://your-onebase-staging.example.com/app/orders" \
  --scenario-path "scenarios/onebase-order-check.json" \
  --auto-load-session \
  --session-site-id onebase-staging \
  --session-account-id zhangsan
```

当前 URL 优先级为：

1. `--url`
2. scenario 文件中的 `url` / `default_url`
3. 环境变量 `TARGET_URL`
4. `scenarios/default.json` 中的默认 URL

### 6.3 不用 scenario 文件，直接跑自然语言

如果只是快速试验，也可以继续用原来的方式：

```bash
uv run webtestagent \
  --url "https://your-onebase.example.com" \
  --scenario "打开列表页，搜索测试数据，验证结果正常显示"
```

但正式给同学协作编写回归用例时，仍然建议优先使用 `--scenario-path`。

---

## 7. 怎么看运行结果

每次执行后，产物会写到：

```text
outputs/{run_id}/
```

重点看这几个文件：

```text
outputs/{run_id}/report.md
outputs/{run_id}/manifest.json
outputs/{run_id}/screenshots/
outputs/{run_id}/snapshots/
```

其中：

- `report.md`：最终测试报告
- `manifest.json`：本次运行的 artifact 索引
- `screenshots/`：截图证据
- `snapshots/`：页面结构快照

如果你要回看某次执行到底做了什么，优先看：

1. 终端输出
2. `report.md`
3. 截图和 snapshot

---

## 8. 常见问题

### 8.1 session 没生效

优先检查：

- 是否开启了 `--auto-load-session`
- `--session-site-id` 是否和首次保存时一致
- `--session-account-id` 是否和首次保存时一致
- `cookies/{site_id}/{account_id}/state.json` 是否存在

### 8.2 session 过期了

很多站点登录态会过期。过期后重新执行一次“登录并保存 session”的命令即可。

### 8.3 场景文件报错

常见原因：

- 顶层不是 JSON object
- 没有 `scenario`，也没有 `steps`
- `steps` 是空数组
- 某个 step 缺少 `type` 或 `text`

建议先用最小场景验证，再逐步加步骤。

### 8.4 删除类操作有风险

删除、批量修改、提交审批这类动作，只能针对测试环境或测试数据执行。

不要把模糊描述写成：

- 删除无用数据
- 清理异常记录
- 处理全部待办

应写成精确目标，例如：

- 删除订单号为 `OB-TEST-001` 的测试记录
- 删除标题为 `自动化验证数据` 的草稿记录

---

## 9. 推荐协作方式

如果你要组织同学一起补 OneBase 用例，建议统一约定：

1. 每个业务页面一个 scenario 文件
2. 文件统一放在 `scenarios/` 目录
3. 默认使用 `url + steps`
4. 删除/修改步骤必须明确指向测试数据
5. 每个场景都至少写一个明确的 `Outcome`

这样后续复跑、排查、补充证据都会简单很多。

---

## 10. 最小工作流总结

### 第一次：登录并保存 session

```bash
uv run webtestagent \
  --url "https://your-onebase.example.com" \
  --scenario "打开 OneBase，完成登录并进入首页，确认页面已处于可操作状态" \
  --auto-save-session \
  --session-site-id onebase-test \
  --session-account-id zhangsan
```

### 第二次开始：复用 session 跑手写场景

```bash
uv run webtestagent \
  --scenario-path "scenarios/onebase-order-check.json" \
  --auto-load-session \
  --session-site-id onebase-test \
  --session-account-id zhangsan
```

如果希望一次执行后继续刷新登录态，也可以同时加上：

```bash
--auto-save-session
```

这样就能形成一个稳定流程：

- 首次登录保存 session
- 后续自动加载 session
- 使用 `--scenario-path` 反复跑手写 JSON 用例
- 查看 `outputs/{run_id}` 下的报告、截图和快照
