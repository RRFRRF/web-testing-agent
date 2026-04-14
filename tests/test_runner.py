"""测试 core/runner.py：测试运行准备、执行与报告落盘。"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from webtestagent.core.runner import (
    PreparedRun,
    RunResult,
    build_thread_id,
    describe_scenario,
    emit_event,
    inject_run_environment,
    prepare_run,
    execute_prepared_run,
    save_final_report,
    _read_manifest_raw,
    _update_manifest_session_block,
    _update_manifest_session_load,
    _update_manifest_session_save,
    _write_manifest_raw,
)
from webtestagent.core.run_context import RunContext


# ── describe_scenario ────────────────────────────────────


class TestDescribeScenario:
    def test_string_scenario(self):
        assert describe_scenario("检查首页") == "检查首页"

    def test_list_scenario(self):
        steps = [{"action": "click"}, {"action": "wait"}]
        assert describe_scenario(steps) == "2 个结构化步骤"

    def test_single_step(self):
        assert describe_scenario([{"action": "open"}]) == "1 个结构化步骤"

    def test_empty_list(self):
        assert describe_scenario([]) == "0 个结构化步骤"


# ── build_thread_id ──────────────────────────────────────


class TestBuildThreadId:
    def test_format(self):
        result = build_thread_id("abc-123")
        assert result == "mvp-web-test-run-abc-123"

    def test_unique_for_different_run_ids(self):
        assert build_thread_id("r1") != build_thread_id("r2")


# ── inject_run_environment ───────────────────────────────


class TestInjectRunEnvironment:
    def test_sets_env_vars(self, tmp_path, monkeypatch):
        run_dir = tmp_path / "outputs" / "r1"
        manifest_path = run_dir / "manifest.json"
        ctx = RunContext(
            run_id="r1",
            run_dir=run_dir,
            snapshots_dir=run_dir / "snapshots",
            screenshots_dir=run_dir / "screenshots",
            console_dir=run_dir / "console",
            network_dir=run_dir / "network",
            manifest_path=manifest_path,
        )
        inject_run_environment(ctx)
        assert os.environ["RUN_ID"] == "r1"
        assert os.environ["OUTPUTS_DIR"] == run_dir.as_posix()
        assert os.environ["MANIFEST_PATH"] == manifest_path.as_posix()


# ── emit_event ───────────────────────────────────────────


class TestEmitEvent:
    def test_none_callback(self):
        # Should not raise
        emit_event(None, {"channel": "system", "summary": "start"})

    def test_callback_receives_timestamp(self):
        received = []

        def cb(event):
            received.append(event)

        emit_event(cb, {"channel": "system", "summary": "start"})
        assert len(received) == 1
        assert "timestamp" in received[0]
        assert received[0]["channel"] == "system"

    def test_event_enriched(self):
        received = []

        def cb(event):
            received.append(event)

        emit_event(cb, {"channel": "model", "summary": "thinking"})
        assert received[0]["channel"] == "model"
        assert received[0]["summary"] == "thinking"


# ── save_final_report ────────────────────────────────────


class TestSaveFinalReport:
    def test_writes_report(self, tmp_path):
        run_dir = tmp_path / "r1"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text('{"run_id": "r1", "artifacts": []}', encoding="utf-8")

        ctx = RunContext(
            run_id="r1",
            run_dir=run_dir,
            snapshots_dir=run_dir / "snapshots",
            screenshots_dir=run_dir / "screenshots",
            console_dir=run_dir / "console",
            network_dir=run_dir / "network",
            manifest_path=manifest_path,
        )
        prepared = PreparedRun(
            url="https://example.com",
            scenario="test",
            scenario_desc="test",
            prompt="test prompt",
            run_context=ctx,
            cli_command="pw",
            config={},
            agent=MagicMock(),
            thread_id="t1",
        )
        report_path = save_final_report(prepared, "# Test Report\nAll good!")
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "Test Report" in content

    def test_manifest_updated(self, tmp_path):
        run_dir = tmp_path / "r1"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text('{"run_id": "r1", "artifacts": []}', encoding="utf-8")

        ctx = RunContext(
            run_id="r1",
            run_dir=run_dir,
            snapshots_dir=run_dir / "snapshots",
            screenshots_dir=run_dir / "screenshots",
            console_dir=run_dir / "console",
            network_dir=run_dir / "network",
            manifest_path=manifest_path,
        )
        prepared = PreparedRun(
            url="https://example.com",
            scenario="test",
            scenario_desc="test",
            prompt="p",
            run_context=ctx,
            cli_command="pw",
            config={},
            agent=MagicMock(),
            thread_id="t1",
        )
        save_final_report(prepared, "report text")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts", [])
        assert any(a.get("type") == "report" for a in artifacts)


# ── manifest session helpers ─────────────────────────────


class TestManifestSessionHelpers:
    def test_read_manifest_raw_exists(self, tmp_path):
        mp = tmp_path / "manifest.json"
        mp.write_text(
            '{"run_id": "r1", "target_url": "https://x.com"}', encoding="utf-8"
        )
        data = _read_manifest_raw(mp, run_id="r1")
        assert data["target_url"] == "https://x.com"

    def test_read_manifest_raw_missing(self, tmp_path):
        mp = tmp_path / "nonexistent.json"
        data = _read_manifest_raw(mp, run_id="r1")
        assert data == {"run_id": "r1"}

    def test_write_and_read_roundtrip(self, tmp_path):
        mp = tmp_path / "manifest.json"
        original = {"run_id": "r1", "artifacts": [{"type": "snapshot"}]}
        _write_manifest_raw(mp, original)
        data = _read_manifest_raw(mp, run_id="r1")
        assert data["artifacts"][0]["type"] == "snapshot"

    def test_update_manifest_session_block(self, tmp_path):
        mp = tmp_path / "manifest.json"
        mp.write_text('{"run_id": "r1"}', encoding="utf-8")
        _update_manifest_session_block(
            mp, run_id="r1", session_data={"site_id": "example.com"}
        )
        data = _read_manifest_raw(mp, run_id="r1")
        assert data["session"]["site_id"] == "example.com"

    def test_update_manifest_session_load(self, tmp_path):
        mp = tmp_path / "manifest.json"
        mp.write_text('{"run_id": "r1"}', encoding="utf-8")
        _update_manifest_session_load(
            mp, run_id="r1", attempted=True, applied=True, message="loaded cookies"
        )
        data = _read_manifest_raw(mp, run_id="r1")
        assert data["session"]["load"]["applied"] is True

    def test_update_manifest_session_save(self, tmp_path):
        mp = tmp_path / "manifest.json"
        mp.write_text('{"run_id": "r1"}', encoding="utf-8")
        _update_manifest_session_save(
            mp, run_id="r1", attempted=True, succeeded=True, message="saved ok"
        )
        data = _read_manifest_raw(mp, run_id="r1")
        assert data["session"]["save"]["succeeded"] is True


# ── PreparedRun / RunResult dataclasses ──────────────────


class TestDataclasses:
    def test_prepared_run_fields(self, tmp_path):
        ctx = RunContext(
            run_id="r1",
            run_dir=tmp_path,
            snapshots_dir=tmp_path / "snapshots",
            screenshots_dir=tmp_path / "screenshots",
            console_dir=tmp_path / "console",
            network_dir=tmp_path / "network",
            manifest_path=tmp_path / "m.json",
        )
        p = PreparedRun(
            url="https://x.com",
            scenario="s",
            scenario_desc="d",
            prompt="p",
            run_context=ctx,
            cli_command="pw",
            config={},
            agent=None,
            thread_id="t1",
        )
        assert p.url == "https://x.com"
        assert p.session_state is None

    def test_run_result_fields(self, tmp_path):
        r = RunResult(
            url="https://x.com",
            scenario="s",
            scenario_desc="d",
            run_id="r1",
            run_dir=tmp_path,
            manifest_path=tmp_path / "m.json",
            report_path=tmp_path / "report.md",
            cli_command="pw",
            final_result={"messages": []},
            final_report="report",
        )
        assert r.run_id == "r1"
        assert r.final_report == "report"


# ── prepare_run 集成测试（mock 外部依赖）─────────────────


class TestPrepareRun:
    def test_prepare_run_basic(self, tmp_path, monkeypatch):
        """验证 prepare_run 返回正确的 PreparedRun 结构。"""
        monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
        with (
            patch("webtestagent.core.runner.init_env"),
            patch("webtestagent.core.runner.create_run_context") as mock_ctx,
            patch("webtestagent.core.runner.ensure_manifest"),
            patch("webtestagent.core.runner.update_manifest_target_url"),
            patch("webtestagent.core.runner.build_prompt", return_value="test prompt"),
            patch("webtestagent.core.runner.resolve_playwright_cli", return_value="pw"),
            patch("webtestagent.core.runner.build_agent", return_value=MagicMock()),
        ):
            mock_ctx.return_value = RunContext(
                run_id="test-run",
                run_dir=tmp_path,
                snapshots_dir=tmp_path / "snapshots",
                screenshots_dir=tmp_path / "screenshots",
                console_dir=tmp_path / "console",
                network_dir=tmp_path / "network",
                manifest_path=tmp_path / "manifest.json",
            )
            prepared = prepare_run("https://example.com", "test scenario")
            assert prepared.url == "https://example.com"
            assert prepared.scenario == "test scenario"
            assert prepared.scenario_desc == "test scenario"
            assert prepared.prompt == "test prompt"
            assert prepared.cli_command == "pw"
            assert prepared.run_context.run_id == "test-run"
            assert prepared.session_state is None


# ── execute_prepared_run 集成测试 ────────────────────────


class TestExecutePreparedRun:
    def test_execute_success(self, tmp_path):
        """验证 execute_prepared_run 在 agent 正常返回时生成报告。"""
        run_dir = tmp_path / "r1"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text('{"run_id": "r1", "artifacts": []}', encoding="utf-8")

        ctx = RunContext(
            run_id="r1",
            run_dir=run_dir,
            snapshots_dir=run_dir / "snapshots",
            screenshots_dir=run_dir / "screenshots",
            console_dir=run_dir / "console",
            network_dir=run_dir / "network",
            manifest_path=manifest_path,
        )
        prepared = PreparedRun(
            url="https://example.com",
            scenario="s",
            scenario_desc="d",
            prompt="p",
            run_context=ctx,
            cli_command="pw",
            config={"configurable": {"thread_id": "t1"}},
            agent=MagicMock(),
            thread_id="t1",
        )

        # Mock agent.stream to yield a valid tuple chunk
        mock_state = MagicMock()
        mock_state.values = {"messages": ["test result"]}
        prepared.agent.stream.return_value = iter(
            [
                ("updates", {"agent": {"messages": ["step1"]}}),
            ]
        )
        prepared.agent.get_state.return_value = mock_state

        with (
            patch(
                "webtestagent.core.runner.final_result_from_state",
                return_value={"messages": ["test result"]},
            ),
            patch("webtestagent.core.runner.extract_text", return_value="Test passed"),
            patch("webtestagent.core.runner.inject_run_environment"),
        ):
            result = execute_prepared_run(prepared)

        assert isinstance(result, RunResult)
        assert result.run_id == "r1"
        assert result.final_report == "Test passed"
        assert result.report_path.exists()

    def test_execute_error_propagates(self, tmp_path):
        """验证 execute_prepared_run 在 agent 抛异常时正确传播。"""
        run_dir = tmp_path / "r1"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text('{"run_id": "r1", "artifacts": []}', encoding="utf-8")

        ctx = RunContext(
            run_id="r1",
            run_dir=run_dir,
            snapshots_dir=run_dir / "snapshots",
            screenshots_dir=run_dir / "screenshots",
            console_dir=run_dir / "console",
            network_dir=run_dir / "network",
            manifest_path=manifest_path,
        )
        prepared = PreparedRun(
            url="https://example.com",
            scenario="s",
            scenario_desc="d",
            prompt="p",
            run_context=ctx,
            cli_command="pw",
            config={"configurable": {"thread_id": "t1"}},
            agent=MagicMock(),
            thread_id="t1",
        )
        prepared.agent.stream.side_effect = RuntimeError("agent crashed")

        with patch("webtestagent.core.runner.inject_run_environment"):
            with pytest.raises(RuntimeError, match="agent crashed"):
                execute_prepared_run(prepared)
