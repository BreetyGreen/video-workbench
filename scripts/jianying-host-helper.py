#!/usr/bin/env python3
"""Publish runtime/jianying.json and safely consume local open-requests."""

from __future__ import annotations

import argparse
import ctypes
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
from typing import Any


def _acquire_single_instance(data_dir: Path) -> Path | None:
    lock = data_dir / "runtime" / "jianying-host-helper.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="ascii").strip())
            if _pid_alive(pid):
                return None
            lock.unlink(missing_ok=True)
        except (OSError, ValueError):
            lock.unlink(missing_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    return lock


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _first_existing(paths: list[Path], *, directory: bool = False) -> Path | None:
    for path in paths:
        if path.is_dir() if directory else path.is_file():
            return path.resolve()
    return None


def detect() -> tuple[Path | None, Path | None]:
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        app = _first_existing(
            [
                Path(r"B:\Apps\JianyingPro\JianyingPro.exe"),
                Path(r"B:\Apps\JianyingPro\11.3.0.14362\JianyingPro.exe"),
                local / "JianyingPro" / "Apps" / "JianyingPro.exe",
                local / "CapCut" / "Apps" / "CapCut.exe",
            ]
        )
        if app is None:
            for root in [Path(r"B:\Apps\JianyingPro"), local / "JianyingPro", local / "CapCut"]:
                if root.is_dir():
                    app = next((p.resolve() for p in root.rglob("*.exe") if p.name.lower() in {"jianyingpro.exe", "capcut.exe"}), None)
                    if app:
                        break
        draft = _first_existing(
            [
                Path(r"B:\JianyingData\Drafts\JianyingPro Drafts"),
                local / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
                local / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            ],
            directory=True,
        )
        return app, draft
    if system == "Darwin":
        app = _first_existing(
            [
                Path("/Applications/JianyingPro.app"),
                Path("/Applications/CapCut.app"),
                home / "Applications" / "JianyingPro.app",
                home / "Applications" / "CapCut.app",
            ],
            directory=True,
        )
        draft = _first_existing(
            [
                home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
                home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
                home / "Library" / "Application Support" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
            ],
            directory=True,
        )
        return app, draft
    return None, None


def write_manifest(data_dir: Path, *, container_draft_root: str, fallback_draft_root: Path | None = None) -> dict[str, Any]:
    app, draft = detect()
    draft = draft or fallback_draft_root
    installed = app is not None
    writable = bool(draft and draft.is_dir() and os.access(draft, os.W_OK))
    effective_container_root = str(draft) if container_draft_root == "__host__" and draft else container_draft_root
    payload = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "installed": installed,
        "app_path": str(app) if app else None,
        "draft_root": str(draft.resolve()) if draft else None,
        "container_draft_root": effective_container_root,
        "draft_root_writable": writable,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    path = data_dir / "runtime" / "jianying.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return payload


def _safe_launch(manifest: dict[str, Any]) -> None:
    app_value = manifest.get("app_path")
    if not isinstance(app_value, str) or not app_value:
        raise ValueError("jianying_app_missing")
    app = Path(app_value).resolve()
    if platform.system() == "Darwin":
        if app.suffix != ".app" or not app.is_dir():
            raise ValueError("unsafe_app_path")
        subprocess.Popen(["open", "-a", str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if app.suffix.lower() != ".exe" or not app.is_file() or app.name.lower() not in {"jianyingpro.exe", "capcut.exe"}:
            raise ValueError("unsafe_app_path")
        subprocess.Popen([str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def process_requests(data_dir: Path, manifest: dict[str, Any]) -> int:
    request_dir = data_dir / "runtime" / "open-requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    processed = 0
    for path in request_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") != "requested":
                continue
            if payload.get("app_path") != manifest.get("app_path"):
                raise ValueError("app_path_mismatch")
            _safe_launch(manifest)
            payload["status"] = "launched"
            payload["launched_at"] = datetime.now(UTC).isoformat()
            processed += 1
        except Exception as error:
            payload = payload if isinstance(locals().get("payload"), dict) else {}
            payload["status"] = "failed"
            payload["error"] = str(error)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return processed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--container-draft-root", default="/jianying-drafts")
    parser.add_argument("--fallback-draft-root", type=Path)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    lock = _acquire_single_instance(data_dir) if args.watch else None
    if args.watch and lock is None:
        return 0
    try:
        while True:
            manifest = write_manifest(
                data_dir,
                container_draft_root=args.container_draft_root,
                fallback_draft_root=args.fallback_draft_root,
            )
            process_requests(data_dir, manifest)
            if not args.watch:
                return 0
            time.sleep(2)
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
