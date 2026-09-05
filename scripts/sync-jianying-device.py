#!/usr/bin/env python3
"""Sync completed server jobs into this Mac/Windows Jianying draft folder."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import runpy
import sys
import time


REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
CONTROL_PLANE = REPO_ROOT / "services" / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE))

from app.services.jianying_handoff_service import JianyingHandoffService  # noqa: E402
from app.services.jianying_runtime_service import JianyingRuntimeService  # noqa: E402
from app.services.remote_jianying_sync_service import RemoteJianyingSyncService, UrlLibSyncHttp  # noqa: E402


_HOST_HELPER: dict[str, object] | None = None


def _windows_dpapi(data: bytes, *, decrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data, len(data))
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = DataBlob()
    crypt32 = ctypes.windll.crypt32
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if decrypt:
        ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination))
    else:
        ok = function(ctypes.byref(source), "VideoWorkbench device token", None, None, None, 0, ctypes.byref(destination))
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.data)


def read_stored_device_token(token_path: Path) -> str:
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
        if payload.get("format") == "windows-dpapi-v1":
            protected = base64.b64decode(str(payload["protected"]).encode("ascii"), validate=True)
            payload = json.loads(_windows_dpapi(protected, decrypt=True).decode("utf-8"))
        return str(payload.get("token") or "").strip()
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ""


def store_device_token(token_path: Path, *, device_id: object, token: str) -> None:
    payload: dict[str, object] = {"device_id": device_id, "token": token}
    if os.name == "nt":
        protected = _windows_dpapi(json.dumps(payload).encode("utf-8"), decrypt=False)
        payload = {"format": "windows-dpapi-v1", "protected": base64.b64encode(protected).decode("ascii")}
    token_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, token_path)


def prepare_runtime(data_dir: Path) -> None:
    """Refresh the Jianying manifest without spawning a Python interpreter.

    A PyInstaller one-file executable cannot use ``sys.executable`` to run a
    bundled ``.py`` data file: ``sys.executable`` points back to the packaged
    helper itself. Loading the audited host helper in-process keeps the source
    and packaged execution paths identical.
    """
    global _HOST_HELPER
    if _HOST_HELPER is None:
        _HOST_HELPER = runpy.run_path(str(REPO_ROOT / "scripts" / "jianying-host-helper.py"))
    write_manifest = _HOST_HELPER["write_manifest"]
    process_requests = _HOST_HELPER["process_requests"]
    manifest = write_manifest(data_dir, container_draft_root="__host__")  # type: ignore[operator]
    process_requests(data_dir, manifest)  # type: ignore[operator]


def load_or_pair_token(server_url: str, data_dir: Path, device_name: str, pairing_code_stdin: bool = False) -> str:
    environment_token = os.environ.get("VIDEO_WORKBENCH_DEVICE_BEARER_TOKEN", "").strip()
    if environment_token:
        return environment_token
    token_path = data_dir / "runtime" / "device-token.json"
    stored = read_stored_device_token(token_path)
    if stored:
        return stored
    if pairing_code_stdin:
        code = sys.stdin.readline().strip()
    else:
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
    store_device_token(token_path, device_id=paired.get("device_id"), token=token)
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description="把服务器成片自动同步到本机剪映草稿箱")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--pair-only", action="store_true", help="Pair and store the device credential without claiming jobs")
    parser.add_argument("--pairing-code-stdin", action="store_true", help="Read the one-time pairing code from standard input")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--device-name", default=os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "VideoWorkbench Device")
    args = parser.parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    token = load_or_pair_token(args.server_url, data_dir, args.device_name, args.pairing_code_stdin)
    if args.pair_only:
        return 0
    http = UrlLibSyncHttp(args.server_url, token)
    consecutive_failures = 0
    while True:
        try:
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
            consecutive_failures = 0
        except Exception as error:
            if not args.watch:
                raise
            consecutive_failures += 1
            delay = min(max(args.interval, 5) * (2 ** min(consecutive_failures - 1, 5)), 300)
            print(f"sync_failed {type(error).__name__}; retry_in={delay}s", file=sys.stderr)
            time.sleep(delay)
            continue
        if not args.watch:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
