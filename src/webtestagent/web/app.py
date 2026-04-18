"""Compatibility entrypoint for the current FastAPI single-run web demo."""

from __future__ import annotations

from webtestagent.web.api import create_app, serve  # noqa: F401
