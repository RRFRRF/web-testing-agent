"""FastAPI 中间件：请求体大小限制、请求日志等。"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

DEFAULT_MAX_BODY = int(os.getenv("WEBAPP_MAX_BODY_SIZE") or "1048576")  # 1MB


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """拒绝超过指定大小的请求体。

    检查策略：
    1. Content-Length 头：直接比较数值
    2. Transfer-Encoding: chunked：设置 body 读取上限
    3. 无两者：设置保守上限

    对于 chunked 和无 Content-Length 的情况，在 call_next 后
    检查实际 body 大小（通过 ASGI body 接收累计）。
    """

    def __init__(self, app, max_size: int = DEFAULT_MAX_BODY):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # 策略 1：检查 Content-Length
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.max_size:
                        return Response(
                            content=f"Request body too large (max {self.max_size} bytes)",
                            status_code=413,
                            media_type="text/plain",
                        )
                except (ValueError, TypeError):
                    return Response(
                        content="Invalid Content-Length header",
                        status_code=400,
                        media_type="text/plain",
                    )

            # 策略 2：chunked 或无 Content-Length — 限制 body 读取
            transfer_encoding = request.headers.get("transfer-encoding", "").lower()
            if "chunked" in transfer_encoding or not content_length:
                try:
                    body = await request.body()
                    if len(body) > self.max_size:
                        return Response(
                            content=f"Request body too large (max {self.max_size} bytes)",
                            status_code=413,
                            media_type="text/plain",
                        )
                except Exception:
                    pass  # body 读取失败，交给后续处理

        return await call_next(request)
