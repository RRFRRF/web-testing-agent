"""每次运行的上下文与输出目录管理。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from webtestagent.config.settings import OUTPUTS_DIR


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    snapshots_dir: Path
    screenshots_dir: Path
    console_dir: Path
    network_dir: Path
    manifest_path: Path


def build_run_id() -> str:
    """生成本次运行唯一 ID。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:8]
    return f"run-{timestamp}-{suffix}"


def create_run_context() -> RunContext:
    """创建本次运行的输出目录结构。"""
    run_id = build_run_id()
    run_dir = OUTPUTS_DIR / run_id
    snapshots_dir = run_dir / "snapshots"
    screenshots_dir = run_dir / "screenshots"
    console_dir = run_dir / "console"
    network_dir = run_dir / "network"
    manifest_path = run_dir / "manifest.json"

    for path in [OUTPUTS_DIR, run_dir, snapshots_dir, screenshots_dir, console_dir, network_dir]:
        path.mkdir(parents=True, exist_ok=True)

    return RunContext(
        run_id=run_id,
        run_dir=run_dir,
        snapshots_dir=snapshots_dir,
        screenshots_dir=screenshots_dir,
        console_dir=console_dir,
        network_dir=network_dir,
        manifest_path=manifest_path,
    )
