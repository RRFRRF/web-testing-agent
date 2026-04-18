"""测试 web/api.py：FastAPI 单 run 应用路由、Schema 校验、依赖行为。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from webtestagent.web.api import create_app
from webtestagent.web.schemas import RunRequest, SessionConfigRequest
from webtestagent.web.state import CurrentRunState, build_session_config, reserve_run


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app():
    application = create_app()
    application.state.current_run = CurrentRunState()
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSchemas:
    def test_run_request_valid(self):
        req = RunRequest(url="https://example.com", scenario="test login")
        assert req.url == "https://example.com"

    def test_run_request_empty_url(self):
        req = RunRequest(url="")
        assert req.url == ""

    def test_run_request_invalid_url(self):
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


class TestStateHelpers:
    def test_build_session_config_defaults(self):
        with patch(
            "webtestagent.web.state.load_session_defaults",
            return_value={},
        ):
            config = build_session_config(None)
        assert config.auto_load is False
        assert config.auto_save is False

    def test_build_session_config_uses_defaults_for_missing_fields(self):
        req = SessionConfigRequest()
        with patch(
            "webtestagent.web.state.load_session_defaults",
            return_value={
                "auto_load": True,
                "auto_save": True,
                "site_id": "site-a",
                "account_id": "acc-a",
                "storage_dir": "cookies/default-site",
            },
        ):
            config = build_session_config(req.model_dump())
        assert config.auto_load is True
        assert config.auto_save is True
        assert config.site_id == "site-a"
        assert config.account_id == "acc-a"
        assert config.storage_dir == Path("cookies/default-site")

    def test_reserve_run_rejects_when_running(self, app):
        state = app.state.current_run
        state.status = "running"

        with pytest.raises(RuntimeError, match="already running"):
            reserve_run(
                state,
                url="https://example.com",
                scenario_input="x",
                session_payload=None,
            )


class TestAPIRoutes:
    @pytest.mark.anyio
    async def test_get_state(self, client):
        resp = await client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["run_id"] is None

    @pytest.mark.anyio
    async def test_post_run_returns_error_detail_when_start_fails(self, client):
        with patch(
            "webtestagent.web.api.start_run",
            side_effect=RuntimeError("prepare failed"),
        ):
            resp = await client.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "x"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "prepare failed"

    @pytest.mark.anyio
    async def test_outputs_route_exists_even_when_missing_file(self, client):
        resp = await client.get("/outputs/nonexistent.png")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_openapi_docs_available(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_openapi_json_available(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "WebTestAgent Demo"
        assert "/api/run" in data["paths"]
        assert "/api/state" in data["paths"]
        assert "/api/reset" in data["paths"]

    @pytest.mark.anyio
    async def test_post_run_conflicts_when_running(self, app):
        app.state.current_run.status = "running"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/run",
                json={"url": "https://example.com", "scenario": "x"},
            )
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_reset_rejects_running_state(self, app):
        app.state.current_run.status = "running"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/reset")
        assert resp.status_code == 409


class TestBodySizeMiddleware:
    @pytest.mark.anyio
    async def test_normal_get_accepted(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/state")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_oversized_post_rejected(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            big_body = "x" * (2 * 1024 * 1024)
            resp = await c.post(
                "/api/run",
                content=big_body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 413
