"""登录态持久化：session 解析、加载、保存。

基于 playwright-cli 的 state-load / state-save 实现，
按站点+账号分类管理登录态文件。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from webtestagent.config.settings import COOKIES_DIR, now_iso


# ── 数据类 ────────────────────────────────────────────────


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
    storage_mode: str = "state"
    storage_root: Path = field(default_factory=lambda: COOKIES_DIR)
    site_id: str = ""
    account_id: str | None = None
    state_file: Path | None = None
    meta_file: Path | None = None
    resolved_by: str = (
        "auto-none"  # explicit / auto-single / auto-none / auto-ambiguous
    )
    load_applied: bool = False


# ── URL → site_id 规范化 ─────────────────────────────────


def normalize_site_id(url: str) -> str:
    """将 URL 规范化为 site_id。

    规则：
    1. 取 hostname
    2. 小写化
    3. 去端口
    4. 去前缀 www.
    5. . → -
    6. 只保留 [a-z0-9-]
    7. 空值 fallback 为 unknown-site

    示例：
    - https://www.12306.cn/index/ → 12306-cn
    - https://passport.jd.com/ → passport-jd-com
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().strip()
    except Exception:
        hostname = ""

    if not hostname:
        return "unknown-site"

    # 去掉 www. 前缀
    if hostname.startswith("www."):
        hostname = hostname[4:]

    # . → -
    hostname = hostname.replace(".", "-")

    # 只保留 [a-z0-9-]
    cleaned = re.sub(r"[^a-z0-9-]", "", hostname)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")

    return cleaned or "unknown-site"


# ── 账号解析 ─────────────────────────────────────────────


def _scan_accounts(site_dir: Path) -> list[str]:
    """扫描站点目录下的账号子目录。"""
    if not site_dir.exists() or not site_dir.is_dir():
        return []
    accounts = []
    for item in sorted(site_dir.iterdir()):
        if item.is_dir() and (item / "state.json").exists():
            accounts.append(item.name)
    return accounts


# ── 解析 ─────────────────────────────────────────────────


def resolve_session(
    config: SessionPersistenceConfig,
    url: str,
) -> ResolvedSessionState:
    """解析会话配置 + URL → 运行时状态。"""
    storage_root = config.storage_dir or COOKIES_DIR
    site_id = config.site_id or normalize_site_id(url)
    site_dir = storage_root / site_id

    # 解析 account_id
    account_id = config.account_id
    resolved_by = "explicit"
    state_file: Path | None = None
    meta_file: Path | None = None

    if account_id:
        # 显式指定
        resolved_by = "explicit"
        account_dir = site_dir / account_id
        state_file = account_dir / "state.json"
        meta_file = account_dir / "meta.json"
    else:
        # 自动查找
        candidates = _scan_accounts(site_dir)
        if len(candidates) == 0:
            resolved_by = "auto-none"
            # 保存时将使用 _default
            state_file = site_dir / "_default" / "state.json"
            meta_file = site_dir / "_default" / "meta.json"
        elif len(candidates) == 1:
            resolved_by = "auto-single"
            account_id = candidates[0]
            state_file = site_dir / account_id / "state.json"
            meta_file = site_dir / account_id / "meta.json"
        else:
            resolved_by = "auto-ambiguous"
            # 歧义：不自动选择
            account_id = None
            state_file = None
            meta_file = None

    return ResolvedSessionState(
        enabled_load=config.auto_load,
        enabled_save=config.auto_save,
        storage_mode="state",
        storage_root=storage_root,
        site_id=site_id,
        account_id=account_id,
        state_file=state_file,
        meta_file=meta_file,
        resolved_by=resolved_by,
        load_applied=False,
    )


# ── playwright-cli 调用 ──────────────────────────────────


def _playwright_prefix() -> list[str]:
    """获取 playwright-cli 命令前缀（委托给 browser_tools 的统一实现）。"""
    from webtestagent.tools.browser_tools import _playwright_prefix as _bt_prefix

    return _bt_prefix()


def _run_playwright_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    """执行 playwright-cli 子命令。"""
    return subprocess.run(
        [*_playwright_prefix(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# ── 加载 ─────────────────────────────────────────────────


def load_session_state(state: ResolvedSessionState) -> tuple[bool, str]:
    """run 前调用 playwright-cli state-load 导入登录态。

    Returns:
        (success, message) 元组
    """
    if not state.enabled_load:
        return False, "auto_load is disabled"

    if state.state_file is None:
        return False, f"No state file resolved (resolved_by={state.resolved_by})"

    if not state.state_file.exists():
        return False, f"State file not found: {state.state_file.as_posix()}"

    result = _run_playwright_cmd(["state-load", state.state_file.as_posix()])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

    if result.returncode != 0:
        return False, f"state-load failed (exit {result.returncode}): {output.strip()}"

    state.load_applied = True

    # 更新 meta.json 的 last_loaded_at
    if state.meta_file and state.meta_file.exists():
        try:
            meta = json.loads(state.meta_file.read_text(encoding="utf-8"))
            meta["last_loaded_at"] = now_iso()
            state.meta_file.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # 更新 meta 失败不阻断流程

    return True, f"Successfully loaded state from {state.state_file.as_posix()}"


# ── 保存 ─────────────────────────────────────────────────


def save_session_state(state: ResolvedSessionState, run_id: str) -> tuple[bool, str]:
    """run 后调用 playwright-cli state-save 保存登录态。

    Returns:
        (success, message) 元组
    """
    if not state.enabled_save:
        return False, "auto_save is disabled"

    # 确定保存目标
    save_file = state.state_file
    save_meta = state.meta_file

    if save_file is None:
        # 歧义场景：保存到 _default
        save_dir = state.storage_root / state.site_id / "_default"
        save_file = save_dir / "state.json"
        save_meta = save_dir / "meta.json"

    # 确保目录存在
    save_file.parent.mkdir(parents=True, exist_ok=True)

    result = _run_playwright_cmd(["state-save", save_file.as_posix()])
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

    if result.returncode != 0:
        return False, f"state-save failed (exit {result.returncode}): {output.strip()}"

    # 写入/更新 meta.json
    if save_meta:
        meta: dict[str, Any] = {}
        if save_meta.exists():
            try:
                meta = json.loads(save_meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}

        now = now_iso()
        meta.update(
            {
                "storage_mode": state.storage_mode,
                "site_id": state.site_id,
                "account_id": state.account_id or "_default",
                "updated_at": now,
                "last_run_id": run_id,
            }
        )
        if "created_at" not in meta:
            meta["created_at"] = now

        save_meta.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return True, f"Successfully saved state to {save_file.as_posix()}"


# ── manifest 辅助 ─────────────────────────────────────────


def session_manifest_data(state: ResolvedSessionState) -> dict[str, Any]:
    """生成 manifest 中的 session 脱敏元数据。"""
    return {
        "site_id": state.site_id,
        "account_id": state.account_id or "",
        "storage_mode": state.storage_mode,
        "auto_load": state.enabled_load,
        "auto_save": state.enabled_save,
        "resolved_by": state.resolved_by,
        "load": {
            "attempted": False,
            "applied": False,
            "message": "",
        },
        "save": {
            "attempted": False,
            "succeeded": False,
            "message": "",
        },
    }
