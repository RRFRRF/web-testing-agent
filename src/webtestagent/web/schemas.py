"""Pydantic models for the single-run web demo."""

from __future__ import annotations

import ntpath
import posixpath
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SessionConfigRequest(BaseModel):
    auto_load: bool | None = None
    auto_save: bool | None = None
    site_id: str | None = None
    account_id: str | None = None
    storage_dir: str | None = None

    @field_validator("storage_dir")
    @classmethod
    def validate_storage_dir(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        path = Path(normalized)
        if (
            posixpath.isabs(normalized)
            or ntpath.isabs(normalized)
            or ".." in path.parts
        ):
            raise ValueError(
                f"storage_dir must be a relative path without '..': {normalized}"
            )
        return normalized


class RunRequest(BaseModel):
    url: str = Field(default="", description="Target URL")
    scenario: str | None = Field(default=None, description="Scenario text or JSON steps")
    session: SessionConfigRequest | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {value!r}")
        return value


class CurrentRunResponse(BaseModel):
    status: str
    run_id: str | None = None
    run_dir: str | None = None
    manifest_path: str | None = None
    url: str = ""
    scenario_input: str = ""
    latest_screenshot: str | None = None
    logs: list[dict[str, Any]] = Field(default_factory=list)
    final_report: str | None = None
    error: str | None = None
    updated_at: str
