import json
import os
from pathlib import Path
import subprocess
import sys


def test_doctor_emits_machine_readable_actions(tmp_path: Path):
    script = Path(__file__).parents[3] / "scripts" / "doctor.py"
    result = subprocess.run(
        [sys.executable, str(script), "--system", "Darwin", "--home", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert payload["platform"]["system"] == "Darwin"
    assert payload["runtime"]["data_dir"].endswith(
        "Library/Application Support/VideoWorkbench"
    )
    assert set(payload["commands"]) == {"ffmpeg", "ffprobe"}
    assert isinstance(payload["actions"], list)
    assert result.stderr == ""


def test_doctor_never_echoes_process_secrets(tmp_path: Path):
    script = Path(__file__).parents[3] / "scripts" / "doctor.py"
    env = os.environ.copy()
    env.update({"PATH": "", "VIDEO_WORKBENCH_API_KEY": "never-print-this"})
    result = subprocess.run(
        [sys.executable, str(script), "--system", "Darwin", "--home", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "never-print-this" not in result.stdout
    assert json.loads(result.stdout)["actions"][0] == "install_ffmpeg"
