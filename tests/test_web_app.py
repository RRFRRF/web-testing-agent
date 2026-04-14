"""测试 web/app.py：HTTP 服务器路由与 RunSession 管理。"""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from webtestagent.web.app_legacy import (
    MAX_BODY_SIZE,
    MAX_EVENTS,
    RunSession,
    RUNS,
    RUNS_LOCK,
    _build_session_config,
    _get_session,
    _latest_artifact_path,
    _read_json,
    _run_manifest_path,
    _run_report_path,
    _session_snapshot,
    AppHandler,
    configure_utf8_runtime,
)


# ── 全局 RUNS 隔离 fixture ───────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_runs():
    """每个测试前后清空全局 RUNS 字典，防止测试间污染。"""
    with RUNS_LOCK:
        RUNS.clear()
    yield
    with RUNS_LOCK:
        RUNS.clear()


# ── RunSession dataclass ─────────────────────────────────


class TestRunSession:
    def test_defaults(self):
        s = RunSession(
            run_id="r1",
            url="https://x.com",
            scenario="test",
            run_dir="/tmp/r1",
            manifest_path="/tmp/m.json",
        )
        assert s.status == "queued"
        assert s.completed_at is None
        assert s.final_report is None
        assert s.error is None
        assert s.next_event_id == 1
        assert len(s.events) == 0

    def test_events_bounded(self):
        s = RunSession(run_id="r1", url="", scenario="", run_dir="", manifest_path="")
        for i in range(MAX_EVENTS + 50):
            s.events.append({"id": i})
        assert len(s.events) == MAX_EVENTS


# ── _read_json ───────────────────────────────────────────


class TestReadJson:
    def test_valid_file(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert _read_json(p) == {"key": "value"}

    def test_missing_file(self, tmp_path):
        assert _read_json(tmp_path / "nope.json") == {}

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        result = _read_json(p)
        assert "_error" in result


# ── _run_manifest_path / _run_report_path ────────────────


class TestPathHelpers:
    def test_manifest_path(self):
        result = _run_manifest_path("r1")
        assert result.name == "manifest.json"
        assert "r1" in str(result)

    def test_report_path(self):
        result = _run_report_path("r1")
        assert result.name == "report.md"
        assert "r1" in str(result)


# ── _latest_artifact_path ────────────────────────────────


class TestLatestArtifactPath:
    def test_finds_latest(self, tmp_path, monkeypatch):
        from webtestagent.config import settings

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)

        manifest_dir = tmp_path / "r1"
        manifest_dir.mkdir()
        manifest = manifest_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"type": "screenshot", "path": "/tmp/old.png"},
                        {"type": "screenshot", "path": "/tmp/new.png"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        # _latest_artifact_path reads manifest via _run_manifest_path which uses
        # the module-level OUTPUTS_DIR; we need to patch the helper instead
        with patch(
            "webtestagent.web.app_legacy._read_json",
            return_value={
                "artifacts": [
                    {"type": "screenshot", "path": "/tmp/old.png"},
                    {"type": "screenshot", "path": "/tmp/new.png"},
                ]
            },
        ):
            result = _latest_artifact_path("r1", "screenshot")
        assert result == "/tmp/new.png"

    def test_no_matching_artifact(self, tmp_path, monkeypatch):
        from webtestagent.config import settings

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)

        manifest_dir = tmp_path / "r1"
        manifest_dir.mkdir()
        manifest = manifest_dir / "manifest.json"
        manifest.write_text(
            '{"artifacts": [{"type": "snapshot", "path": "/tmp/s.yaml"}]}',
            encoding="utf-8",
        )

        result = _latest_artifact_path("r1", "screenshot")
        assert result is None

    def test_no_manifest(self, tmp_path, monkeypatch):
        from webtestagent.config import settings

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)
        result = _latest_artifact_path("nonexistent", "screenshot")
        assert result is None


# ── _session_snapshot ────────────────────────────────────


class TestSessionSnapshot:
    def test_basic_fields(self):
        s = RunSession(
            run_id="r1",
            url="https://x.com",
            scenario="test",
            run_dir="/tmp/r1",
            manifest_path="/tmp/m.json",
        )
        snap = _session_snapshot(s)
        assert snap["run_id"] == "r1"
        assert snap["url"] == "https://x.com"
        assert snap["status"] == "queued"
        assert snap["event_count"] == 0


# ── _get_session ─────────────────────────────────────────


class TestGetSession:
    def test_existing(self):
        s = RunSession(run_id="r1", url="", scenario="", run_dir="", manifest_path="")
        with RUNS_LOCK:
            RUNS["r1"] = s
        assert _get_session("r1") is s

    def test_missing(self):
        assert _get_session("nonexistent") is None


# ── _build_session_config ────────────────────────────────


class TestBuildSessionConfig:
    def test_defaults(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            config = _build_session_config({})
        assert config.auto_load is False
        assert config.auto_save is False

    def test_from_payload(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            config = _build_session_config(
                {"session": {"auto_load": True, "auto_save": True, "site_id": "x.com"}}
            )
        assert config.auto_load is True
        assert config.auto_save is True
        assert config.site_id == "x.com"

    def test_payload_overrides_defaults(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults",
            return_value={"auto_load": False, "site_id": "default.com"},
        ):
            config = _build_session_config(
                {"session": {"auto_load": True, "site_id": "override.com"}}
            )
        assert config.auto_load is True
        assert config.site_id == "override.com"


# ── configure_utf8_runtime ───────────────────────────────


class TestConfigureUtf8:
    def test_sets_env(self):
        configure_utf8_runtime()
        import os

        assert os.environ.get("PYTHONIOENCODING") == "utf-8"


# ── HTTP 路由集成测试 ────────────────────────────────────


class TestHTTPRoutes:
    """用真实 HTTP 服务器测试 API 路由。"""

    @pytest.fixture
    def server(self, tmp_path, monkeypatch):
        """启动真实 HTTP 服务器在随机可用端口。"""
        from http.server import ThreadingHTTPServer
        from webtestagent.config import settings

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)

        # Find a free port
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield server, port
        server.shutdown()

    def _get(self, port, path):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        return conn.getresponse()

    def _post(self, port, path, body: dict):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            path,
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        return conn.getresponse()

    def test_get_runs(self, server):
        _, port = server
        resp = self._get(port, "/api/runs")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert "runs" in data

    def test_get_defaults(self, server):
        _, port = server
        with (
            patch(
                "webtestagent.web.app_legacy.load_scenario",
                return_value="default scenario",
            ),
            patch("webtestagent.web.app_legacy.load_session_defaults", return_value={}),
            patch(
                "webtestagent.web.app_legacy.get_default_url",
                return_value="https://default.com",
            ),
        ):
            resp = self._get(port, "/api/defaults")
            assert resp.status == 200
            data = json.loads(resp.read())
            assert "default_url" in data

    def test_get_nonexistent_run_manifest(self, server):
        _, port = server
        resp = self._get(port, "/api/runs/nonexistent/manifest")
        assert resp.status == 404

    def test_get_nonexistent_run_report(self, server):
        _, port = server
        resp = self._get(port, "/api/runs/nonexistent/report")
        assert resp.status == 404

    def test_get_run_events_missing(self, server):
        _, port = server
        resp = self._get(port, "/api/runs/nonexistent/events")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["events"] == []

    def test_get_latest_screenshot_missing(self, server):
        _, port = server
        resp = self._get(port, "/api/runs/nonexistent/latest-screenshot")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["path"] is None

    def test_post_run_invalid_json(self, server):
        _, port = server
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/run",
            b"not json",
            {"Content-Type": "application/json", "Content-Length": "8"},
        )
        resp = conn.getresponse()
        assert resp.status == 400

    def test_404_for_unknown_path(self, server):
        _, port = server
        resp = self._get(port, "/api/unknown")
        assert resp.status == 404

    def test_manifest_and_report_endpoints(self, server, tmp_path, monkeypatch):
        _, port = server
        # Create a run directory with manifest and report
        # We need to patch _run_manifest_path and _run_report_path to use tmp_path
        run_dir = tmp_path / "r1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {"run_id": "r1", "target_url": "https://x.com", "artifacts": []}
            ),
            encoding="utf-8",
        )
        (run_dir / "report.md").write_text("# Report\nAll good!", encoding="utf-8")

        with (
            patch(
                "webtestagent.web.app_legacy._run_manifest_path",
                return_value=run_dir / "manifest.json",
            ),
            patch(
                "webtestagent.web.app_legacy._run_report_path",
                return_value=run_dir / "report.md",
            ),
        ):
            resp_manifest = self._get(port, "/api/runs/r1/manifest")
            assert resp_manifest.status == 200
            data = json.loads(resp_manifest.read())
            assert data["run_id"] == "r1"

            resp_report = self._get(port, "/api/runs/r1/report")
            assert resp_report.status == 200
            body = resp_report.read().decode("utf-8")
            assert "Report" in body


# ── API Key 认证 ────────────────────────────────────────


class TestApiKeyAuth:
    """测试 WEBAPP_API_KEY 认证机制。"""

    @pytest.fixture
    def server_with_key(self, tmp_path, monkeypatch):
        """启动带 API Key 的 HTTP 服务器。"""
        from http.server import ThreadingHTTPServer
        from webtestagent.config import settings
        import socket

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "webtestagent.web.app_legacy.WEBAPP_API_KEY", "test-secret-key"
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield server, port
        server.shutdown()

    @pytest.fixture
    def server_no_key(self, tmp_path, monkeypatch):
        """启动不带 API Key 的 HTTP 服务器。"""
        from http.server import ThreadingHTTPServer
        from webtestagent.config import settings
        import socket

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("webtestagent.web.app_legacy.WEBAPP_API_KEY", "")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield server, port
        server.shutdown()

    def test_no_key_always_passes(self, server_no_key):
        """未设置 API Key 时，/api/ 请求直接通过。"""
        _, port = server_no_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs")
        resp = conn.getresponse()
        assert resp.status == 200

    def test_api_key_in_header(self, server_with_key):
        """正确 Header X-API-Key 通过认证。"""
        _, port = server_with_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs", headers={"X-API-Key": "test-secret-key"})
        resp = conn.getresponse()
        assert resp.status == 200

    def test_api_key_in_query(self, server_with_key):
        """正确 query param ?key= 通过认证。"""
        _, port = server_with_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs?key=test-secret-key")
        resp = conn.getresponse()
        assert resp.status == 200

    def test_wrong_api_key_returns_401(self, server_with_key):
        """错误 API Key 返回 401。"""
        _, port = server_with_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs", headers={"X-API-Key": "wrong-key"})
        resp = conn.getresponse()
        assert resp.status == 401

    def test_no_api_key_returns_401(self, server_with_key):
        """缺少 API Key 返回 401。"""
        _, port = server_with_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs")
        resp = conn.getresponse()
        assert resp.status == 401

    def test_post_with_api_key(self, server_with_key):
        """POST 请求也需要 API Key — 通过 401 测试间接验证。"""
        _, port = server_with_key
        # 先验证无 key 返回 401
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/run",
            json.dumps({"url": "https://x.com"}).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 401

    def test_post_without_api_key_401(self, server_with_key):
        """POST 请求缺少 API Key 返回 401。"""
        _, port = server_with_key
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/run",
            json.dumps({"url": "https://x.com"}).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 401


# ── storage_dir 校验 ────────────────────────────────────


class TestStorageDirValidation:
    """测试 _build_session_config 中 storage_dir 的安全性校验。"""

    def test_absolute_path_rejected(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            with pytest.raises(ValueError, match="storage_dir must be a relative"):
                _build_session_config({"session": {"storage_dir": "/etc/passwd"}})

    def test_dotdot_rejected(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            with pytest.raises(ValueError, match="storage_dir must be a relative"):
                _build_session_config({"session": {"storage_dir": "../etc/passwd"}})

    def test_valid_relative_path(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            config = _build_session_config(
                {"session": {"storage_dir": "cookies/mysite"}}
            )
        assert config.storage_dir == Path("cookies/mysite")

    def test_no_storage_dir(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            config = _build_session_config({})
        assert config.storage_dir is None

    def test_empty_storage_dir(self):
        with patch(
            "webtestagent.web.app_legacy.load_session_defaults", return_value={}
        ):
            config = _build_session_config({"session": {"storage_dir": ""}})
        assert config.storage_dir is None


# ── 请求体大小限制 ──────────────────────────────────────


class TestBodySizeLimit:
    """测试 _read_json_body 的请求体大小限制。"""

    def test_oversized_body_rejected_unit(self):
        """直接测试 _read_json_body 抛 ValueError。"""
        # 构造一个 mock handler 来测试 _read_json_body

        handler = AppHandler.__new__(AppHandler)
        handler.headers = MagicMock()
        handler.headers.get.return_value = str(MAX_BODY_SIZE + 1)
        handler.rfile = MagicMock()

        with pytest.raises(ValueError, match="Request body too large"):
            handler._read_json_body()

    def test_normal_body_accepted_unit(self):
        """正常大小请求体正常解析。"""

        body = json.dumps({"url": "https://example.com"})
        handler = AppHandler.__new__(AppHandler)
        handler.headers = MagicMock()
        handler.headers.get.return_value = str(len(body))
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = body.encode("utf-8")

        result = handler._read_json_body()
        assert result == {"url": "https://example.com"}

    def test_empty_body(self):
        """空请求体返回空 dict。"""

        handler = AppHandler.__new__(AppHandler)
        handler.headers = MagicMock()
        handler.headers.get.return_value = "0"
        handler.rfile = MagicMock()

        result = handler._read_json_body()
        assert result == {}


# ── 更多 HTTP 路由 ──────────────────────────────────────


class TestMoreHTTPRoutes:
    """补充 HTTP 路由测试。"""

    @pytest.fixture
    def server(self, tmp_path, monkeypatch):
        from http.server import ThreadingHTTPServer
        from webtestagent.config import settings
        import socket

        monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield server, port
        server.shutdown()

    def test_get_root(self, server):
        """GET / 返回 index.html 或 404（如果 static 不存在）。"""
        _, port = server
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        # static/index.html 可能存在也可能不存在，但不应该 500
        assert resp.status in (200, 404)

    def test_post_non_api_run_404(self, server):
        """POST 非 /api/run 路径返回 404。"""
        _, port = server
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/other", b"{}", {"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 404

    def test_get_run_events_existing_session(self, server):
        """GET /api/runs/{id}/events 对已有 session 返回事件。"""
        _, port = server
        s = RunSession(
            run_id="r1",
            url="https://x.com",
            scenario="test",
            run_dir="/tmp/r1",
            manifest_path="/tmp/m.json",
        )
        s.events.append({"id": 1, "summary": "test event"})
        with RUNS_LOCK:
            RUNS["r1"] = s
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/runs/r1/events")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert len(data["events"]) == 1

    def test_get_latest_screenshot_existing_session(self, server):
        """GET /api/runs/{id}/latest-screenshot 对已有 session 返回路径。"""
        _, port = server
        s = RunSession(
            run_id="r1",
            url="https://x.com",
            scenario="test",
            run_dir="/tmp/r1",
            manifest_path="/tmp/m.json",
        )
        with RUNS_LOCK:
            RUNS["r1"] = s
        with patch(
            "webtestagent.web.app_legacy._latest_artifact_path",
            return_value="/tmp/screenshot.png",
        ):
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/runs/r1/latest-screenshot")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["path"] == "/tmp/screenshot.png"
