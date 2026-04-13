"""artifact 落盘、预览生成与 manifest 维护。"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT


PREVIEW_MAX_LINES = 10
PREVIEW_MAX_CHARS = 1200
_MANIFEST_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass
class ArtifactRecord:
    index: int
    type: str
    label: str
    path: str
    created_at: str
    size_bytes: int
    preview: str


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_manifest_lock(manifest_path: Path) -> threading.RLock:
    key = str(manifest_path.resolve())
    with _LOCKS_GUARD:
        lock = _MANIFEST_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _MANIFEST_LOCKS[key] = lock
        return lock


def _default_manifest(*, run_id: str, target_url: str | None = None) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": _now_iso(),
        "target_url": target_url or "",
        "artifacts": [],
    }


def _write_manifest(manifest_path: Path, data: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)


def _read_manifest(manifest_path: Path, *, run_id: str, target_url: str | None = None) -> dict[str, Any]:
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Manifest is corrupted: {manifest_path.as_posix()}") from exc

    data = _default_manifest(run_id=run_id, target_url=target_url)
    _write_manifest(manifest_path, data)
    return data


def _to_virtual_path(file_path: Path) -> str:
    try:
        relative = file_path.resolve().relative_to(PROJECT_ROOT.resolve())
        return f"/{relative.as_posix()}"
    except ValueError:
        return file_path.as_posix()


def slugify_label(label: str) -> str:
    """将用户标签转为适合文件名的形式。"""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "artifact"


def build_preview(text: str, *, max_lines: int = PREVIEW_MAX_LINES, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    """构建轻量文本预览。"""
    stripped = text.strip()
    if not stripped:
        return "(empty)"
    lines = stripped.splitlines()[:max_lines]
    preview = "\n".join(lines)
    if len(preview) > max_chars:
        preview = preview[:max_chars] + "\n...(truncated)"
    elif len(stripped.splitlines()) > max_lines:
        preview += "\n...(truncated)"
    return preview


def ensure_manifest(manifest_path: Path, *, run_id: str, target_url: str | None = None) -> dict[str, Any]:
    """初始化或读取 manifest.json。"""
    lock = _get_manifest_lock(manifest_path)
    with lock:
        return _read_manifest(manifest_path, run_id=run_id, target_url=target_url)


def update_manifest_target_url(manifest_path: Path, *, run_id: str, target_url: str) -> None:
    """更新 manifest 中的目标 URL。"""
    lock = _get_manifest_lock(manifest_path)
    with lock:
        data = _read_manifest(manifest_path, run_id=run_id)
        data["target_url"] = target_url
        _write_manifest(manifest_path, data)


def add_artifact_record(
    manifest_path: Path,
    *,
    run_id: str,
    artifact_type: str,
    label: str,
    file_path: Path,
    preview: str,
) -> ArtifactRecord:
    """向 manifest 添加一条 artifact 记录。"""
    lock = _get_manifest_lock(manifest_path)
    with lock:
        data = _read_manifest(manifest_path, run_id=run_id)
        index = len(data["artifacts"]) + 1
        record = ArtifactRecord(
            index=index,
            type=artifact_type,
            label=label,
            path=_to_virtual_path(file_path),
            created_at=_now_iso(),
            size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            preview=preview,
        )
        data["artifacts"].append(asdict(record))
        _write_manifest(manifest_path, data)
        return record


def save_text_artifact(
    *,
    manifest_path: Path,
    run_id: str,
    artifact_dir: Path,
    artifact_type: str,
    label: str,
    suffix: str,
    content: str,
) -> ArtifactRecord:
    """保存文本 artifact，并写入 manifest。"""
    lock = _get_manifest_lock(manifest_path)
    with lock:
        data = _read_manifest(manifest_path, run_id=run_id)
        index = len(data["artifacts"]) + 1
        filename = f"{index:03d}-{slugify_label(label)}{suffix}"
        file_path = artifact_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        record = ArtifactRecord(
            index=index,
            type=artifact_type,
            label=label,
            path=_to_virtual_path(file_path),
            created_at=_now_iso(),
            size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            preview=build_preview(content),
        )
        data["artifacts"].append(asdict(record))
        _write_manifest(manifest_path, data)
        return record


def register_file_artifact(
    *,
    manifest_path: Path,
    run_id: str,
    artifact_type: str,
    label: str,
    file_path: Path,
    preview: str | None = None,
) -> ArtifactRecord:
    """将现有文件注册进 manifest。"""
    final_preview = preview or f"Saved file: {_to_virtual_path(file_path)}"
    return add_artifact_record(
        manifest_path,
        run_id=run_id,
        artifact_type=artifact_type,
        label=label,
        file_path=file_path,
        preview=final_preview,
    )


def format_artifact_response(record: ArtifactRecord) -> str:
    """返回给 agent 的轻量摘要。"""
    return (
        f"artifact saved\n"
        f"- type: {record.type}\n"
        f"- label: {record.label}\n"
        f"- path: {record.path}\n"
        f"- size_bytes: {record.size_bytes}\n"
        f"- preview:\n{record.preview}"
    )
