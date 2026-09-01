from pathlib import Path


def test_sync_helper_has_pinned_cross_platform_build_and_install_contracts() -> None:
    root = Path(__file__).resolve().parents[3]
    requirements = (root / "sync-helper" / "requirements-build.txt").read_text()
    windows = (root / "sync-helper" / "install-windows.ps1").read_text()
    macos = (root / "sync-helper" / "install-macos.sh").read_text()
    plist = (root / "sync-helper" / "com.video-workbench.sync.plist").read_text()
    workflow = (root / ".github" / "workflows" / "sync-helper-release.yml").read_text()
    sync_script = (root / "scripts" / "sync-jianying-device.py").read_text()
    windows_build = (root / "sync-helper" / "build.ps1").read_text()
    macos_build = (root / "sync-helper" / "build.sh").read_text()

    assert requirements.strip() == "pyinstaller==6.22.2"
    assert "Test-Path -LiteralPath 'B:\\'" in windows
    assert "$env:LOCALAPPDATA" in windows
    assert "Register-ScheduledTask" in windows
    assert "initial sync failed" in windows
    assert "LaunchAgents" in macos and "launchctl bootstrap" in macos
    assert '"$INSTALL" --server-url' in macos
    assert "RunAtLoad" in plist and "KeepAlive" in plist
    assert "windows-latest" in workflow and "macos-14" in workflow
    assert "VIDEO_WORKBENCH_DEVICE_BEARER_TOKEN" not in workflow
    assert "${{ github.token }}" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "gh release upload" in workflow
    assert "install-windows.ps1" in windows_build
    assert "install-macos.sh" in macos_build
    assert "runpy.run_path" in sync_script
    assert "subprocess.run" not in sync_script
    for build in (windows_build, macos_build):
        assert "--hidden-import ctypes" in build
        assert "--hidden-import datetime" in build
