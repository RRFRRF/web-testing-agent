"""测试 core/session.py：site_id 规范化、session 解析/加载/保存。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch


from webtestagent.core.session import (
    ResolvedSessionState,
    SessionPersistenceConfig,
    normalize_site_id,
    resolve_session,
    session_manifest_data,
    _scan_accounts,
    load_session_state,
    save_session_state,
    _playwright_prefix,
    _run_playwright_cmd,
)


# ── normalize_site_id ────────────────────────────────────


class TestNormalizeSiteId:
    def test_12306(self):
        assert normalize_site_id("https://www.12306.cn/index/") == "12306-cn"

    def test_jd_passport(self):
        assert normalize_site_id("https://passport.jd.com/") == "passport-jd-com"

    def test_strip_www(self):
        assert normalize_site_id("https://www.example.com/") == "example-com"

    def test_no_www(self):
        assert normalize_site_id("https://example.com/") == "example-com"

    def test_empty_url(self):
        assert normalize_site_id("") == "unknown-site"

    def test_invalid_url(self):
        assert normalize_site_id("not-a-url") == "unknown-site"

    def test_lowercase(self):
        assert normalize_site_id("https://EXAMPLE.COM/") == "example-com"

    def test_port_stripped(self):
        result = normalize_site_id("https://example.com:8080/")
        assert "8080" not in result
        assert result == "example-com"

    def test_multi_dot(self):
        assert normalize_site_id("https://a.b.c.com/") == "a-b-c-com"


# ── _scan_accounts ───────────────────────────────────────


class TestScanAccounts:
    def test_empty_dir(self, tmp_path: Path):
        assert _scan_accounts(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert _scan_accounts(tmp_path / "nope") == []

    def test_finds_accounts(self, tmp_path: Path):
        (tmp_path / "user1" / "state.json").parent.mkdir(parents=True)
        (tmp_path / "user1" / "state.json").write_text("{}", encoding="utf-8")
        (tmp_path / "user2" / "state.json").parent.mkdir(parents=True)
        (tmp_path / "user2" / "state.json").write_text("{}", encoding="utf-8")
        accounts = _scan_accounts(tmp_path)
        assert accounts == ["user1", "user2"]

    def test_ignores_no_state_json(self, tmp_path: Path):
        (tmp_path / "empty_dir").mkdir()
        assert _scan_accounts(tmp_path) == []


# ── resolve_session ──────────────────────────────────────


class TestResolveSession:
    def test_explicit_account(self, tmp_path: Path):
        config = SessionPersistenceConfig(
            auto_load=True,
            auto_save=True,
            site_id="test-site",
            account_id="user1",
            storage_dir=tmp_path,
        )
        state = resolve_session(config, "https://example.com/")
        assert state.site_id == "test-site"
        assert state.account_id == "user1"
        assert state.resolved_by == "explicit"
        assert state.enabled_load is True

    def test_auto_single_account(self, tmp_path: Path):
        site_dir = tmp_path / "example-com" / "user1"
        site_dir.mkdir(parents=True)
        (site_dir / "state.json").write_text("{}", encoding="utf-8")
        config = SessionPersistenceConfig(auto_load=True, storage_dir=tmp_path)
        state = resolve_session(config, "https://example.com/")
        assert state.resolved_by == "auto-single"
        assert state.account_id == "user1"

    def test_auto_no_accounts(self, tmp_path: Path):
        config = SessionPersistenceConfig(auto_load=True, storage_dir=tmp_path)
        state = resolve_session(config, "https://example.com/")
        assert state.resolved_by == "auto-none"
        assert state.account_id is None

    def test_auto_ambiguous(self, tmp_path: Path):
        site_dir = tmp_path / "example-com"
        for acc in ["user1", "user2"]:
            d = site_dir / acc
            d.mkdir(parents=True)
            (d / "state.json").write_text("{}", encoding="utf-8")
        config = SessionPersistenceConfig(auto_load=True, storage_dir=tmp_path)
        state = resolve_session(config, "https://example.com/")
        assert state.resolved_by == "auto-ambiguous"
        assert state.state_file is None

    def test_site_id_from_url(self, tmp_path: Path):
        config = SessionPersistenceConfig(storage_dir=tmp_path)
        state = resolve_session(config, "https://www.12306.cn/index/")
        assert state.site_id == "12306-cn"


# ── session_manifest_data ────────────────────────────────


class TestSessionManifestData:
    def test_structure(self):
        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="test",
            account_id="u1",
            resolved_by="explicit",
        )
        data = session_manifest_data(state)
        assert data["site_id"] == "test"
        assert data["auto_load"] is True
        assert "load" in data
        assert "save" in data


# ── load_session_state / save_session_state ─────────────


class TestLoadSessionState:
    """测试 load_session_state 的各种路径。"""

    def test_disabled_auto_load(self):
        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=False,
            site_id="test",
            resolved_by="explicit",
        )
        ok, msg = load_session_state(state)
        assert ok is False
        assert "disabled" in msg

    def test_no_state_file_resolved(self):
        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="test",
            state_file=None,
            resolved_by="auto-ambiguous",
        )
        ok, msg = load_session_state(state)
        assert ok is False
        assert "No state file" in msg

    def test_state_file_not_found(self, tmp_path: Path):
        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="test",
            state_file=tmp_path / "nonexistent" / "state.json",
            resolved_by="explicit",
        )
        ok, msg = load_session_state(state)
        assert ok is False
        assert "not found" in msg

    def test_successful_load(self, tmp_path: Path):
        """mock _run_playwright_cmd 模拟成功加载。"""
        state_file = tmp_path / "site" / "user1" / "state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{}", encoding="utf-8")
        meta_file = tmp_path / "site" / "user1" / "meta.json"
        meta_file.write_text('{"created_at": "2025-01-01"}', encoding="utf-8")

        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="site",
            account_id="user1",
            state_file=state_file,
            meta_file=meta_file,
            resolved_by="explicit",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="OK", stderr=""
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = load_session_state(state)
        assert ok is True
        assert "Successfully" in msg
        assert state.load_applied is True

    def test_load_playwright_failure(self, tmp_path: Path):
        """playwright-cli state-load 失败。"""
        state_file = tmp_path / "site" / "user1" / "state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{}", encoding="utf-8")

        state = ResolvedSessionState(
            enabled_load=True,
            enabled_save=False,
            site_id="site",
            state_file=state_file,
            resolved_by="explicit",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = load_session_state(state)
        assert ok is False
        assert "failed" in msg


class TestSaveSessionState:
    """测试 save_session_state 的各种路径。"""

    def test_disabled_auto_save(self):
        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=False,
            site_id="test",
            resolved_by="explicit",
        )
        ok, msg = save_session_state(state, "run1")
        assert ok is False
        assert "disabled" in msg

    def test_save_with_no_state_file_uses_default(self, tmp_path: Path):
        """state_file 为 None 时保存到 _default。"""
        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=True,
            site_id="test-site",
            storage_root=tmp_path,
            state_file=None,
            meta_file=None,
            resolved_by="auto-ambiguous",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="OK", stderr=""
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = save_session_state(state, "run1")
        assert ok is True
        assert "_default" in msg

    def test_successful_save(self, tmp_path: Path):
        """正常保存状态和 meta。"""
        state_file = tmp_path / "site" / "user1" / "state.json"
        meta_file = tmp_path / "site" / "user1" / "meta.json"

        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=True,
            site_id="site",
            account_id="user1",
            storage_root=tmp_path,
            state_file=state_file,
            meta_file=meta_file,
            resolved_by="explicit",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="OK", stderr=""
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = save_session_state(state, "run1")
        assert ok is True
        assert "Successfully" in msg
        # meta.json 应该被创建
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["site_id"] == "site"
        assert meta["last_run_id"] == "run1"

    def test_save_playwright_failure(self, tmp_path: Path):
        """playwright-cli state-save 失败。"""
        state_file = tmp_path / "site" / "user1" / "state.json"

        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=True,
            site_id="site",
            account_id="user1",
            storage_root=tmp_path,
            state_file=state_file,
            resolved_by="explicit",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = save_session_state(state, "run1")
        assert ok is False
        assert "failed" in msg

    def test_save_updates_existing_meta(self, tmp_path: Path):
        """保存时更新已有的 meta.json。"""
        state_file = tmp_path / "site" / "user1" / "state.json"
        meta_file = tmp_path / "site" / "user1" / "meta.json"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(
            json.dumps({"created_at": "2025-01-01", "old_field": "keep"}),
            encoding="utf-8",
        )

        state = ResolvedSessionState(
            enabled_load=False,
            enabled_save=True,
            site_id="site",
            account_id="user1",
            storage_root=tmp_path,
            state_file=state_file,
            meta_file=meta_file,
            resolved_by="explicit",
        )

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="OK", stderr=""
        )
        with patch(
            "webtestagent.core.session._run_playwright_cmd",
            return_value=mock_result,
        ):
            ok, msg = save_session_state(state, "run2")
        assert ok is True
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["created_at"] == "2025-01-01"  # 保留旧值
        assert meta["last_run_id"] == "run2"  # 更新新值


# ── _playwright_prefix 委托 ────────────────────────────


class TestPlaywrightPrefix:
    """测试 _playwright_prefix 委托给 browser_tools。"""

    def test_delegates_to_browser_tools(self):
        with patch(
            "webtestagent.tools.browser_tools._playwright_prefix",
            return_value=["npx", "playwright-cli"],
        ):
            result = _playwright_prefix()
        assert result == ["npx", "playwright-cli"]


# ── _run_playwright_cmd ────────────────────────────────


class TestRunPlaywrightCmd:
    """测试 _run_playwright_cmd 执行。"""

    def test_calls_subprocess(self):
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with patch(
            "webtestagent.core.session.subprocess.run", return_value=mock_result
        ):
            with patch(
                "webtestagent.tools.browser_tools._playwright_prefix",
                return_value=["playwright-cli"],
            ):
                result = _run_playwright_cmd(["state-load", "/tmp/state.json"])
        assert result.returncode == 0
