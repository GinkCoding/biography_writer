"""Runtime monitor for long-running biography generation workflows.

Features:
1. Per-run status file (`status.json`) for quick health checks.
2. Structured event stream (`events.jsonl`) for timeline analysis.
3. Node artifact snapshots (`artifacts/<stage>/*.json`) for debugging.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


def _now() -> str:
    return datetime.now().isoformat()


def _json_dump(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


@dataclass
class _RunPaths:
    run_id: str
    run_dir: Path
    events_file: Path
    status_file: Path
    artifacts_dir: Path
    manifest_file: Path


class RuntimeMonitor:
    """Thread-safe runtime monitor (singleton)."""

    _instance: Optional["RuntimeMonitor"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, project_root: Optional[Path] = None):
        if self._initialized:
            return

        # Reentrant lock avoids deadlocks when high-level APIs call nested monitor APIs.
        self._lock = threading.RLock()
        self.project_root = project_root or Path.cwd()
        self.runs_root = self.project_root / ".observability" / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)

        self._current: Optional[_RunPaths] = None
        self._status: Dict[str, Any] = {}
        self._event_count = 0
        self._initialized = True

    def start_run(self, book_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_id = f"{book_id}_{timestamp}"
            run_dir = self.runs_root / run_id
            events_file = run_dir / "events.jsonl"
            status_file = run_dir / "status.json"
            artifacts_dir = run_dir / "artifacts"
            manifest_file = run_dir / "artifacts_manifest.json"

            run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            self._current = _RunPaths(
                run_id=run_id,
                run_dir=run_dir,
                events_file=events_file,
                status_file=status_file,
                artifacts_dir=artifacts_dir,
                manifest_file=manifest_file,
            )
            self._event_count = 0

            self._status = {
                "run_id": run_id,
                "book_id": book_id,
                "status": "running",
                "started_at": _now(),
                "updated_at": _now(),
                "current_stage": "bootstrap",
                "last_message": "run started",
                "run_dir": str(run_dir),
                "events_file": str(events_file),
                "status_file": str(status_file),
                "artifacts_dir": str(artifacts_dir),
                "manifest_file": str(manifest_file),
                "metadata": metadata or {},
            }
            _json_dump(status_file, self._status)
            _json_dump(
                manifest_file,
                {
                    "run_id": run_id,
                    "book_id": book_id,
                    "created_at": _now(),
                    "artifacts": [],
                },
            )
            self.log_event(
                stage="run",
                status="started",
                message="run started",
                metadata=metadata,
            )
            logger.info(f"Runtime monitor started: {run_dir}")
            return run_id

    def has_active_run(self) -> bool:
        with self._lock:
            return self._current is not None

    def log_event(
        self,
        stage: str,
        status: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            if self._current is None:
                return

            event = {
                "timestamp": _now(),
                "run_id": self._current.run_id,
                "sequence": self._event_count + 1,
                "stage": stage,
                "status": status,
                "message": message,
                "metadata": metadata or {},
            }

            try:
                with open(self._current.events_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            except Exception as exc:
                logger.warning(f"Failed to append runtime event: {exc}")

            self._status["updated_at"] = event["timestamp"]
            self._status["current_stage"] = stage
            self._status["last_message"] = message
            self._status["last_status"] = status
            self._status["event_count"] = event["sequence"]
            self._event_count = event["sequence"]
            _json_dump(self._current.status_file, self._status)

    def heartbeat(
        self,
        stage: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log_event(stage=stage, status="heartbeat", message=message, metadata=metadata)

    def save_json_artifact(self, name: str, data: Any, stage: str = "general") -> Optional[Path]:
        with self._lock:
            if self._current is None:
                return None

            safe_stage = stage.replace("/", "_")
            target_dir = self._current.artifacts_dir / safe_stage
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / name

            try:
                payload = data if isinstance(data, (dict, list)) else {"value": data}
                target_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                self._append_artifact_record(stage=stage, name=name, kind="json", path=target_path)
                return target_path
            except Exception as exc:
                logger.warning(f"Failed to save runtime artifact {name}: {exc}")
                return None

    def save_text_artifact(self, name: str, content: str, stage: str = "general") -> Optional[Path]:
        with self._lock:
            if self._current is None:
                return None

            safe_stage = stage.replace("/", "_")
            target_dir = self._current.artifacts_dir / safe_stage
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / name
            try:
                target_path.write_text(content, encoding="utf-8")
                self._append_artifact_record(stage=stage, name=name, kind="text", path=target_path)
                return target_path
            except Exception as exc:
                logger.warning(f"Failed to save text artifact {name}: {exc}")
                return None

    def _append_artifact_record(self, stage: str, name: str, kind: str, path: Path) -> None:
        if self._current is None:
            return
        manifest_path = self._current.manifest_file
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {"run_id": self._current.run_id, "artifacts": []}
        artifacts = manifest.setdefault("artifacts", [])
        artifacts.append(
            {
                "timestamp": _now(),
                "stage": stage,
                "name": name,
                "kind": kind,
                "path": str(path),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
        )
        _json_dump(manifest_path, manifest)

    def end_run(self, status: str = "completed", error: Optional[str] = None) -> None:
        with self._lock:
            if self._current is None:
                return

            finished_at = _now()
            self.log_event(
                stage="run",
                status=status,
                message="run finished" if not error else f"run failed: {error}",
                metadata={"error": error} if error else {},
            )
            self._status["status"] = status
            self._status["finished_at"] = finished_at
            if error:
                self._status["error"] = error
            _json_dump(self._current.status_file, self._status)
            self._current = None

    def get_current_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def get_latest_status(self, book_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        candidates = sorted(self.runs_root.glob("*/status.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for status_file in candidates:
            try:
                payload = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if book_id and payload.get("book_id") != book_id:
                continue
            payload["status_file"] = str(status_file)
            return payload
        return None


def get_runtime_monitor(project_root: Optional[Path] = None) -> RuntimeMonitor:
    return RuntimeMonitor(project_root=project_root)
