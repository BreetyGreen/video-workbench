from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests isolated from the persisted daily automation schedule."""
    monkeypatch.setenv("VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("VIDEO_WORKBENCH_PUBLIC_TREND_WEB_ENABLED", "false")


def find_media_tool(name: str) -> str:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    winget_link = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    if winget_link.exists():
        return str(winget_link)
    pytest.skip(f"{name} is not installed")


@pytest.fixture(scope="session")
def ffmpeg_bin() -> str:
    return find_media_tool("ffmpeg")


@pytest.fixture(scope="session")
def ffprobe_bin() -> str:
    return find_media_tool("ffprobe")


@pytest.fixture(scope="session")
def ffmpeg_fixture(tmp_path_factory: pytest.TempPathFactory, ffmpeg_bin: str) -> Path:
    output = tmp_path_factory.mktemp("media") / "fixture.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output
