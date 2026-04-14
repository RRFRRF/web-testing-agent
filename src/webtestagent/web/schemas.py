"""Pydantic 请求/响应模型：Web API 的数据校验与序列化。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


# ── 请求模型 ────────────────────────────────────────────


class SessionConfigRequest(BaseModel):
    """POST /api/run 中 session 配置的请求模型。"""

    auto_load: bool = False
    auto_save: bool = False
    site_id: str | None = None
    account_id: str | None = None
    storage_dir: str | None = None

    @field_validator("storage_dir")
    @classmethod
    def validate_storage_dir(cls, v: str | None) -> str | None:
        """校验 storage_dir：必须是相对路径且不含 .."""
        if v is not None and v != "":
            p = Path(v)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(
                    f"storage_dir must be a relative path without '..': {v}"
                )
        return v if v else None


class RunRequest(BaseModel):
    """POST /api/run 请求模型。"""

    url: str = Field(default="", description="目标测试 URL")
    scenario: str | None = Field(default=None, description="测试场景描述")
    session: SessionConfigRequest | None = Field(
        default=None, description="会话持久化配置"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """URL 如果非空，必须以 http:// 或 https:// 开头。"""
        v = v.strip()
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {v!r}")
        return v


# ── 响应模型 ────────────────────────────────────────────


class SessionInfoResponse(BaseModel):
    """响应中的 session 信息。"""

    auto_load: bool = False
    auto_save: bool = False
    site_id: str = ""
    account_id: str = ""


class DefaultsResponse(BaseModel):
    """GET /api/defaults 响应模型。"""

    default_url: str
    scenario: str
    session: SessionInfoResponse


class RunSnapshotResponse(BaseModel):
    """单个 run 的快照信息。"""

    run_id: str
    url: str
    scenario: str
    run_dir: str
    manifest_path: str
    status: str
    started_at: str
    completed_at: str | None = None
    final_report: str | None = None
    error: str | None = None
    latest_screenshot: str | None = None
    event_count: int = 0


class RunListResponse(BaseModel):
    """GET /api/runs 响应模型。"""

    runs: list[RunSnapshotResponse] = Field(default_factory=list)


class RunCreatedResponse(BaseModel):
    """POST /api/run 201 响应模型。"""

    run: RunSnapshotResponse


class EventListResponse(BaseModel):
    """GET /api/runs/{id}/events 响应模型。"""

    events: list[dict] = Field(default_factory=list)
    status: str = ""


class LatestScreenshotResponse(BaseModel):
    """GET /api/runs/{id}/latest-screenshot 响应模型。"""

    path: str | None = None


class ErrorResponse(BaseModel):
    """错误响应模型。"""

    error: str
