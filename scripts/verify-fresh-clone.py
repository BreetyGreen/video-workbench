#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_DIRNAME = PROJECT_ROOT.name


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(result.stdout.strip())


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

        return {
            "status": "ok",
            "archive": "tracked-files-only",
            "repository_layout": "standalone" if standalone_repository else "subdirectory",
            "doctor_exit": doctor.returncode,
            "doctor_actions": report["actions"],
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
