#!/usr/bin/env python3
"""Sync completed server jobs into this Mac/Windows Jianying draft folder."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE = REPO_ROOT / "services" / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE))

from app.services.jianying_handoff_service import JianyingHandoffService  # noqa: E402
from app.services.jianying_runtime_service import JianyingRuntimeService  # noqa: E402
from app.services.remote_jianying_sync_service import RemoteJianyingSyncService, UrlLibSyncHttp  # noqa: E402


def prepare_runtime(data_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "jianying-host-helper.py"),
            "--data-dir",
            str(data_dir),
            "--container-draft-root",
            "__host__",
        ],
        check=True,
    )


def load_or_pair_token(server_url: str, data_dir: Path, device_name: str) -> str:
    environment_token = os.environ.get("VIDEO_WORKBENCH_DEVICE_BEARER_TOKEN", "").strip()
    if environment_token:
        return environment_token
    token_path = data_dir / "runtime" / "device-token.json"
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
        stored = str(payload.get("token") or "").strip()
        if stored:
            return stored
    except (OSError, json.JSONDecodeError):
        pass
    code = getpass.getpass("首次使用请输入服务器生成的一次性配对码：").strip()
    if not code:
        raise ValueError("pairing_code_required")
    paired = UrlLibSyncHttp(server_url).post_json(
        "/api/devices/pair",
        {"code": code, "name": device_name},
    )
    token = str(paired.get("token") or "").strip()
    if not token:
        raise ValueError("device_pairing_failed")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"device_id": paired.get("device_id"), "token": token}), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, token_path)
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description="把服务器成片自动同步到本机剪映草稿箱")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--device-name", default=os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "VideoWorkbench Device")
    args = parser.parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    token = load_or_pair_token(args.server_url, data_dir, args.device_name)
    http = UrlLibSyncHttp(args.server_url, token)
    while True:
        prepare_runtime(data_dir)
        handoff = JianyingHandoffService(data_dir, data_dir / "artifacts", JianyingRuntimeService(data_dir))
        results = RemoteJianyingSyncService(
            data_dir=data_dir,
            http=http,
            handoff=handoff,
            device_api=True,
        ).sync_pending()
        prepare_runtime(data_dir)
        for item in results:
            print(f"{item['job_id']} {item['status']}")
        if not args.watch:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
