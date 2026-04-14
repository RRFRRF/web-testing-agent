"""测试 core/run_context.py：运行 ID 生成、目录结构创建。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from webtestagent.core.run_context import RunContext, build_run_id, create_run_context


# ── build_run_id ─────────────────────────────────────────


class TestBuildRunId:
    def test_format(self):
        run_id = build_run_id()
        # 格式: run-YYYYMMDD-HHMMSS-xxxxxxxx
        assert run_id.startswith("run-")
        parts = run_id.split("-")
        # run + date(8) + time(6) + suffix(8) = 至少 4 段
        assert len(parts) >= 4

    def test_unique(self):
        ids = {build_run_id() for _ in range(100)}
        assert len(ids) == 100

    def test_timestamp_pattern(self):
        run_id = build_run_id()
        # 验证时间戳部分格式
        assert re.match(r"run-\d{8}-\d{6}-[0-9a-f]{8}", run_id)


# ── RunContext ───────────────────────────────────────────


class TestRunContext:
    def test_frozen_dataclass(self):
        ctx = RunContext(
            run_id="test",
            run_dir=Path("/tmp/test"),
            snapshots_dir=Path("/tmp/test/snapshots"),
            screenshots_dir=Path("/tmp/test/screenshots"),
            console_dir=Path("/tmp/test/console"),
            network_dir=Path("/tmp/test/network"),
            manifest_path=Path("/tmp/test/manifest.json"),
        )
        with pytest.raises(AttributeError):
            ctx.run_id = "changed"  # type: ignore


# ── create_run_context ───────────────────────────────────


class TestCreateRunContext:
    def test_creates_directory_structure(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "webtestagent.core.run_context.OUTPUTS_DIR", tmp_path / "outputs"
        )
        ctx = create_run_context()
        assert ctx.run_dir.is_dir()
        assert ctx.snapshots_dir.is_dir()
        assert ctx.screenshots_dir.is_dir()
        assert ctx.console_dir.is_dir()
        assert ctx.network_dir.is_dir()

    def test_run_id_in_dir_name(self, tmp_path: Path, monkeypatch):
        outputs = tmp_path / "outputs"
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", outputs)
        ctx = create_run_context()
        assert ctx.run_id in ctx.run_dir.name
        assert ctx.run_dir.parent == outputs

    def test_manifest_path_under_run_dir(self, tmp_path: Path, monkeypatch):
        outputs = tmp_path / "outputs"
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", outputs)
        ctx = create_run_context()
        assert ctx.manifest_path == ctx.run_dir / "manifest.json"

    def test_subdirs_correct(self, tmp_path: Path, monkeypatch):
        outputs = tmp_path / "outputs"
        monkeypatch.setattr("webtestagent.core.run_context.OUTPUTS_DIR", outputs)
        ctx = create_run_context()
        assert ctx.snapshots_dir == ctx.run_dir / "snapshots"
        assert ctx.screenshots_dir == ctx.run_dir / "screenshots"
        assert ctx.console_dir == ctx.run_dir / "console"
        assert ctx.network_dir == ctx.run_dir / "network"
