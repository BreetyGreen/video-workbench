from pathlib import Path

from app.platforms.runtime import resolve_runtime_paths


def test_macos_runtime_paths_are_outside_the_clone(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    paths = resolve_runtime_paths(system="Darwin", home=home)

    assert paths.data_dir == home / "Library" / "Application Support" / "VideoWorkbench"
    assert paths.cache_dir == home / "Library" / "Caches" / "VideoWorkbench"
    assert paths.inbox_dir == home / "Movies" / "VideoWorkbench Inbox"
    assert paths.database_url.endswith(
        "/Library/Application Support/VideoWorkbench/control-plane.db"
    )


def test_windows_runtime_paths_preserve_a_portable_default(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    paths = resolve_runtime_paths(system="Windows", home=home)

    assert paths.data_dir == home / "AppData" / "Local" / "VideoWorkbench"
    assert paths.cache_dir == home / "AppData" / "Local" / "VideoWorkbench" / "cache"
    assert paths.inbox_dir == home / "Videos" / "VideoWorkbench Inbox"


def test_explicit_home_is_not_resolved_against_the_current_machine():
    relative_home = Path("fixture-home")
    paths = resolve_runtime_paths(system="Linux", home=relative_home)

    assert paths.data_dir == relative_home / ".local" / "share" / "VideoWorkbench"
