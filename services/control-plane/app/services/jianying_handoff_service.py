from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any
from uuid import UUID
import zipfile

from app.services.jianying_runtime_service import JianyingRuntimeService


class JianyingHandoffService:
    def __init__(self, data_dir: Path, artifact_dir: Path, runtime: JianyingRuntimeService):
        self.data_dir = Path(data_dir)
        self.artifact_dir = Path(artifact_dir)
        self.runtime = runtime
        self.handoff_dir = self.data_dir / "runtime" / "handoffs"
        self.open_request_dir = self.data_dir / "runtime" / "open-requests"

    def status(self, task_id: str) -> dict[str, Any]:
        state_path = self.handoff_dir / f"{task_id}.json"
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runtime = self.runtime.snapshot()
            return {
                "status": "ready" if runtime.get("ready_for_auto_import") else "waiting",
                "code": None if runtime.get("ready_for_auto_import") else "jianying_not_ready",
                "runtime": runtime,
            }
        return payload if isinstance(payload, dict) else {"status": "waiting"}

    def import_task(self, task_id: str) -> dict[str, Any]:
        try:
            UUID(task_id)
        except ValueError:
            return self._save(task_id, {"status": "failed", "code": "invalid_task_id"})

        package = self.artifact_dir / task_id / "draft.zip"
        if not package.is_file():
            return self._save(task_id, {"status": "failed", "code": "draft_package_missing"})
        quality = self._read_json(self.artifact_dir / task_id / "quality-report.json")
        if not quality or quality.get("blocking_failures"):
            return self._save(task_id, {"status": "failed", "code": "quality_gate_blocked"})

        runtime = self.runtime.snapshot()
        if not runtime.get("ready_for_auto_import"):
            return self._save(task_id, {"status": "waiting", "code": "jianying_not_ready", "runtime": runtime})

        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        previous = self.status(task_id)
        if (
            previous.get("status") == "imported"
            and previous.get("package_sha256") == digest
            and Path(str(previous.get("container_draft_path") or "")).is_dir()
        ):
            self._request_open(task_id, runtime, previous)
            self._update_review_warning(task_id)
            return {**previous, "idempotent": True}

        container_root = Path(str(runtime["container_draft_root"])).resolve()
        container_root.mkdir(parents=True, exist_ok=True)
        # Stage on the same mounted volume so the final rename is atomic even
        # when /data and the Jianying draft root are different Docker mounts.
        staging_root = container_root / ".video-workbench-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f"{task_id}-", dir=staging_root))
        try:
            with zipfile.ZipFile(package) as archive:
                top = self._validate_archive(archive)
                archive.extractall(stage)
            source = stage / top
            if not (source / "draft_info.json").is_file():
                return self._save(task_id, {"status": "failed", "code": "draft_info_missing"})
            destination = self._unique_destination(container_root, top, task_id)
            host_destination = self._join_host_path(str(runtime["draft_root"]), destination.name)
            native_source = (self.artifact_dir / task_id / "drafts" / top).resolve()
            source_prefixes = {
                f"/data/artifacts/{task_id}/drafts/{top}",
                str(native_source),
                native_source.as_posix(),
            }
            rewritten = 0
            for name in ("draft_info.json", "draft_content.json", "draft_meta_info.json"):
                path = source / name
                if path.is_file():
                    document = self._read_json(path)
                    if document is None:
                        raise ValueError(f"invalid_{name}")
                    for source_prefix in source_prefixes:
                        document, count = self._replace_strings(document, source_prefix, host_destination)
                        rewritten += count
                    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self._validate_media_paths(source / "draft_info.json", source, host_destination)
            source.replace(destination)
            payload = self._save(
                task_id,
                {
                    "status": "imported",
                    "code": None,
                    "draft_path": host_destination,
                    "container_draft_path": str(destination),
                    "package_sha256": digest,
                    "rewritten_paths": rewritten,
                    "media_validated": True,
                    "idempotent": False,
                    "runtime": runtime,
                },
            )
            self._request_open(task_id, runtime, payload)
            self._update_review_warning(task_id)
            return payload
        except (ValueError, zipfile.BadZipFile) as error:
            return self._save(task_id, {"status": "failed", "code": str(error)})
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    def _validate_archive(self, archive: zipfile.ZipFile) -> str:
        roots: set[str] = set()
        for info in archive.infolist():
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("unsafe_archive_path")
            if re.match(r"^[A-Za-z]:", path.parts[0]):
                raise ValueError("unsafe_archive_path")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("archive_symlink_not_allowed")
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise ValueError("archive_requires_single_root")
        return next(iter(roots))

    def _validate_media_paths(self, draft_info: Path, source: Path, host_destination: str) -> None:
        payload = self._read_json(draft_info)
        if payload is None:
            raise ValueError("invalid_draft_info")

        def walk(value: Any):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "path" and isinstance(child, str) and child.startswith(host_destination):
                        relative = child[len(host_destination):].lstrip("/\\").replace("\\", "/")
                        target = (source / relative).resolve()
                        if source.resolve() not in target.parents and target != source.resolve():
                            raise ValueError("unsafe_media_path")
                        if not target.is_file():
                            raise ValueError("draft_media_missing")
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)

    @staticmethod
    def _unique_destination(root: Path, top: str, task_id: str) -> Path:
        safe = re.sub(r'[<>:"/\\|?*]+', "-", top).strip(" .") or "视频草稿"
        base = root / f"{safe}-{task_id[:8]}"
        if not base.exists():
            return base
        index = 2
        while (root / f"{base.name}-{index}").exists():
            index += 1
        return root / f"{base.name}-{index}"

    @staticmethod
    def _join_host_path(root: str, name: str) -> str:
        separator = "\\" if "\\" in root or re.match(r"^[A-Za-z]:", root) else "/"
        return root.rstrip("/\\") + separator + name

    @classmethod
    def _replace_strings(cls, value: Any, source: str, destination: str) -> tuple[Any, int]:
        if isinstance(value, str):
            return value.replace(source, destination), value.count(source)
        if isinstance(value, list):
            output = []
            count = 0
            for child in value:
                updated, child_count = cls._replace_strings(child, source, destination)
                output.append(updated)
                count += child_count
            return output, count
        if isinstance(value, dict):
            output = {}
            count = 0
            for key, child in value.items():
                updated, child_count = cls._replace_strings(child, source, destination)
                output[key] = updated
                count += child_count
            return output, count
        return value, 0

    def _request_open(self, task_id: str, runtime: dict[str, Any], state: dict[str, Any]) -> None:
        self.open_request_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(
            self.open_request_dir / f"{task_id}.json",
            {
                "task_id": task_id,
                "app_path": runtime.get("app_path"),
                "draft_path": state.get("draft_path"),
                "requested_at": datetime.now(UTC).isoformat(),
                "status": "requested",
            },
        )

    def _update_review_warning(self, task_id: str) -> None:
        path = self.artifact_dir / task_id / "review.json"
        payload = self._read_json(path)
        if payload is None:
            return
        warnings = payload.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings = [
            str(item)
            for item in warnings
            if "尚未在本机剪映打开草稿" not in str(item)
        ]
        message = "草稿已自动导入本机剪映目录，并已请求打开客户端；仍需人工确认画面兼容性。"
        if message not in warnings:
            warnings.append(message)
        payload["warnings"] = warnings
        self._write_json_atomic(path, payload)

    def _save(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = {**payload, "task_id": task_id, "updated_at": datetime.now(UTC).isoformat()}
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(self.handoff_dir / f"{task_id}.json", result)
        return result

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
