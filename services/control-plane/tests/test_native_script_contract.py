from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_native_start_is_loopback_and_not_docker_based():
    source = (ROOT / "scripts" / "start-local.sh").read_text(encoding="utf-8")
    assert "127.0.0.1" in source
    assert "run uvicorn app.main:app" in source
    assert "docker" not in source.lower()


def test_stop_uses_only_the_recorded_pid():
    source = (ROOT / "scripts" / "stop-local.sh").read_text(encoding="utf-8")
    assert "control-plane.pid" in source
    assert "pkill" not in source
    assert "killall" not in source


def test_bootstrap_pins_python_and_creates_runtime_directories():
    source = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'PYTHON_VERSION="3.12"' in source
    assert 'python install "$PYTHON_VERSION"' in source
    assert "VideoWorkbench Inbox" in source
    assert "brew install ffmpeg" in source
    assert "--locked" in source


def test_start_never_reads_a_repo_env_file():
    source = (ROOT / "scripts" / "start-local.sh").read_text(encoding="utf-8")
    assert ".env" not in source
    assert "VIDEO_WORKBENCH_DATA_DIR" in source
    assert "VIDEO_WORKBENCH_DATABASE_URL" in source
