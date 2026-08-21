#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_ROOT = PROJECT_ROOT / "services" / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE_ROOT))

from app.platforms.jianying import discover_jianying  # noqa: E402
from app.platforms.runtime import resolve_runtime_paths  # noqa: E402


def _read_mdfind() -> str:
    try:
        result = subprocess.run(
            [
                "mdfind",
                "kMDItemContentType == 'com.apple.application-bundle' && "
                "(kMDItemDisplayName == '*Jianying*'cd || kMDItemDisplayName == '*CapCut*'cd)",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def build_report(*, requested_system: str | None, home: Path | None) -> dict[str, object]:
    detected_system = requested_system or platform.system()
    user_home = Path(home) if home is not None else Path.home()
    runtime = resolve_runtime_paths(system=detected_system, home=user_home)
    mdfind_output = ""
    if requested_system is None and platform.system() == "Darwin":
        mdfind_output = _read_mdfind()
    jianying = discover_jianying(
        home=user_home,
        system=detected_system,
        mdfind_output=mdfind_output,
    )
    commands = {
        name: {"available": shutil.which(name) is not None}
        for name in ("ffmpeg", "ffprobe")
    }
    actions: list[str] = []
    if not commands["ffmpeg"]["available"] or not commands["ffprobe"]["available"]:
        actions.append("install_ffmpeg")
    if not jianying.installed:
        actions.append("install_or_open_jianying")
    elif jianying.needs_folder_picker:
        actions.append("choose_jianying_draft_root")

    return {
        "platform": {
            "system": detected_system,
            "architecture": platform.machine(),
        },
        "runtime": {
            "data_dir": runtime.data_dir.as_posix(),
            "cache_dir": runtime.cache_dir.as_posix(),
            "inbox_dir": runtime.inbox_dir.as_posix(),
        },
        "commands": commands,
        "jianying": {
            "installed": jianying.installed,
            "app_path": jianying.app_path.as_posix() if jianying.app_path else None,
            "draft_root": jianying.draft_root.as_posix() if jianying.draft_root else None,
            "candidate_count": len(jianying.candidates),
            "needs_folder_picker": jianying.needs_folder_picker,
        },
        "actions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect local VideoWorkbench readiness")
    parser.add_argument("--system", choices=("Darwin", "Windows", "Linux"))
    parser.add_argument("--home", type=Path)
    args = parser.parse_args()
    report = build_report(requested_system=args.system, home=args.home)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    commands = report["commands"]
    assert isinstance(commands, dict)
    required_ready = all(
        isinstance(value, dict) and value.get("available") is True
        for value in commands.values()
    )
    return 0 if required_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
