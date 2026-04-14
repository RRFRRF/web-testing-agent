"""FastAPI 应用工厂：Web 控制台入口。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from webtestagent.config.settings import OUTPUTS_DIR, configure_utf8_runtime, init_env
from webtestagent.web.middleware import MaxBodySizeMiddleware
from webtestagent.web.routers.runs import runs_router
from webtestagent.web.routers.ws import ws_router
from webtestagent.web.services.run_store import RunStore

WEB_STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.getenv("WEBAPP_PORT") or "8765")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：startup 初始化 RunStore，shutdown 等待活跃 run 完成。"""
    app.state.run_store = RunStore()
    yield
    await app.state.run_store.graceful_shutdown()


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="WebTestAgent",
        description="AI-powered Web Automation Testing Agent API",
        version="0.2.0",
        lifespan=lifespan,
    )

    # 中间件按添加逆序执行：
    # 1. MaxBodySizeMiddleware 先执行（后添加）— 拒绝超大请求
    # 2. CORSMiddleware 后执行（先添加）— 给所有响应加 CORS 头（包括 413）
    cors_origins = os.getenv("WEBAPP_CORS_ORIGINS", "*").strip()
    if not cors_origins:
        cors_origins = "*"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MaxBodySizeMiddleware)

    # API 路由
    app.include_router(runs_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")

    # 静态文件（outputs 目录浏览）
    if OUTPUTS_DIR.exists():
        app.mount(
            "/outputs", StaticFiles(directory=OUTPUTS_DIR, html=False), name="outputs"
        )

    # 前端静态文件（最后挂载，作为 fallback）
    if WEB_STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="static")

    return app


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """CLI 入口：启动 Uvicorn 服务器。"""
    import uvicorn

    # 环境初始化在 uvicorn fork 之前完成
    configure_utf8_runtime()
    init_env()
    print(f"[web] 控制台已启动: http://{host}:{port}")
    print(f"[web] API 文档: http://{host}:{port}/docs")
    print(f"[web] outputs 目录: {OUTPUTS_DIR.as_posix()}")
    uvicorn.run(
        "webtestagent.web.api:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    serve()
