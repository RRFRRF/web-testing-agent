"""RunSession 管理服务：封装 run 生命周期，替代全局 RUNS 字典。"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from webtestagent.config.settings import OUTPUTS_DIR, now_iso
from webtestagent.config.scenarios import load_session_defaults
from webtestagent.core.runner import PreparedRun, prepare_run, execute_prepared_run
from webtestagent.core.session import SessionPersistenceConfig
from webtestagent.web.schemas import (
    RunSnapshotResponse,
    SessionConfigRequest,
)

MAX_EVENTS = 500

# run_id 合法模式（与 dependencies.py 保持一致）
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

# 终止状态集合
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


# ── 数据类 ──────────────────────────────────────────────


@dataclass
class RunSession:
    """一次测试运行的会话状态。"""

    run_id: str
    url: str
    scenario: str
    run_dir: str
    manifest_path: str
    status: str = "queued"
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    completed_at: str | None = None
    final_report: str | None = None
    error: str | None = None
    events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_EVENTS)
    )
    next_event_id: int = 1
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock())
    )


# ── RunStore ────────────────────────────────────────────


class RunStore:
    """线程安全的 run 会话存储，替代模块级全局 RUNS 字典。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunSession] = {}
        self._lock = threading.RLock()

    # ── 查询 ───────────────────────────────────────────

    def get_session(self, run_id: str) -> RunSession | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_snapshots(self) -> list[RunSnapshotResponse]:
        """列出所有 run 的快照，包括活跃的和磁盘上归档的。"""
        snapshots: list[RunSnapshotResponse] = []
        seen: set[str] = set()

        with self._lock:
            sessions = list(self._runs.values())

        for session in sessions:
            snapshots.append(self.snapshot(session))
            seen.add(session.run_id)

        # 磁盘上归档的 run
        if OUTPUTS_DIR.exists():
            for run_dir in _safe_iterdir(OUTPUTS_DIR):
                if run_dir.name in seen:
                    continue
                manifest_path = run_dir / "manifest.json"
                manifest = _read_json(manifest_path)
                report_path = run_dir / "report.md"
                snapshots.append(
                    RunSnapshotResponse(
                        run_id=run_dir.name,
                        url=manifest.get("target_url", ""),
                        scenario="",
                        run_dir=run_dir.as_posix(),
                        manifest_path=manifest_path.as_posix(),
                        status="completed" if report_path.exists() else "archived",
                        started_at=manifest.get("created_at", ""),
                        completed_at=None,
                        final_report=(
                            report_path.as_posix() if report_path.exists() else None
                        ),
                        error=None,
                        latest_screenshot=_latest_artifact_path(
                            run_dir.name, "screenshot"
                        ),
                        event_count=0,
                    )
                )

        snapshots.sort(
            key=lambda s: (s.started_at or "", s.run_id or ""),
            reverse=True,
        )
        return snapshots

    # ── 创建 ───────────────────────────────────────────

    def start_run(
        self,
        url: str,
        scenario_text: str | None,
        session_config: SessionPersistenceConfig | None = None,
    ) -> RunSession:
        """创建并启动一次测试运行。"""
        from webtestagent.config.scenarios import load_scenario

        scenario_value = load_scenario((scenario_text or "").strip() or None)
        prepared = prepare_run(url, scenario_value, session_config=session_config)
        session = RunSession(
            run_id=prepared.run_context.run_id,
            url=prepared.url,
            scenario=prepared.scenario_desc,
            run_dir=prepared.run_context.run_dir.as_posix(),
            manifest_path=prepared.run_context.manifest_path.as_posix(),
        )
        with self._lock:
            self._runs[prepared.run_context.run_id] = session
        thread = threading.Thread(
            target=_run_worker, args=(session, prepared), daemon=True
        )
        thread.start()
        return session

    # ── 事件流 ─────────────────────────────────────────

    async def stream_events(
        self, run_id: str, last_event_id: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        """异步迭代 run 事件（用于 SSE 推送）。

        使用 asyncio.to_thread 避免阻塞事件循环。
        """
        session = self.get_session(run_id)
        if session is None:
            return

        while True:
            # 读取待推送事件（在锁内）
            pending: list[dict[str, Any]] = []
            with session.condition:
                for event in session.events:
                    if int(event.get("id") or 0) > last_event_id:
                        pending.append(event)

                if not pending:
                    if session.status in _TERMINAL_STATES:
                        # 发送最终状态事件
                        yield {
                            "id": last_event_id + 1,
                            "timestamp": now_iso(),
                            "channel": "system",
                            "mode": "status",
                            "summary": f"run {session.status}",
                            "payload": self.snapshot(session).model_dump(),
                        }
                        return
                    # 非阻塞等待：在线程中持有 condition 锁后再 wait，避免 RuntimeError
                    await asyncio.to_thread(_wait_on_condition, session.condition, 15)
                    yield {"event": "keepalive"}
                    continue

            for event in pending:
                yield event
                last_event_id = max(last_event_id, int(event.get("id") or 0))

            # 检查终止状态
            with session.condition:
                if session.status in _TERMINAL_STATES:
                    return

    # ── 生命周期 ───────────────────────────────────────

    async def graceful_shutdown(self, timeout: float = 30.0) -> None:
        """等待所有活跃 run 完成（最多 timeout 秒）。"""
        with self._lock:
            active = [
                s for s in self._runs.values() if s.status not in _TERMINAL_STATES
            ]
        if not active:
            return
        deadline = time.monotonic() + timeout
        for session in active:
            remaining = max(0, deadline - time.monotonic())
            if remaining <= 0:
                return
            await asyncio.to_thread(_wait_for_terminal, session, remaining)

    # ── 公开接口 ───────────────────────────────────────

    def snapshot(self, session: RunSession) -> RunSnapshotResponse:
        """将 RunSession 转为 RunSnapshotResponse（公开接口）。"""
        with session.condition:
            latest_screenshot = _latest_artifact_path(session.run_id, "screenshot")
            return RunSnapshotResponse(
                run_id=session.run_id,
                url=session.url,
                scenario=session.scenario,
                run_dir=session.run_dir,
                manifest_path=session.manifest_path,
                status=session.status,
                started_at=session.started_at,
                completed_at=session.completed_at,
                final_report=session.final_report,
                error=session.error,
                latest_screenshot=latest_screenshot,
                event_count=len(session.events),
            )

    def build_session_config(
        self, req: SessionConfigRequest | None
    ) -> SessionPersistenceConfig:
        """从请求模型构建 SessionPersistenceConfig，合并 scenarios 默认值。"""
        defaults = load_session_defaults()
        if req is None:
            return SessionPersistenceConfig(
                auto_load=bool(defaults.get("auto_load", False)),
                auto_save=bool(defaults.get("auto_save", False)),
                site_id=defaults.get("site_id") or None,
                account_id=defaults.get("account_id") or None,
                storage_dir=(Path(defaults["storage_dir"]) if defaults.get("storage_dir") else None),
            )
        storage_dir: Path | None = None
        if req.storage_dir:
            storage_dir = Path(req.storage_dir)
        elif defaults.get("storage_dir"):
            storage_dir = Path(defaults["storage_dir"])
        return SessionPersistenceConfig(
            auto_load=bool(
                req.auto_load
                if req.auto_load is not None
                else defaults.get("auto_load", False)
            ),
            auto_save=bool(
                req.auto_save
                if req.auto_save is not None
                else defaults.get("auto_save", False)
            ),
            site_id=req.site_id or defaults.get("site_id") or None,
            account_id=req.account_id or defaults.get("account_id") or None,
            storage_dir=storage_dir,
        )


# ── 模块内部辅助 ───────────────────────────────────────


def _validate_run_id_safe(run_id: str) -> str:
    """校验 run_id 安全性（内部使用）。拒绝路径遍历字符。"""
    if not run_id or not _RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return run_id


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_error": f"Invalid JSON in {path.name}: {exc}"}


def _run_manifest_path(run_id: str) -> Path:
    _validate_run_id_safe(run_id)
    return OUTPUTS_DIR / run_id / "manifest.json"


def _run_report_path(run_id: str) -> Path:
    _validate_run_id_safe(run_id)
    return OUTPUTS_DIR / run_id / "report.md"


def _latest_artifact_path(run_id: str, artifact_type: str) -> str | None:
    _validate_run_id_safe(run_id)
    manifest = _read_json(_run_manifest_path(run_id))
    artifacts = manifest.get("artifacts") or []
    if not isinstance(artifacts, list):
        return None
    for item in reversed(artifacts):
        if isinstance(item, dict) and item.get("type") == artifact_type:
            path = item.get("path")
            if isinstance(path, str) and path:
                return path
    return None


def _safe_iterdir(directory: Path) -> list[Path]:
    """安全遍历目录，跳过已删除/不可访问的条目。"""
    result: list[Path] = []
    try:
        entries = sorted(
            directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return result
    for entry in entries:
        try:
            if entry.is_dir():
                result.append(entry)
        except OSError:
            continue
    return result


def _append_event(session: RunSession, event: dict[str, Any]) -> None:
    with session.condition:
        event_id = session.next_event_id
        session.next_event_id += 1
        session.events.append({"id": event_id, **event})
        session.condition.notify_all()


def _wait_on_condition(condition: threading.Condition, timeout: float) -> None:
    """在线程内安全等待 condition。"""
    with condition:
        condition.wait(timeout=timeout)


def _wait_for_terminal(session: RunSession, timeout: float) -> None:
    """等待会话进入终止态，超时后返回。"""
    deadline = time.monotonic() + timeout
    with session.condition:
        while session.status not in _TERMINAL_STATES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            session.condition.wait(timeout=remaining)


def _run_worker(session: RunSession, prepared: PreparedRun) -> None:
    """后台线程：执行测试 run。"""
    with session.condition:
        session.status = "running"
        session.condition.notify_all()

    def on_event(event: dict[str, Any]) -> None:
        _append_event(session, event)

    try:
        result = execute_prepared_run(prepared, on_event=on_event)
        with session.condition:
            session.status = "completed"
            session.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            session.final_report = result.final_report
            session.condition.notify_all()
    except Exception as exc:
        with session.condition:
            session.status = "failed"
            session.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            session.error = str(exc)
            session.condition.notify_all()
