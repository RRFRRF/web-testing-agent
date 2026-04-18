"""Single-run in-memory state for the web demo."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from webtestagent.config.scenarios import (
    get_default_scenario_input,
    get_default_url,
    load_scenario,
    load_session_defaults,
)
from webtestagent.config.settings import now_iso
from webtestagent.core.runner import PreparedRun, execute_prepared_run, prepare_run
from webtestagent.core.session import SessionPersistenceConfig


def _read_manifest_data(manifest_path: str | None) -> dict[str, Any]:
    if not manifest_path:
        return {}
    path = Path(manifest_path)
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _manifest_artifacts(manifest_path: str | None) -> list[dict[str, Any]]:
    data = _read_manifest_data(manifest_path)
    artifacts = data.get("artifacts") or []
    if not isinstance(artifacts, list):
        return []
    return [item for item in artifacts if isinstance(item, dict)]


def _artifact_path(manifest_path: str | None, artifact_type: str) -> str | None:
    for item in reversed(_manifest_artifacts(manifest_path)):
        if item.get("type") == artifact_type:
            saved_path = item.get("path")
            if isinstance(saved_path, str) and saved_path:
                return saved_path
    return None


def artifact_summary(state: "CurrentRunState") -> dict[str, Any]:
    report_path = _artifact_path(state.manifest_path, "report")
    test_script_path = _artifact_path(state.manifest_path, "playwright-test")
    latest_screenshot = _latest_screenshot_path(state.manifest_path)
    return {
        "manifest_path": state.manifest_path,
        "run_dir": state.run_dir,
        "latest_screenshot": latest_screenshot,
        "report_path": report_path,
        "test_script_path": test_script_path,
        "has_report": bool(report_path),
        "has_script": bool(test_script_path),
    }


def script_payload(state: "CurrentRunState") -> dict[str, Any]:
    test_script_path = _artifact_path(state.manifest_path, "playwright-test")
    if not test_script_path:
        return {"path": None, "content": None, "has_script": False}

    try:
        content = Path(test_script_path).read_text(encoding="utf-8")
    except OSError:
        content = None
    return {
        "path": test_script_path,
        "content": content,
        "has_script": True,
    }


@dataclass
class CurrentRunState:
    status: str = "idle"
    run_id: str | None = None
    run_dir: str | None = None
    manifest_path: str | None = None
    url: str = field(default_factory=get_default_url)
    scenario_input: str = field(default_factory=get_default_scenario_input)
    latest_screenshot: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    final_report: str | None = None
    error: str | None = None
    updated_at: str = field(default_factory=now_iso)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            summary = artifact_summary(self)
            return {
                "status": self.status,
                "run_id": self.run_id,
                "run_dir": self.run_dir,
                "manifest_path": self.manifest_path,
                "url": self.url,
                "scenario_input": self.scenario_input,
                "latest_screenshot": summary["latest_screenshot"],
                "logs": list(self.logs),
                "final_report": self.final_report,
                "error": self.error,
                "updated_at": self.updated_at,
                "report_path": summary["report_path"],
                "test_script_path": summary["test_script_path"],
                "has_script": summary["has_script"],
                "has_report": summary["has_report"],
            }

    def reset(self) -> None:
        with self.lock:
            self.status = "idle"
            self.run_id = None
            self.run_dir = None
            self.manifest_path = None
            self.url = get_default_url()
            self.scenario_input = get_default_scenario_input()
            self.latest_screenshot = None
            self.logs = []
            self.final_report = None
            self.error = None
            self.updated_at = now_iso()


@dataclass(frozen=True)
class RunReservation:
    url: str
    scenario_input: str
    session_payload: dict[str, Any] | None


def _latest_artifact_path(manifest_path: str | None, artifact_type: str) -> str | None:
    if not manifest_path:
        return None
    path = Path(manifest_path)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    artifacts = data.get("artifacts") or []
    if not isinstance(artifacts, list):
        return None

    for item in reversed(artifacts):
        if isinstance(item, dict) and item.get("type") == artifact_type:
            saved_path = item.get("path")
            if isinstance(saved_path, str) and saved_path:
                return saved_path
    return None


def _latest_screenshot_path(manifest_path: str | None) -> str | None:
    if not manifest_path:
        return None
    path = Path(manifest_path)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    artifacts = data.get("artifacts") or []
    if not isinstance(artifacts, list):
        return None

    for item in reversed(artifacts):
        if isinstance(item, dict) and item.get("type") in {
            "screenshot",
            "trace-screenshot",
        }:
            saved_path = item.get("path")
            if isinstance(saved_path, str) and saved_path:
                return saved_path
    return None


def build_session_config(
    session_payload: dict[str, Any] | None,
) -> SessionPersistenceConfig:
    defaults = load_session_defaults()
    payload = session_payload or {}
    storage_dir = payload.get("storage_dir") or defaults.get("storage_dir")

    return SessionPersistenceConfig(
        auto_load=bool(
            payload.get("auto_load")
            if payload.get("auto_load") is not None
            else defaults.get("auto_load", False)
        ),
        auto_save=bool(
            payload.get("auto_save")
            if payload.get("auto_save") is not None
            else defaults.get("auto_save", False)
        ),
        site_id=payload.get("site_id") or defaults.get("site_id") or None,
        account_id=payload.get("account_id") or defaults.get("account_id") or None,
        storage_dir=Path(storage_dir) if storage_dir else None,
    )


def reserve_run(
    state: CurrentRunState,
    *,
    url: str,
    scenario_input: str,
    session_payload: dict[str, Any] | None,
) -> RunReservation:
    with state.lock:
        if state.status in {"preparing", "running"}:
            raise RuntimeError("A run is already running")
        state.status = "preparing"
        state.run_id = None
        state.run_dir = None
        state.manifest_path = None
        state.url = url
        state.scenario_input = scenario_input
        state.latest_screenshot = None
        state.logs = []
        state.final_report = None
        state.error = None
        state.updated_at = now_iso()
    return RunReservation(
        url=url,
        scenario_input=scenario_input,
        session_payload=session_payload,
    )


def release_reservation(state: CurrentRunState) -> None:
    with state.lock:
        if state.status == "preparing":
            state.reset()


def start_run(
    state: CurrentRunState,
    *,
    url: str,
    scenario_input: str,
    session_payload: dict[str, Any] | None,
) -> PreparedRun:
    prepared = prepare_run(
        url,
        load_scenario(scenario_input.strip() or None),
        session_config=build_session_config(session_payload),
    )
    with state.lock:
        state.status = "running"
        state.run_id = prepared.run_context.run_id
        state.run_dir = prepared.run_context.run_dir.as_posix()
        state.manifest_path = prepared.run_context.manifest_path.as_posix()
        state.url = prepared.url
        state.scenario_input = scenario_input
        state.latest_screenshot = None
        state.logs = []
        state.final_report = None
        state.error = None
        state.updated_at = now_iso()
    return prepared


def append_event(state: CurrentRunState, event: dict[str, Any]) -> None:
    with state.lock:
        state.logs.append(event)
        state.latest_screenshot = _latest_screenshot_path(state.manifest_path)
        state.updated_at = now_iso()


def complete_run(state: CurrentRunState, final_report: str) -> None:
    with state.lock:
        state.status = "completed"
        state.final_report = final_report
        state.latest_screenshot = _latest_screenshot_path(state.manifest_path)
        state.updated_at = now_iso()


def fail_run(state: CurrentRunState, error: str) -> None:
    with state.lock:
        state.status = "failed"
        state.error = error
        state.latest_screenshot = _latest_screenshot_path(state.manifest_path)
        state.updated_at = now_iso()


def run_worker(state: CurrentRunState, prepared: PreparedRun) -> None:
    try:
        result = execute_prepared_run(
            prepared,
            on_event=lambda event: append_event(state, event),
        )
        complete_run(state, result.final_report)
    except Exception as exc:
        fail_run(state, str(exc))
