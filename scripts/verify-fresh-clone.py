#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_DIRNAME = PROJECT_ROOT.name
SETUP_PATH = "/setup"
SETUP_PREFERENCES_PATH = "/api/setup/preferences"


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(result.stdout.strip())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_service(url: str, process: subprocess.Popen[str], *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"fresh-clone service exited early: {stdout}\n{stderr}".strip())
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.25)
    raise RuntimeError("fresh-clone service did not become healthy within 90 seconds")


def _request_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _verify_setup_smoke(clone_root: Path, fake_home: Path, environment: dict[str, str]) -> None:
    uv_bin = environment.get("UV_BIN") or shutil.which("uv")
    if not uv_bin:
        raise RuntimeError("uv is required for the fresh-clone setup smoke test")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    runtime_dir = fake_home / "VideoWorkbench"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    service_environment = environment.copy()
    service_environment.update(
        {
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
            "VIDEO_WORKBENCH_DATA_DIR": str(runtime_dir),
            "VIDEO_WORKBENCH_DATABASE_URL": f"sqlite:///{(runtime_dir / 'control-plane.db').as_posix()}",
            "VIDEO_WORKBENCH_AUTOMATION_ENABLED": "false",
            "VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED": "false",
            "VIDEO_WORKBENCH_PUBLIC_TREND_WEB_ENABLED": "false",
        }
    )
    process = subprocess.Popen(
        [
            uv_bin,
            "run",
            "--project",
            str(clone_root / "services" / "control-plane"),
            "--locked",
            "python",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=clone_root / "services" / "control-plane",
        env=service_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_service(f"{base_url}/health", process)
        with urlopen(f"{base_url}{SETUP_PATH}", timeout=10) as response:
            setup_html = response.read().decode("utf-8")
        if response.status != 200 or "本地模式现在就能用" not in setup_html:
            raise RuntimeError("fresh-clone setup page did not expose local-first onboarding")
        status = _request_json(f"{base_url}/api/setup/status")
        if not (status.get("local_mode") or {}).get("ready"):
            raise RuntimeError("fresh-clone local mode was not ready")
        saved = _request_json(
            f"{base_url}{SETUP_PREFERENCES_PATH}",
            method="PUT",
            payload={"local_mode_confirmed": True},
        )
        if saved != {"local_mode_confirmed": True}:
            raise RuntimeError("fresh-clone local-mode confirmation was not saved")
        with urlopen(f"{base_url}/", timeout=10) as response:
            workbench_html = response.read().decode("utf-8")
        if response.status != 200 or "今天想让观众记住什么？" not in workbench_html:
            raise RuntimeError("fresh-clone workbench did not open after local confirmation")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def verify_archive() -> dict[str, object]:
    git_root = _git_root()
    standalone_repository = PROJECT_ROOT.resolve() == git_root.resolve()
    with tempfile.TemporaryDirectory(prefix="videoworkbench-clone-") as temp_name:
        temp_root = Path(temp_name)
        archive_path = temp_root / "clone.zip"
        archive_command = [
            "git",
            "-C",
            str(git_root),
            "archive",
            "--format=zip",
            f"--output={archive_path}",
            "HEAD",
        ]
        if not standalone_repository:
            archive_command.append(APPLICATION_DIRNAME)
        subprocess.run(
            archive_command,
            check=True,
            capture_output=True,
        )
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_root / "checkout")
        clone_root = temp_root / "checkout"
        if not standalone_repository:
            clone_root /= APPLICATION_DIRNAME

        forbidden = (
            clone_root / ".env",
            clone_root / "data",
            clone_root / "services" / "control-plane" / ".venv",
            clone_root / "services" / "control-plane" / "data",
        )
        leaked = [str(path.relative_to(clone_root)) for path in forbidden if path.exists()]
        if leaked:
            raise RuntimeError(f"runtime files leaked into the archive: {leaked}")

        required = (
            clone_root / "AGENTS.md",
            clone_root / "scripts" / "bootstrap.sh",
            clone_root / "scripts" / "doctor.py",
            clone_root / "services" / "control-plane" / "uv.lock",
        )
        missing = [str(path.relative_to(clone_root)) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"bootstrap files missing from the archive: {missing}")

        fake_home = temp_root / "home"
        fake_home.mkdir()
        environment = os.environ.copy()
        environment["VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED"] = "false"
        doctor = subprocess.run(
            [
                sys.executable,
                str(clone_root / "scripts" / "doctor.py"),
                "--system",
                "Darwin",
                "--home",
                str(fake_home),
            ],
            cwd=clone_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
            env=environment,
        )
        if doctor.returncode not in (0, 2) or doctor.stderr:
            raise RuntimeError(f"doctor failed in the archive: {doctor.stderr.strip()}")
        report = json.loads(doctor.stdout)

        bootstrap = (clone_root / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        runbook = (clone_root / "docs" / "runbooks" / "macos-local.md").read_text(encoding="utf-8")
        handlers = {
            "install_ffmpeg": "brew install ffmpeg" in bootstrap,
            "install_or_open_jianying": "install_or_open_jianying" in runbook,
            "choose_jianying_draft_root": "choose_jianying_draft_root" in runbook,
        }
        unhandled = [action for action in report["actions"] if not handlers.get(action, False)]
        if unhandled:
            raise RuntimeError(f"doctor actions have no bootstrap or runbook handler: {unhandled}")

        _verify_setup_smoke(clone_root, fake_home, environment)

        return {
            "status": "ok",
            "archive": "tracked-files-only",
            "repository_layout": "standalone" if standalone_repository else "subdirectory",
            "doctor_exit": doctor.returncode,
            "doctor_actions": report["actions"],
            "setup_smoke": "passed",
            "real_home_modified": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the GitHub fresh-clone contract")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify without installing dependencies or starting the service",
    )
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("only --dry-run is supported")
    print(json.dumps(verify_archive(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
