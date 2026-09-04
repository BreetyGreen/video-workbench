from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SyncHttp(Protocol):
    def get_json(self, path: str) -> Any: ...
    def download(self, path: str, destination: Path) -> None: ...
    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


class UrlLibSyncHttp:
    def __init__(self, server_url: str, bearer_token: str = "", *, max_download_bytes: int = 4_000_000_000):
        normalized = server_url.rstrip("/")
        if not normalized.startswith("https://") and not normalized.startswith(
            ("http://127.0.0.1", "http://localhost")
        ):
            raise ValueError("remote_sync_requires_https")
        self.server_url = normalized
        self.bearer_token = bearer_token.strip()
        self.max_download_bytes = max_download_bytes

    def _request(self, path: str, *, data: bytes | None = None) -> Request:
        headers = {"Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        return Request(self.server_url + path, data=data, headers=headers)

    def get_json(self, path: str) -> Any:
        with urlopen(self._request(path), timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with urlopen(self._request(path, data=body), timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        total = 0
        try:
            with urlopen(self._request(path), timeout=300) as response, temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise ValueError("remote_artifact_too_large")
                    stream.write(chunk)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


class RemoteJianyingSyncService:
    def __init__(self, *, data_dir: Path, http: SyncHttp, handoff: Any, device_api: bool = False):
        self.data_dir = Path(data_dir)
        self.http = http
        self.handoff = handoff
        self.device_api = device_api

    def sync_pending(self, *, limit: int = 20) -> list[dict[str, str]]:
        normalized_limit = min(max(limit, 1), 100)
        if self.device_api:
            jobs = self.http.get_json(f"/api/devices/me/course-edit-jobs?{urlencode({'limit': normalized_limit})}")
        else:
            query = urlencode({"state": "awaiting_device", "limit": normalized_limit})
            jobs = self.http.get_json(f"/api/course-edit-jobs?{query}")
        if not isinstance(jobs, list):
            raise ValueError("invalid_remote_job_queue")
        results: list[dict[str, str]] = []
        for job in jobs:
            if not isinstance(job, dict) or not job.get("id") or not job.get("task_id"):
                continue
            job_id = str(job["id"])
            task_id = str(job["task_id"])
            task_dir = self.data_dir / "artifacts" / task_id
            try:
                for name in ("quality-report.json", "draft.zip"):
                    artifact_path = (
                        f"/api/devices/me/course-edit-jobs/{job_id}/artifacts/{name}"
                        if self.device_api
                        else f"/api/tasks/{task_id}/artifacts/{name}"
                    )
                    self.http.download(artifact_path, task_dir / name)
                handoff = self.handoff.import_task(task_id)
                status = str(handoff.get("status") or "failed")
                error_code = str(handoff.get("code") or "")
            except Exception as error:
                status = "failed"
                error_code = type(error).__name__
            ack_status = "imported" if status == "imported" else "failed"
            ack_path = (
                f"/api/devices/me/course-edit-jobs/{job_id}/handoff"
                if self.device_api
                else f"/api/course-edit-jobs/{job_id}/device-handoff"
            )
            self.http.post_json(
                ack_path,
                {"status": ack_status, "error_code": error_code},
            )
            results.append({"job_id": job_id, "task_id": task_id, "status": status})
        return results
