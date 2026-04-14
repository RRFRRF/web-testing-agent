"""测试 core/artifacts.py：artifact 落盘、预览、manifest 维护。"""

from __future__ import annotations

from pathlib import Path

import pytest

from webtestagent.core.artifacts import (
    ArtifactRecord,
    build_preview,
    ensure_manifest,
    format_artifact_response,
    register_file_artifact,
    save_text_artifact,
    slugify_label,
    update_manifest_target_url,
)


# ── slugify_label ────────────────────────────────────────


class TestSlugifyLabel:
    def test_simple_text(self):
        assert slugify_label("首页快照") == "首页快照"

    def test_spaces_to_hyphens(self):
        assert slugify_label("after search") == "after-search"

    def test_special_chars_removed(self):
        result = slugify_label("step#1!/test")
        assert "#" not in result
        assert "!" not in result

    def test_empty_returns_artifact(self):
        assert slugify_label("") == "artifact"

    def test_whitespace_only_returns_artifact(self):
        assert slugify_label("   ") == "artifact"

    def test_mixed_case_lowered(self):
        assert slugify_label("MyLabel") == "mylabel"

    def test_consecutive_hyphens_collapsed(self):
        result = slugify_label("a---b")
        assert "---" not in result
        assert "a-b" in result


# ── build_preview ────────────────────────────────────────


class TestBuildPreview:
    def test_short_text_unchanged(self):
        assert build_preview("hello") == "hello"

    def test_empty_returns_empty_marker(self):
        assert build_preview("") == "(empty)"
        assert build_preview("  \n  ") == "(empty)"

    def test_truncation_by_chars(self):
        long_text = "a" * 2000
        preview = build_preview(long_text, max_chars=100)
        assert len(preview) < 2000
        assert "truncated" in preview

    def test_truncation_by_lines(self):
        many_lines = "\n".join(f"line {i}" for i in range(50))
        preview = build_preview(many_lines, max_lines=5)
        assert "truncated" in preview

    def test_custom_limits(self):
        text = "x" * 500
        preview = build_preview(text, max_chars=200)
        assert len(preview) <= 220  # 允许 "...(truncated)" 尾部


# ── ensure_manifest ──────────────────────────────────────


class TestEnsureManifest:
    def test_creates_manifest_if_missing(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        data = ensure_manifest(manifest_path, run_id="test-run-1")
        assert manifest_path.exists()
        assert data["run_id"] == "test-run-1"
        assert "artifacts" in data
        assert isinstance(data["artifacts"], list)

    def test_reads_existing_manifest(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        # 先创建
        ensure_manifest(manifest_path, run_id="run-a", target_url="https://a.com")
        # 再读取
        data = ensure_manifest(manifest_path, run_id="run-a")
        assert data["target_url"] == "https://a.com"

    def test_corrupted_manifest_raises(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("NOT JSON{{", encoding="utf-8")
        with pytest.raises(RuntimeError, match="corrupted"):
            ensure_manifest(manifest_path, run_id="bad-run")

    def test_target_url_stored(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        data = ensure_manifest(
            manifest_path, run_id="r1", target_url="https://example.com"
        )
        assert data["target_url"] == "https://example.com"


# ── update_manifest_target_url ───────────────────────────


class TestUpdateManifestTargetUrl:
    def test_updates_url(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        ensure_manifest(manifest_path, run_id="r1", target_url="https://old.com")
        update_manifest_target_url(
            manifest_path, run_id="r1", target_url="https://new.com"
        )
        data = ensure_manifest(manifest_path, run_id="r1")
        assert data["target_url"] == "https://new.com"


# ── save_text_artifact ───────────────────────────────────


class TestSaveTextArtifact:
    def test_saves_file_and_updates_manifest(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        artifact_dir = tmp_path / "snaps"
        artifact_dir.mkdir()

        ensure_manifest(manifest_path, run_id="r1")

        record = save_text_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_dir=artifact_dir,
            artifact_type="snapshot",
            label="home-page",
            suffix=".yaml",
            content="page:\n  title: Test",
        )

        assert isinstance(record, ArtifactRecord)
        assert record.type == "snapshot"
        assert record.label == "home-page"
        assert record.size_bytes > 0
        # 验证文件已落盘
        saved_files = list(artifact_dir.glob("*.yaml"))
        assert len(saved_files) == 1

    def test_increments_index(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        artifact_dir = tmp_path / "snaps"
        artifact_dir.mkdir()
        ensure_manifest(manifest_path, run_id="r1")

        r1 = save_text_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_dir=artifact_dir,
            artifact_type="snapshot",
            label="step-1",
            suffix=".yaml",
            content="a",
        )
        r2 = save_text_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_dir=artifact_dir,
            artifact_type="snapshot",
            label="step-2",
            suffix=".yaml",
            content="b",
        )
        assert r1.index == 1
        assert r2.index == 2


# ── register_file_artifact ───────────────────────────────


class TestRegisterFileArtifact:
    def test_registers_existing_file(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        ensure_manifest(manifest_path, run_id="r1")

        file_path = tmp_path / "screenshot.png"
        file_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        record = register_file_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_type="screenshot",
            label="home-screen",
            file_path=file_path,
            preview="Screenshot saved",
        )

        assert record.type == "screenshot"
        assert record.size_bytes > 0

    def test_custom_preview(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        ensure_manifest(manifest_path, run_id="r1")

        file_path = tmp_path / "data.txt"
        file_path.write_text("hello", encoding="utf-8")

        record = register_file_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_type="text",
            label="custom",
            file_path=file_path,
            preview="Custom preview text",
        )
        assert record.preview == "Custom preview text"

    def test_default_preview_when_none(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        ensure_manifest(manifest_path, run_id="r1")

        file_path = tmp_path / "data.txt"
        file_path.write_text("hello", encoding="utf-8")

        record = register_file_artifact(
            manifest_path=manifest_path,
            run_id="r1",
            artifact_type="text",
            label="auto-preview",
            file_path=file_path,
            preview=None,
        )
        assert "Saved file" in record.preview


# ── format_artifact_response ─────────────────────────────


class TestFormatArtifactResponse:
    def test_output_format(self):
        record = ArtifactRecord(
            index=1,
            type="snapshot",
            label="home",
            path="/outputs/run-1/snapshots/001-home.yaml",
            created_at="2025-01-01T00:00:00",
            size_bytes=1024,
            preview="page title: Test",
        )
        text = format_artifact_response(record)
        assert "artifact saved" in text
        assert "snapshot" in text
        assert "home" in text
        assert "1024" in text
