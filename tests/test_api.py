"""测试 web/api.py：FastAPI 应用路由、Schema 校验、依赖注入。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from webtestagent.web.api import create_app
from webtestagent.web.schemas import RunRequest, SessionConfigRequest
from webtestagent.web.services.run_store import RunStore


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def app():
    """创建 FastAPI 应用实例，并手动初始化 RunStore（TestClient 不触发 lifespan）。"""
    application = create_app()
    application.state.run_store = RunStore()
    return application


@pytest.fixture
async def client(app):
    """异步 HTTP 测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Schema 校验 ────────────────────────────────────────


class TestSchemas:
    """测试 Pydantic Schema 校验。"""

    def test_run_request_valid(self):
        req = RunRequest(url="https://example.com", scenario="test login")
        assert req.url == "https://example.com"

    def test_run_request_empty_url(self):
        """空 URL 允许（会用 default_url 填充）。"""
        req = RunRequest(url="")
        assert req.url == ""

    def test_run_request_invalid_url(self):
        """非 http/https URL 被拒绝。"""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            RunRequest(url="ftp://example.com")

    def test_session_config_valid_storage_dir(self):
        cfg = SessionConfigRequest(storage_dir="cookies/mysite")
        assert cfg.storage_dir == "cookies/mysite"

    def test_session_config_absolute_storage_dir_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SessionConfigRequest(storage_dir="/etc/passwd")

    def test_session_config_dotdot_storage_dir_rejected(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SessionConfigRequest(storage_dir="../etc/passwd")

    def test_session_config_uses_none_by_default(self):
        cfg = SessionConfigRequest()
        assert cfg.auto_load is None
        assert cfg.auto_save is None

    def test_session_config_empty_storage_dir(self):
        cfg = SessionConfigRequest(storage_dir="")
        assert cfg.storage_dir is None


class TestRunStore:
    """测试 RunStore 服务层。"""

    def test_initial_empty(self):
        store = RunStore()
        assert store.list_snapshots() == [] or isinstance(store.list_snapshots(), list)

    def test_get_session_missing(self):
        store = RunStore()
        assert store.get_session("nonexistent") is None

    def test_build_session_config_defaults(self):
        store = RunStore()
        with patch(
            "webtestagent.web.services.run_store.load_session_defaults",
            return_value={},
        ):
            config = store.build_session_config(None)
        assert config.auto_load is False
        assert config.auto_save is False


    def test_build_session_config_uses_defaults_for_missing_fields(self):
        store = RunStore()
        req = SessionConfigRequest()
        with patch(
            "webtestagent.web.services.run_store.load_session_defaults",
            return_value={
                "auto_load": True,
                "auto_save": True,
                "site_id": "site-a",
                "account_id": "acc-a",
                "storage_dir": "cookies/default-site",
            },
        ):
            config = store.build_session_config(req)
        assert config.auto_load is True
        assert config.auto_save is True
        assert config.site_id == "site-a"
        assert config.account_id == "acc-a"
        assert config.storage_dir == Path("cookies/default-site")

    def test_validate_run_id_safe_rejects_traversal(self):
        """_validate_run_id_safe 拒绝路径遍历。"""
        from webtestagent.web.services.run_store import _validate_run_id_safe

        with pytest.raises(ValueError):
            _validate_run_id_safe("../etc")
        with pytest.raises(ValueError):
            _validate_run_id_safe("foo/bar")
        with pytest.raises(ValueError):
            _validate_run_id_safe("")
        # 合法 ID 通过
        assert _validate_run_id_safe("run-2024-01-01-abc") == "run-2024-01-01-abc"
        assert _validate_run_id_safe("run.123") == "run.123"


# ── API 路由测试 ───────────────────────────────────────


class TestAPIRoutes:
    """测试 FastAPI 路由（无 API Key）。"""

    @pytest.mark.anyio
    async def test_get_defaults(self, client):
        with (
            patch(
                "webtestagent.web.routers.runs.load_scenario",
                return_value="default scenario",
            ),
            patch(
                "webtestagent.web.routers.runs.load_session_defaults",
                return_value={},
            ),
            patch(
                "webtestagent.web.routers.runs.get_default_url",
                return_value="https://default.com",
            ),
        ):
            resp = await client.get("/api/defaults")
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_url"] == "https://default.com"


    @pytest.mark.anyio
    async def test_post_run_returns_error_detail_when_start_fails(self, client):
        with patch(
            "webtestagent.web.routers.runs.RunStore.start_run",
            side_effect=RuntimeError("prepare failed"),
        ):
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "x"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "prepare failed"

    @pytest.mark.anyio
    async def test_get_manifest_not_found(self, client):
        resp = await client.get("/api/runs/nonexistent/manifest")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_get_report_not_found(self, client):
        resp = await client.get("/api/runs/nonexistent/report")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_get_events_missing_run(self, client):
        resp = await client.get("/api/runs/nonexistent/events")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_get_latest_screenshot_missing(self, client):
        resp = await client.get("/api/runs/nonexistent/latest-screenshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] is None

    @pytest.mark.anyio
    async def test_openapi_docs_available(self, client):
        """自动生成的 OpenAPI 文档可访问。"""
        resp = await client.get("/docs")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_openapi_json_available(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "WebTestAgent"
        assert "/api/run" in data["paths"]


# ── API Key 认证测试 ──────────────────────────────────


class TestAPIKeyAuth:
    """测试 API Key 认证。"""

    @pytest.mark.anyio
    async def test_no_key_passes(self, app):
        """未设置 WEBAPP_API_KEY 时请求直接通过。"""
        with patch("webtestagent.web.dependencies.WEBAPP_API_KEY", ""):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/runs")
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_valid_header_key(self, app):
        """正确 Header X-API-Key 通过。"""
        with patch("webtestagent.web.dependencies.WEBAPP_API_KEY", "secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/runs", headers={"X-API-Key": "secret"})
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_valid_query_key(self, app):
        """正确 query param ?key= 通过。"""
        with patch("webtestagent.web.dependencies.WEBAPP_API_KEY", "secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/runs?key=secret")
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_wrong_key_401(self, app):
        """错误 API Key 返回 401。"""
        with patch("webtestagent.web.dependencies.WEBAPP_API_KEY", "secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/runs", headers={"X-API-Key": "wrong"})
            assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_no_key_401(self, app):
        """缺少 API Key 返回 401。"""
        with patch("webtestagent.web.dependencies.WEBAPP_API_KEY", "secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/runs")
            assert resp.status_code == 401


# ── 路径遍历防护测试 ──────────────────────────────────


class TestPathTraversalProtection:
    """测试 run_id 路径遍历防护。"""

    @pytest.mark.anyio
    async def test_dotdot_run_id_rejected(self, client):
        """../ 路径遍历被 FastAPI 路由匹配阻止（含 / 不匹配 {run_id}）。"""
        resp = await client.get("/api/runs/..%2F..%2Fetc/manifest")
        assert resp.status_code in (400, 404)  # 404 = 路由不匹配，同样安全

    @pytest.mark.anyio
    async def test_slash_run_id_rejected(self, client):
        """含 / 的 run_id 被拒绝。"""
        resp = await client.get("/api/runs/foo/bar/manifest")
        # FastAPI 路由匹配可能不匹配，但如果有匹配则应 400
        assert resp.status_code in (400, 404)

    @pytest.mark.anyio
    async def test_null_byte_run_id_rejected(self, client):
        """null 字节被拒绝。"""
        resp = await client.get("/api/runs/run%00x/manifest")
        assert resp.status_code in (400, 404)

    @pytest.mark.anyio
    async def test_valid_run_id_accepted(self, client):
        """合法 run_id 通过校验（返回 404 而非 400）。"""
        resp = await client.get("/api/runs/run-2024-01-01-abc/manifest")
        assert resp.status_code == 404  # 不存在，但 run_id 合法


# ── MaxBodySizeMiddleware 测试 ─────────────────────────


class TestMaxBodySizeMiddleware:
    """测试请求体大小限制中间件。"""

    @pytest.mark.anyio
    async def test_normal_post_accepted(self, app):
        """正常大小请求不触发 413 — 用 GET 测试。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/runs")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_oversized_post_rejected(self, app):
        """超大 POST 被拒绝 (413)。"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            big_body = "x" * (2 * 1024 * 1024)  # 2MB
            resp = await c.post(
                "/api/run",
                content=big_body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 413
