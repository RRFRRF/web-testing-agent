"""向后兼容代理：旧入口 webtestagent.web.app 现在委托给 FastAPI 版本。

迁移指南：
  - 旧: from webtestagent.web.app import serve, AppHandler
  - 新: from webtestagent.web.api import create_app, serve
  - CLI: webtestagent-web → webtestagent-api（两者等价）
"""

from __future__ import annotations

import warnings

from webtestagent.web.api import create_app, serve  # noqa: F401

warnings.warn(
    "webtestagent.web.app is deprecated; use webtestagent.web.api instead. "
    "The legacy http.server handler has been replaced by FastAPI.",
    DeprecationWarning,
    stacklevel=2,
)
