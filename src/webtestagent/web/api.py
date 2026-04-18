"""Minimal FastAPI app for the single-run web demo."""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from webtestagent.config.scenarios import get_default_url
from webtestagent.config.settings import OUTPUTS_DIR, configure_utf8_runtime, init_env
from webtestagent.web.middleware import MaxBodySizeMiddleware
from webtestagent.web.schemas import CurrentRunResponse, RunRequest
from webtestagent.web.state import (
    CurrentRunState,
    release_reservation,
    reserve_run,
    run_worker,
    start_run,
)

WEB_STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.getenv("WEBAPP_PORT") or "8765")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.current_run = CurrentRunState()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="WebTestAgent Demo",
        description="Single-run visual demo for the current WebTestAgent MVP",
        version="0.3.0",
        lifespan=lifespan,
    )

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MaxBodySizeMiddleware)

    @app.get("/api/state", response_model=CurrentRunResponse)
    async def get_state() -> CurrentRunResponse:
        return CurrentRunResponse(**app.state.current_run.snapshot())

    @app.post("/api/run", status_code=201, response_model=CurrentRunResponse)
    async def post_run(req: RunRequest) -> CurrentRunResponse:
        state = app.state.current_run
        url = req.url or get_default_url()
        try:
            reservation = reserve_run(
                state,
                url=url,
                scenario_input=req.scenario or "",
                session_payload=req.session.model_dump() if req.session else None,
            )
        except RuntimeError as exc:
            if str(exc) == "A run is already running":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        try:
            prepared = start_run(
                state,
                url=reservation.url,
                scenario_input=reservation.scenario_input,
                session_payload=reservation.session_payload,
            )
        except RuntimeError as exc:
            release_reservation(state)
            if str(exc) == "A run is already running":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            release_reservation(state)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        thread = threading.Thread(target=run_worker, args=(state, prepared), daemon=True)
        thread.start()
        return CurrentRunResponse(**state.snapshot())

    @app.post("/api/reset", response_model=CurrentRunResponse)
    async def post_reset() -> CurrentRunResponse:
        state = app.state.current_run
        with state.lock:
            if state.status == "running":
                raise HTTPException(
                    status_code=409, detail="Cannot reset while a run is running"
                )
            state.reset()
        return CurrentRunResponse(**state.snapshot())

    app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR, html=False), name="outputs")
    if WEB_STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="static")

    return app


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    import uvicorn

    configure_utf8_runtime()
    init_env()
    print(f"[web] 控制台已启动: http://{host}:{port}")
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
