"""API 路由：/api/runs/* 和 /api/run。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from webtestagent.config.settings import OUTPUTS_DIR
from webtestagent.config.scenarios import (
    get_default_url,
    load_scenario,
    load_session_defaults,
)
from webtestagent.web.dependencies import (
    get_run_store,
    validate_run_id,
    verify_api_key,
)
from webtestagent.web.schemas import (
    DefaultsResponse,
    EventListResponse,
    LatestScreenshotResponse,
    RunCreatedResponse,
    RunListResponse,
    RunRequest,
    RunSnapshotResponse,
    SessionInfoResponse,
)
from webtestagent.web.services.run_store import RunStore, RunSession

runs_router = APIRouter()


# ── 辅助 ───────────────────────────────────────────────


def _session_to_snapshot(session: RunSession) -> RunSnapshotResponse:
    """将 RunSession 转为 RunSnapshotResponse（公开接口，替代 store._snapshot）。"""
    from webtestagent.web.services.run_store import _latest_artifact_path

    with session.condition:
        latest_screenshot = _latest_artifact_path(session.run_id, "screenshot")
        return RunSnapshotResponse(
            run_id=session.run_id,
            url=session.url,
            scenario=session.scenario,
            run_dir=session.run_dir,
            manifest_path=session.manifest_path,
            status=session.status,
            started_at=session.started_at,
            completed_at=session.completed_at,
            final_report=session.final_report,
            error=session.error,
            latest_screenshot=latest_screenshot,
            event_count=len(session.events),
        )


# ── GET /api/defaults ───────────────────────────────────


@runs_router.get(
    "/defaults",
    response_model=DefaultsResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_defaults() -> DefaultsResponse:
    scenario = load_scenario(None)
    session_defaults = load_session_defaults()
    return DefaultsResponse(
        default_url=get_default_url(),
        scenario=(
            scenario
            if isinstance(scenario, str)
            else json.dumps(scenario, ensure_ascii=False, indent=2)
        ),
        session=SessionInfoResponse(
            auto_load=bool(session_defaults.get("auto_load", False)),
            auto_save=bool(session_defaults.get("auto_save", False)),
            site_id=session_defaults.get("site_id") or "",
            account_id=session_defaults.get("account_id") or "",
        ),
    )


# ── GET /api/runs ──────────────────────────────────────


@runs_router.get(
    "/runs",
    response_model=RunListResponse,
    dependencies=[Depends(verify_api_key)],
)
async def list_runs(
    store: RunStore = Depends(get_run_store),
) -> RunListResponse:
    return RunListResponse(runs=store.list_snapshots())


# ── POST /api/run ──────────────────────────────────────


@runs_router.post(
    "/run",
    status_code=201,
    response_model=RunCreatedResponse,
    dependencies=[Depends(verify_api_key)],
)
async def create_run(
    req: RunRequest,
    store: RunStore = Depends(get_run_store),
) -> RunCreatedResponse:
    url = req.url or get_default_url()
    session_config = store.build_session_config(req.session)
    try:
        session = store.start_run(url, req.scenario, session_config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RunCreatedResponse(run=_session_to_snapshot(session))


# ── GET /api/runs/{run_id}/manifest ────────────────────


@runs_router.get(
    "/runs/{run_id}/manifest",
    dependencies=[Depends(verify_api_key)],
)
async def get_manifest(
    run_id: str = Depends(validate_run_id),
    store: RunStore = Depends(get_run_store),
) -> dict[str, Any]:
    manifest_path = OUTPUTS_DIR / run_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid manifest: {exc}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read manifest: {exc}")


# ── GET /api/runs/{run_id}/report ──────────────────────


@runs_router.get(
    "/runs/{run_id}/report",
    dependencies=[Depends(verify_api_key)],
)
async def get_report(
    run_id: str = Depends(validate_run_id),
    store: RunStore = Depends(get_run_store),
) -> str:
    report_path = OUTPUTS_DIR / run_id / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        return report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read report: {exc}")


# ── GET /api/runs/{run_id}/events ──────────────────────


@runs_router.get(
    "/runs/{run_id}/events",
    response_model=EventListResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_events(
    run_id: str = Depends(validate_run_id),
    store: RunStore = Depends(get_run_store),
) -> EventListResponse:
    session = store.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    with session.condition:
        return EventListResponse(
            events=list(session.events),
            status=session.status,
        )


# ── GET /api/runs/{run_id}/latest-screenshot ───────────


@runs_router.get(
    "/runs/{run_id}/latest-screenshot",
    response_model=LatestScreenshotResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_latest_screenshot(
    run_id: str = Depends(validate_run_id),
    store: RunStore = Depends(get_run_store),
) -> LatestScreenshotResponse:
    from webtestagent.web.services.run_store import _latest_artifact_path

    screenshot_path = _latest_artifact_path(run_id, "screenshot")
    return LatestScreenshotResponse(path=screenshot_path)


# ── GET /api/run/{run_id}/stream (SSE) ─────────────────


@runs_router.get(
    "/run/{run_id}/stream",
    dependencies=[Depends(verify_api_key)],
)
async def stream_run(
    run_id: str = Depends(validate_run_id),
    store: RunStore = Depends(get_run_store),
) -> EventSourceResponse:
    session = store.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    async def event_generator():
        async for event in store.stream_events(run_id):
            if event.get("event") == "keepalive":
                yield {"event": "keepalive", "data": ""}
            else:
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False),
                    "id": str(event.get("id", "")),
                }

    return EventSourceResponse(event_generator())

