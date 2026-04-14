"""FastAPI 依赖注入：API Key 认证、RunStore 获取、路径安全校验。"""

from __future__ import annotations

import os
import re

from fastapi import Header, Query, Request, WebSocket
from fastapi.exceptions import HTTPException

from webtestagent.web.services.run_store import RunStore

WEBAPP_API_KEY = os.getenv("WEBAPP_API_KEY")

# run_id 合法模式：仅允许字母、数字、连字符、下划线、点
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_run_id(run_id: str) -> str:
    """校验 run_id 安全性：拒绝路径遍历字符。

    Returns 校验后的 run_id。
    Raises HTTPException 400 如果 run_id 包含非法字符。
    """
    if not run_id or not _RUN_ID_PATTERN.match(run_id):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid run_id: {run_id!r}. Only alphanumeric, hyphens, underscores, and dots are allowed.",
        )
    return run_id


async def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    key: str | None = Query(None, alias="key"),
) -> None:
    """API Key 认证依赖。未配置 WEBAPP_API_KEY 时始终通过。

    支持两种方式：
    - Header: X-API-Key: <key>
    - Query: ?key=<key>
    """
    if not WEBAPP_API_KEY:
        return
    if x_api_key == WEBAPP_API_KEY or key == WEBAPP_API_KEY:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


def get_run_store(request: Request) -> RunStore:
    """从 app.state 获取 RunStore 实例。"""
    return request.app.state.run_store


class WebSocketAuthError(Exception):
    """WebSocket 认证失败异常。"""


async def verify_api_key_ws(websocket: WebSocket) -> None:
    """WebSocket API Key 认证。从 query param ?key= 获取。

    Raises WebSocketAuthError 如果认证失败。
    """
    if not WEBAPP_API_KEY:
        return
    key = websocket.query_params.get("key")
    if key == WEBAPP_API_KEY:
        return
    await websocket.close(code=4001, reason="Unauthorized")
    raise WebSocketAuthError("Unauthorized")
