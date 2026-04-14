# 实施计划：登录态持久化（可复用导入/自动保存）

## Context

项目已完成目录重构，代码组织为 `src/webtestagent/` 分层包结构。当前浏览器登录态没有正式持久化能力：没有测试前自动导入 cookie/storage state，也没有测试后自动保存，因此同一站点反复测试时会重复登录，且无法按站点/账号复用登录态。

本次要补的是**运行级别的登录态持久化**，不是把责任交给 prompt 让 agent"记得去保存"。以 Playwright CLI 已支持的 `state-load` / `state-save` 为主实现，把登录态文件放在项目根 `cookies/` 下，按 **站点 + 账号** 分类。

---

## 方案概述

### 核心思路

1. 以 `state-load` / `state-save` 为主，不以 profile 作为默认方案
2. 在项目根新增 `cookies/` 状态库，按站点与账号分类
3. 新增统一的会话配置模型，与 scenario 分离
4. "自动导入 / 自动保存"做成 runner 前后置，不依赖 agent 决定
5. 适度注入 session 上下文到 prompt，但不把核心逻辑放到 prompt 里
6. manifest 记录脱敏 session 元数据，不暴露真实 cookie 内容

---

## 涉及文件与变更映射

### 新增文件

| 新文件 | 职责 |
|--------|------|
| `src/webtestagent/core/session.py` | **核心新增**：`SessionPersistenceConfig`、`ResolvedSessionState` 数据类、`normalize_site_id()` helper、session 解析/加载/保存逻辑 |
| `cookies/` | 运行时状态库目录（`.gitignore`，不进 git） |
| `docs/session-persistence-plan.md` | 本文档 |

### 修改文件

| 文件 | 变更内容 |
|------|----------|
| [settings.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/settings.py) | 新增 `COOKIES_DIR`、`parse_bool()` |
| [scenarios.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/scenarios.py) | 新增 `load_session_defaults()` 从 `scenarios/default.json` 读取 `session` 块 |
| [runner.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/runner.py) | `prepare_run()` 增加 session 前置导入；`execute_prepared_run()` 增加后置保存；`PreparedRun` 扩展 `session_state` 字段 |
| [artifacts.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/artifacts.py) | `_default_manifest()` 新增顶层 `session` 元数据块 |
| [main.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/cli/main.py) | `parse_args()` 新增 `--auto-load-session` 等 CLI 参数 |
| [user.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/prompts/user.py) | `build_prompt()` 补充 session 上下文说明 |
| [app.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/app.py) | API 扩展：`/api/defaults` 返回 session 默认值；`POST /api/run` 接收 session 配置 |
| [index.html](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html) | 新增表单字段：自动导入/自动保存/账号 |
| [.gitignore](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/.gitignore) | 添加 `cookies/` |
| [default.json](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/scenarios/default.json) | 新增 `session` 块 |

### 参考文件（只读）

| 文件 | 说明 |
|------|------|
| [storage-state.md](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/skills/playwright-cli/references/storage-state.md) | `state-load` / `state-save` 命令参考 |
| [session-management.md](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/skills/playwright-cli/references/session-management.md) | 会话管理参考 |

---

## 详细变更说明

### 1. `cookies/` 状态库结构

```text
cookies/
├── <site_id>/
│   ├── _default/
│   │   ├── state.json       # Playwright storage state
│   │   └── meta.json        # 脱敏元数据
│   └── <account_id>/
│       ├── state.json
│       └── meta.json
```

示例：
- `cookies/12306-cn/alice/state.json`
- `cookies/passport-jd-com/_default/state.json`

`meta.json` 包含：`storage_mode`、`site_id`、`account_id`、`origin_host`、`source_url`、`created_at`、`updated_at`、`last_loaded_at`、`last_run_id`

安全边界：`cookies/` 不进 `outputs/`，不通过 Web 控制台暴露，加入 `.gitignore`。

---

### 2. 新增 `src/webtestagent/core/session.py`

```python
@dataclass
class SessionPersistenceConfig:
    """用户输入层：会话持久化配置。"""
    auto_load: bool = False
    auto_save: bool = False
    site_id: str | None = None
    account_id: str | None = None
    storage_dir: Path | None = None

@dataclass
class ResolvedSessionState:
    """解析后结果：运行时会话状态。"""
    enabled_load: bool
    enabled_save: bool
    storage_mode: str               # 固定为 "state"
    storage_root: Path
    site_id: str
    account_id: str | None
    state_file: Path | None
    meta_file: Path | None
    resolved_by: str                # explicit / auto-single / auto-none / auto-ambiguous
    load_applied: bool

def normalize_site_id(url: str) -> str:
    """URL → site_id 规范化。"""
    # urlparse → hostname → 小写 → 去端口 → 去 www. → . → - → 只保留 [a-z0-9-]
    ...

def resolve_session(config: SessionPersistenceConfig, url: str) -> ResolvedSessionState:
    """解析会话配置 + URL → 运行时状态。"""
    ...

def load_session_state(state: ResolvedSessionState) -> bool:
    """run 前调用 playwright-cli state-load。"""
    ...

def save_session_state(state: ResolvedSessionState, run_id: str) -> bool:
    """run 后调用 playwright-cli state-save + 更新 meta.json。"""
    ...
```

`account_id` 解析规则：
- 显式提供 → 直接使用
- 未提供 → 扫描 `cookies/<site_id>/` 下目录
  - 0 个候选：跳过导入，`resolved_by = "auto-none"`
  - 1 个候选：自动使用，`resolved_by = "auto-single"`
  - 多个候选：歧义跳过，`resolved_by = "auto-ambiguous"`
- 保存时若无明确账号 → 保存到 `_default`

---

### 3. 修改 [settings.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/settings.py)

```python
# 新增
COOKIES_DIR = PROJECT_ROOT / "cookies"

def parse_bool(value: str | None, default: bool = False) -> bool:
    """解析环境变量布尔值。"""
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")
```

---

### 4. 修改 [scenarios.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/scenarios.py)

新增函数：

```python
def load_session_defaults() -> dict[str, Any]:
    """从 scenarios/default.json 读取 session 配置块。"""
    data = _load_scenarios_file()
    return data.get("session", {})
```

---

### 5. 修改 [runner.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/runner.py)

#### `PreparedRun` 扩展

```diff
 @dataclass
 class PreparedRun:
     ...
+    session_state: ResolvedSessionState | None
```

#### `prepare_run()` 增加前置导入

```python
def prepare_run(url, scenario, *, session_config=None, ...):
    ...
    # 现有流程之后
    session_state = None
    if session_config:
        from webtestagent.core.session import resolve_session, load_session_state
        session_state = resolve_session(session_config, url)
        if session_state.enabled_load and session_state.state_file:
            load_session_state(session_state)
        # 注入到 config["context"]
        config["context"]["session_auto_load"] = session_state.enabled_load
        config["context"]["session_auto_save"] = session_state.enabled_save
        config["context"]["session_site_id"] = session_state.site_id
        config["context"]["session_account_id"] = session_state.account_id
    ...
```

#### `execute_prepared_run()` 增加后置保存

```python
def execute_prepared_run(prepared, ...):
    ...
    try:
        # 现有流程
        ...
        return RunResult(...)
    except Exception:
        raise
    finally:
        # 后置保存（成功和失败都尝试）
        if prepared.session_state and prepared.session_state.enabled_save:
            from webtestagent.core.session import save_session_state
            save_session_state(prepared.session_state, prepared.run_context.run_id)
```

---

### 6. 修改 [artifacts.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/artifacts.py)

`_default_manifest()` 新增顶层 `session` 块：

```python
def _default_manifest(*, run_id, target_url=None):
    return {
        "run_id": run_id,
        "created_at": _now_iso(),
        "target_url": target_url or "",
        "session": {                          # 新增
            "site_id": "",
            "account_id": "",
            "storage_mode": "state",
            "auto_load": False,
            "auto_save": False,
            "load": {"attempted": False, "applied": False, "resolved_by": "", "message": ""},
            "save": {"attempted": False, "succeeded": False, "message": ""},
        },
        "artifacts": [],
    }
```

新增 helper：

```python
def update_manifest_session(manifest_path, *, run_id, session_data):
    """更新 manifest 中的 session 元数据。"""
    ...
```

---

### 7. 修改 [main.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/cli/main.py)

```python
def parse_args():
    parser = argparse.ArgumentParser(...)
    # 现有参数...
    # 新增
    parser.add_argument("--auto-load-session", action="store_true")
    parser.add_argument("--auto-save-session", action="store_true")
    parser.add_argument("--session-site-id", help="Override site ID for session storage")
    parser.add_argument("--session-account-id", help="Account identifier for multi-account sites")
    parser.add_argument("--session-dir", help="Override session storage directory")
    return parser.parse_args()

def main():
    ...
    # 构建 session 配置
    from webtestagent.core.session import SessionPersistenceConfig
    session_config = SessionPersistenceConfig(
        auto_load=args.auto_load_session or parse_bool(os.getenv("AUTO_LOAD_SESSION")),
        auto_save=args.auto_save_session or parse_bool(os.getenv("AUTO_SAVE_SESSION")),
        site_id=args.session_site_id or os.getenv("SESSION_SITE_ID"),
        account_id=args.session_account_id or os.getenv("SESSION_ACCOUNT_ID"),
        storage_dir=Path(args.session_dir) if args.session_dir else None,
    )
    prepared = prepare_run(url, scenario, session_config=session_config)
    ...
```

---

### 8. 修改 [user.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/prompts/user.py)

在 `build_prompt()` 末尾可选追加 session 上下文：

```python
def build_prompt(url, scenario, *, outputs_dir, session_state=None):
    ...
    if session_state and session_state.load_applied:
        prompt += f"\n\n注意：本次运行已自动导入站点 {session_state.site_id} 的登录态。如果页面已处于登录状态，请直接继续测试，不需要重新登录。"
    elif session_state and session_state.enabled_save:
        prompt += f"\n\n注意：本次运行结束后将自动保存登录态。如果测试过程中涉及登录操作，可正常执行。"
    return prompt.strip()
```

---

### 9. 修改 [app.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/app.py) 和 [index.html](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html)

#### Web API 扩展

- `GET /api/defaults` 返回增加 `session` 对象
- `POST /api/run` 接收 `session` 配置
- `start_run()` 签名扩展 `session_config` 参数
- `_session_snapshot()` 返回脱敏会话摘要

#### 前端表单扩展

- 自动导入（checkbox）
- 自动保存（checkbox）
- 账号标识（text，可选）
- 高级区域：site_id / storage_dir

安全边界：不新增 `/cookies/` 静态路由，manifest 中的 session 信息只包含脱敏元数据。

---

### 10. 修改 [default.json](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/scenarios/default.json)

新增独立 `session` 块，不污染原有 `scenario/steps`：

```json
{
  "default_url": "...",
  "scenario": "...",
  "steps": [...],
  "session": {
    "auto_load": true,
    "auto_save": true,
    "site_id": null,
    "account_id": null,
    "storage_dir": "cookies"
  }
}
```

---

## 配置优先级

```text
CLI 参数 > 环境变量 > scenarios/default.json session 块 > 默认值
```

环境变量：

| 变量 | 说明 |
|------|------|
| `AUTO_LOAD_SESSION` | 自动导入（`true`/`false`） |
| `AUTO_SAVE_SESSION` | 自动保存（`true`/`false`） |
| `SESSION_SITE_ID` | 站点标识覆盖 |
| `SESSION_ACCOUNT_ID` | 账号标识 |
| `SESSION_DIR` | 状态存储目录覆盖 |

---

## 执行顺序

### Phase A：核心逻辑（不影响已有功能）
1. [settings.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/settings.py) — 新增 `COOKIES_DIR`、`parse_bool()`
2. **[NEW]** `src/webtestagent/core/session.py` — 全部 session 逻辑
3. [artifacts.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/artifacts.py) — manifest 增加 session 块
4. [runner.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/core/runner.py) — 集成 session 前置/后置
5. `.gitignore` — 添加 `cookies/`

### Phase B：配置入口
6. [scenarios.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/config/scenarios.py) — `load_session_defaults()`
7. [main.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/cli/main.py) — CLI 参数扩展
8. [user.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/prompts/user.py) — prompt 注入 session 上下文
9. [default.json](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/scenarios/default.json) — 新增 session 块

### Phase C：Web 控制台
10. [app.py](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/app.py) — API 扩展
11. [index.html](file:///c:/Users/ZhuanZ/Desktop/Projects_China_mobile/mvp-deepagents/src/webtestagent/web/static/index.html) — 前端表单扩展

---

## 验证方案

### 1. 配置与解析

- `normalize_site_id()` 对各种 URL 的规范化结果
- CLI / env / scenarios / Web 的优先级覆盖正确
- 多账号自动查找规则（0 个 / 1 个 / 多个）

### 2. Runner 集成

```bash
# 已有 state.json，自动导入
uv run webtestagent --url "https://www.12306.cn" --auto-load-session

# 首次登录，自动保存
uv run webtestagent --url "https://www.12306.cn" --auto-save-session

# 同时启用
uv run webtestagent --url "https://www.12306.cn" --auto-load-session --auto-save-session

# 指定账号
uv run webtestagent --url "https://www.12306.cn" --auto-load-session --session-account-id alice
```

验证项：
- 已存在 `state.json` 且 `auto_load=True` → run 前成功加载
- 不存在状态文件 → run 不报错，正常继续
- 多账号未指定 → 不自动猜测，manifest 标记 `auto-ambiguous`
- `auto_save=True` → run 结束后写出 `state.json` + `meta.json`
- run 失败时仍尝试保存（`finally` 块）

### 3. Web 控制台

- 表单能看到自动导入/保存开关
- `/api/defaults` 返回 session 默认值
- 页面显示脱敏会话摘要，但访问不到真实 cookie 文件

### 4. 安全

- `/cookies/...` 不可直接静态访问
- manifest / logs 中不出现 cookie 内容
- `cookies/` 已在 `.gitignore` 中
