"""已停用的多 run 存储兼容层。

当前 Web 入口已切换到单 run `CurrentRunState`，这里仅保留最小兼容 API，
避免旧残留导入在测试收集阶段直接失败。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from webtestagent.config.settings import OUTPUTS_DIR, now_iso
from webtestagent.web.schemas import SessionConfigRequest
from webtestagent.web.state import build_session_config as _build_session_config

MAX_EVENTS = 500
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class RunSession:
    """兼容旧接口的最小会话对象。"""

    run_id: str
    url: str = ""
    scenario: str = ""
    run_dir: str = ""
    manifest_path: str = ""
    status: str = "archived"
    started_at: str = field(default_factory=now_iso)
    completed_at: str | None = None
    final_report: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class RunStore:
    """旧多 run Store 的停用兼容实现。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunSession] = {}

    def get_session(self, run_id: str) -> RunSession | None:
        return self._runs.get(run_id)

    def list_snapshots(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        seen = set(self._runs)
        for session in self._runs.values():
            snapshots.append(self.snapshot(session))

        if OUTPUTS_DIR.exists():
            for run_dir in _safe_iterdir(OUTPUTS_DIR):
                if run_dir.name in seen:
                    continue
                manifest_path = run_dir / "manifest.json"
                manifest = _read_json(manifest_path)
                report_path = run_dir / "report.md"
                snapshots.append(
                    {
                        "run_id": run_dir.name,
                        "url": manifest.get("target_url", ""),
                        "scenario": "",
                        "run_dir": run_dir.as_posix(),
                        "manifest_path": manifest_path.as_posix(),
                        "status": "completed" if report_path.exists() else "archived",
                        "started_at": manifest.get("created_at", ""),
                        "completed_at": None,
                        "final_report": report_path.as_posix() if report_path.exists() else None,
                        "error": None,
                        "latest_screenshot": _latest_artifact_path(run_dir.name, "screenshot"),
                        "event_count": 0,
                    }
                )

        snapshots.sort(
            key=lambda s: (s.get("started_at") or "", s.get("run_id") or ""),
            reverse=True,
        )
        return snapshots

    def start_run(
        self,
        url: str,
        scenario_text: str | None,
        session_config: Any | None = None,
    ) -> RunSession:
        raise RuntimeError(
            "Legacy multi-run RunStore has been removed. Use webtestagent.web.state/current_run instead."
        )

    def snapshot(self, session: RunSession) -> dict[str, Any]:
        latest_screenshot = _latest_artifact_path(session.run_id, "screenshot")
        return {
            "run_id": session.run_id,
            "url": session.url,
            "scenario": session.scenario,
            "run_dir": session.run_dir,
            "manifest_path": session.manifest_path,
            "status": session.status,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "final_report": session.final_report,
            "error": session.error,
            "latest_screenshot": latest_screenshot,
            "event_count": len(session.events),
        }

    def build_session_config(self, req: SessionConfigRequest | None):
        payload = req.model_dump() if req is not None else None
        return _build_session_config(payload)


def _validate_run_id_safe(run_id: str) -> str:
    if not run_id or not _RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return run_id


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"_error": f"Invalid JSON in {path.name}: {exc}"}


def _run_manifest_path(run_id: str) -> Path:
    _validate_run_id_safe(run_id)
    return OUTPUTS_DIR / run_id / "manifest.json"


def _run_report_path(run_id: str) -> Path:
    _validate_run_id_safe(run_id)
    return OUTPUTS_DIR / run_id / "report.md"


def _latest_artifact_path(run_id: str, artifact_type: str) -> str | None:
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
