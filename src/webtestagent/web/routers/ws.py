"""WebSocket 路由：实时双向通信（事件推送 + 控制指令）。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from webtestagent.web.dependencies import verify_api_key_ws, WebSocketAuthError
from webtestagent.web.services.run_store import RunStore, _TERMINAL_STATES

if TYPE_CHECKING:
    from webtestagent.web.services.run_store import RunSession

ws_router = APIRouter()


@ws_router.websocket("/ws/run/{run_id}")
async def run_websocket(
    websocket: WebSocket,
    run_id: str,
) -> None:
    """WebSocket 端点：实时推送 run 事件 + 接收控制指令。

    协议：
    - 服务端 → 客户端: JSON 事件消息 {"id": N, "channel": "...", ...}
    - 客户端 → 服务端: JSON 控制指令 {"action": "cancel"} / {"action": "ping"}
    - 服务端 → 客户端: {"event": "pong"} 响应 ping
    """
    # API Key 认证
    try:
        await verify_api_key_ws(websocket)
    except WebSocketAuthError:
        return

    await websocket.accept()

    store: RunStore = websocket.app.state.run_store
    session: RunSession | None = store.get_session(run_id)

    if session is None:
        await websocket.send_json({"error": f"Run {run_id} not found"})
        await websocket.close()
        return

    # 双任务：推送事件 + 接收指令
    push_task = asyncio.create_task(_push_events(websocket, store, run_id))
    recv_task = asyncio.create_task(
        _receive_commands(websocket, store, session, run_id)
    )

    try:
        done, pending = await asyncio.wait(
            {push_task, recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _push_events(websocket: WebSocket, store: RunStore, run_id: str) -> None:
    """持续推送 run 事件到客户端。"""
    async for event in store.stream_events(run_id):
        if event.get("event") == "keepalive":
            await websocket.send_json({"event": "keepalive"})
            continue
        await websocket.send_json(event)


async def _receive_commands(
    websocket: WebSocket, store: RunStore, session: RunSession, run_id: str
) -> None:
    """接收客户端控制指令。"""
    while True:
        try:
            data = await websocket.receive_json()
        except WebSocketDisconnect:
            return

        action = data.get("action")
        if action == "cancel":
            with session.condition:
                if session.status not in _TERMINAL_STATES:
                    session.status = "cancelled"
                    session.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                    session.condition.notify_all()
            await websocket.send_json({"event": "cancelled", "run_id": run_id})
        elif action == "ping":
            await websocket.send_json({"event": "pong"})
        elif action == "get_status":
            snapshot = store.snapshot(session)
            await websocket.send_json(
                {"event": "status", "data": snapshot.model_dump()}
            )
