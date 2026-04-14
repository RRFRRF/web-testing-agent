"""最小网页控制台：启动测试、查看事件流、报告与 artifacts。"""
from __future__ import annotations

import json
import locale
import mimetypes
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from webtestagent.config.settings import OUTPUTS_DIR, PROJECT_ROOT, init_env, parse_bool
from webtestagent.config.scenarios import get_default_url, load_scenario, load_session_defaults
from webtestagent.core.runner import PreparedRun, prepare_run, execute_prepared_run
from webtestagent.core.session import SessionPersistenceConfig

WEB_STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.getenv("WEBAPP_PORT") or "8765")
MAX_EVENTS = 500


@dataclass
class RunSession:
    run_id: str
    url: str
    scenario: str
    run_dir: str
    manifest_path: str
    status: str = "queued"
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    completed_at: str | None = None
    final_report: str | None = None
    error: str | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    next_event_id: int = 1
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))


RUNS: dict[str, RunSession] = {}
RUNS_LOCK = threading.RLock()


def configure_utf8_runtime() -> None:
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    if hasattr(locale, "getpreferredencoding"):
        locale.getpreferredencoding = lambda do_setlocale=True: "utf-8"  # type: ignore[assignment]
    if hasattr(locale, "getencoding"):
        locale.getencoding = lambda: "utf-8"  # type: ignore[assignment]
    if hasattr(subprocess, "_text_encoding"):
        subprocess._text_encoding = lambda: "utf-8"  # type: ignore[attr-defined]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_error": f"Invalid JSON in {path.name}: {exc}"}


def _run_manifest_path(run_id: str) -> Path:
    return OUTPUTS_DIR / run_id / "manifest.json"


def _run_report_path(run_id: str) -> Path:
    return OUTPUTS_DIR / run_id / "report.md"


def _latest_artifact_path(run_id: str, artifact_type: str) -> str | None:
    manifest = _read_json(_run_manifest_path(run_id))
    artifacts = manifest.get("artifacts") or []
    if not isinstance(artifacts, list):
        return None
    for item in reversed(artifacts):
        if isinstance(item, dict) and item.get("type") == artifact_type:
            path = item.get("path")
            if isinstance(path, str) and path:
                return path
    return None


def _session_snapshot(session: RunSession) -> dict[str, Any]:
    with session.condition:
        latest_screenshot = _latest_artifact_path(session.run_id, "screenshot")
        return {
            "run_id": session.run_id,
            "url": session.url,
            "scenario": session.scenario,
            "run_dir": session.run_dir,
            "manifest_path": session.manifest_path,
            "status": session.status,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "final_report": session.final_report,
            "error": session.error,
            "latest_screenshot": latest_screenshot,
            "event_count": len(session.events),
        }


def _list_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    seen: set[str] = set()

    with RUNS_LOCK:
        sessions = list(RUNS.values())

    for session in sessions:
        runs.append(_session_snapshot(session))
        seen.add(session.run_id)

    if OUTPUTS_DIR.exists():
        for run_dir in sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not run_dir.is_dir() or run_dir.name in seen:
                continue
            manifest_path = run_dir / "manifest.json"
            manifest = _read_json(manifest_path)
            report_path = run_dir / "report.md"
            runs.append(
                {
                    "run_id": run_dir.name,
                    "url": manifest.get("target_url", ""),
                    "scenario": "",
                    "run_dir": run_dir.as_posix(),
                    "manifest_path": manifest_path.as_posix(),
                    "status": "completed" if report_path.exists() else "archived",
                    "started_at": manifest.get("created_at", ""),
                    "completed_at": None,
                    "final_report": report_path.as_posix() if report_path.exists() else None,
                    "error": None,
                    "latest_screenshot": _latest_artifact_path(run_dir.name, "screenshot"),
                    "event_count": 0,
                }
            )
    runs.sort(key=lambda item: (item.get("started_at") or "", item.get("run_id") or ""), reverse=True)
    return runs


def _get_session(run_id: str) -> RunSession | None:
    with RUNS_LOCK:
        return RUNS.get(run_id)


def _append_event(session: RunSession, event: dict[str, Any]) -> None:
    with session.condition:
        event_id = session.next_event_id
        session.next_event_id += 1
        session.events.append({"id": event_id, **event})
        session.condition.notify_all()


def _run_worker(session: RunSession, prepared: PreparedRun) -> None:
    with session.condition:
        session.status = "running"
        session.url = prepared.url
        session.scenario = prepared.scenario_desc
        session.run_id = prepared.run_context.run_id
        session.run_dir = prepared.run_context.run_dir.as_posix()
        session.manifest_path = prepared.run_context.manifest_path.as_posix()
        session.condition.notify_all()

    def on_event(event: dict[str, Any]) -> None:
        _append_event(session, event)

    try:
        result = execute_prepared_run(prepared, on_event=on_event)
        with session.condition:
            session.status = "completed"
            session.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            session.final_report = result.final_report
            session.condition.notify_all()
    except Exception as exc:
        with session.condition:
            session.status = "failed"
            session.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            session.error = str(exc)
            session.condition.notify_all()


def _build_session_config(payload: dict) -> SessionPersistenceConfig:
    """从 POST /api/run payload 构建 session 配置，合并 scenarios 默认值。"""
    defaults = load_session_defaults()
    sess = payload.get("session") or {}
    return SessionPersistenceConfig(
        auto_load=bool(sess.get("auto_load", defaults.get("auto_load", False))),
        auto_save=bool(sess.get("auto_save", defaults.get("auto_save", False))),
        site_id=sess.get("site_id") or defaults.get("site_id") or None,
        account_id=sess.get("account_id") or defaults.get("account_id") or None,
        storage_dir=Path(sess["storage_dir"]) if sess.get("storage_dir") else None,
    )


def start_run(url: str, scenario_text: str | None, session_config: SessionPersistenceConfig | None = None) -> RunSession:
    scenario_value = load_scenario((scenario_text or "").strip() or None)
    prepared = prepare_run(url, scenario_value, session_config=session_config)
    session = RunSession(
        run_id=prepared.run_context.run_id,
        url=prepared.url,
        scenario=prepared.scenario_desc,
        run_dir=prepared.run_context.run_dir.as_posix(),
        manifest_path=prepared.run_context.manifest_path.as_posix(),
    )
    with RUNS_LOCK:
        RUNS[prepared.run_context.run_id] = session
    thread = threading.Thread(target=_run_worker, args=(session, prepared), daemon=True)
    thread.start()
    return session


class AppHandler(BaseHTTPRequestHandler):
    server_version = "MVPDeepAgentsWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, *, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content_type, _ = mimetypes.guess_type(file_path.name)
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, root: Path, rel_path: str) -> None:
        rel = Path(unquote(rel_path.lstrip("/")))
        file_path = (root / rel).resolve()
        try:
            file_path.relative_to(root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if file_path.is_dir():
            file_path = file_path / "index.html"
        self._send_file(file_path)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length > 0 else b"{}"
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _handle_run_stream(self, run_id: str) -> None:
        session = _get_session(run_id)
        if session is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Run not found")
            return

        query = parse_qs(urlparse(self.path).query)
        last_event_id = int((query.get("lastEventId") or ["0"])[0] or "0")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            while True:
                pending: list[dict[str, Any]] = []
                with session.condition:
                    for event in session.events:
                        if int(event.get("id") or 0) > last_event_id:
                            pending.append(event)
                    if not pending:
                        if session.status in {"completed", "failed"}:
                            final_event = {
                                "id": last_event_id + 1,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "channel": "system",
                                "mode": "status",
                                "summary": f"run {session.status}",
                                "payload": _session_snapshot(session),
                            }
                            pending.append(final_event)
                            last_event_id += 1
                        else:
                            session.condition.wait(timeout=15)
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            continue
                for event in pending:
                    event_id = int(event.get("id") or 0)
                    data = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                    self.wfile.write(b"event: message\n")
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_event_id = max(last_event_id, event_id)
                if session.status in {"completed", "failed"}:
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_file(WEB_STATIC_DIR / "index.html")
            return

        if path.startswith("/web/"):
            self._serve_static(WEB_STATIC_DIR, path[len("/web/"):])
            return

        if path.startswith("/outputs/"):
            self._serve_static(PROJECT_ROOT, path.lstrip("/"))
            return

        if path == "/api/defaults":
            scenario = load_scenario(None)
            session_defaults = load_session_defaults()
            self._send_json(
                {
                    "default_url": get_default_url(),
                    "scenario": scenario if isinstance(scenario, str) else json.dumps(scenario, ensure_ascii=False, indent=2),
                    "session": {
                        "auto_load": bool(session_defaults.get("auto_load", False)),
                        "auto_save": bool(session_defaults.get("auto_save", False)),
                        "site_id": session_defaults.get("site_id") or "",
                        "account_id": session_defaults.get("account_id") or "",
                    },
                }
            )
            return

        if path == "/api/runs":
            self._send_json({"runs": _list_runs()})
            return

        if path.startswith("/api/runs/") and path.endswith("/manifest"):
            run_id = path.split("/")[3]
            manifest_path = _run_manifest_path(run_id)
            if not manifest_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Manifest not found")
                return
            self._send_json(_read_json(manifest_path))
            return

        if path.startswith("/api/runs/") and path.endswith("/report"):
            run_id = path.split("/")[3]
            report_path = _run_report_path(run_id)
            if not report_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Report not found")
                return
            self._send_text(report_path.read_text(encoding="utf-8"), content_type="text/markdown; charset=utf-8")
            return

        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            session = _get_session(run_id)
            if session is None:
                self._send_json({"events": []})
                return
            with session.condition:
                self._send_json({"events": list(session.events), "status": session.status})
            return

        if path.startswith("/api/runs/") and path.endswith("/latest-screenshot"):
            run_id = path.split("/")[3]
            screenshot_path = _latest_artifact_path(run_id, "screenshot")
            self._send_json({"path": screenshot_path})
            return

        if path.startswith("/api/run/") and path.endswith("/stream"):
            run_id = path.split("/")[3]
            self._handle_run_stream(run_id)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError as exc:
                self._send_json({"error": f"Invalid JSON: {exc}"}, status=400)
                return

            url = str(payload.get("url") or "").strip() or get_default_url()
            scenario = payload.get("scenario")
            scenario_text = str(scenario).strip() if scenario is not None else None
            session_config = _build_session_config(payload)
            session = start_run(url, scenario_text, session_config)
            self._send_json({"run": _session_snapshot(session)}, status=201)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    configure_utf8_runtime()
    init_env()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"[web] 控制台已启动: http://{host}:{port}")
    print(f"[web] outputs 目录: {OUTPUTS_DIR.as_posix()}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
