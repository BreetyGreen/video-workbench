from pathlib import Path, PurePosixPath
import os
import runpy
import plistlib
import io
import sys
from types import SimpleNamespace

import pytest


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
    assert "Test-Path -LiteralPath 'B:\\'" not in windows
    assert "$preferredRoot = $env:LOCALAPPDATA" in windows
    assert "[string]$InstallDir = ''" in windows
    assert "[string]$DataDir = ''" in windows
    assert "$env:LOCALAPPDATA" in windows
    assert "Register-ScheduledTask" in windows
    assert "-RestartCount 5" in windows
    assert "initial sync failed" in windows
    assert "Join-Path $PSScriptRoot 'VideoWorkbenchSync.exe'" in windows
    assert "LaunchAgents" in macos and "launchctl bootstrap" in macos
    assert '"$INSTALL" --server-url' in macos
    assert 'SOURCE="$ROOT/VideoWorkbenchSync"' in macos
    assert "RunAtLoad" in plist and "KeepAlive" in plist
    assert "windows-latest" in workflow and "macos-14" in workflow
    assert "VIDEO_WORKBENCH_DEVICE_BEARER_TOKEN" not in workflow
    assert "${{ github.token }}" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "gh release upload" in workflow
    assert "gh release create" in workflow and "--draft" in workflow
    assert "VideoWorkbench-Sync-Setup-macOS.zip.sha256" in macos_build
    assert "VideoWorkbench Sync Setup.app" in macos_build
    assert "MACOS_CODESIGN_IDENTITY" in macos_build
    assert 'rm -rf "$APP"' not in macos_build
    assert "trap 'rm -rf" not in macos_build
    assert "install-windows.ps1" in windows_build
    assert "install-macos.sh" in macos_build
    assert "runpy.run_path" in sync_script
    assert "subprocess.run" not in sync_script
    assert "consecutive_failures" in sync_script and "retry_in=" in sync_script
    for build in (windows_build, macos_build):
        assert "--hidden-import ctypes" in build
        assert "--hidden-import datetime" in build


def test_macos_setup_validates_urls_and_builds_safe_plist() -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    assert setup["validate_server_url"](" https://video.example.com/api/ ") == "https://video.example.com/api"
    for invalid in ("http://video.example.com", "https://", "https://user:secret@example.com", "https://x.test?a=1"):
        try:
            setup["validate_server_url"](invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe URL: {invalid}")
    payload = setup["launch_agent_payload"](
        PurePosixPath("/Users/A & B/Applications/VideoWorkbenchSync"),
        "https://video.example.com/a&b",
        PurePosixPath("/Users/A & B/Library/Application Support/VideoWorkbench Sync"),
    )
    encoded = plistlib.dumps(payload)
    decoded = plistlib.loads(encoded)
    assert decoded["ProgramArguments"][0] == "/Users/A & B/Applications/VideoWorkbenchSync"
    assert decoded["ProgramArguments"][2] == "https://video.example.com/a&b"
    assert decoded["ProgramArguments"][-1] == "--watch"


def test_macos_setup_dialog_cancellation_and_hidden_input() -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    calls = []

    def cancelled(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="execution error: User canceled. (-128)")

    try:
        setup["ask_text"]("pair", hidden=True, runner=cancelled)
    except setup["SetupCancelled"]:
        pass
    else:
        raise AssertionError("cancellation was not propagated")
    assert "with hidden answer" in calls[0][-1]


def test_macos_setup_recognizes_localized_cancel_and_uses_valid_alert_styles() -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))

    def cancelled(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="执行错误：用户已取消。(-128)")

    with pytest.raises(setup["SetupCancelled"]):
        setup["run_osascript"]("display dialog", runner=cancelled)

    scripts = []

    def succeeded(args, **kwargs):
        scripts.append(args[-1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    setup["show_message"]("ok", runner=succeeded)
    setup["show_message"]("bad", is_error=True, runner=succeeded)
    assert scripts[0].endswith("as informational")
    assert scripts[1].endswith("as critical")


def test_macos_setup_failure_does_not_replace_existing_install(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    helper = tmp_path / "bundled helper"
    helper.write_bytes(b"new")
    destination = tmp_path / "Applications" / "VideoWorkbenchSync"
    destination.parent.mkdir()
    destination.write_bytes(b"old")
    calls = []

    def failed(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="network failed")

    try:
        setup["install"]("https://video.example.com", "do-not-log", home=tmp_path, helper=helper, runner=failed)
    except RuntimeError:
        pass
    else:
        raise AssertionError("pairing failure was not reported")
    assert destination.read_bytes() == b"old"
    assert calls[0][0][1:3] == ["--server-url", "https://video.example.com"]
    assert "do-not-log" not in calls[0][0]
    assert calls[0][1]["input"] == "do-not-log\n"


def test_macos_setup_success_pairs_only_then_stops_old_agent_and_installs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    helper = tmp_path / "bundled helper"
    helper.write_bytes(b"new-helper")
    destination = tmp_path / "Applications" / "VideoWorkbenchSync"
    destination.parent.mkdir()
    destination.write_bytes(b"old-helper")
    events = []

    def runner(args, **kwargs):
        if "--data-dir" in args:
            events.append("pair")
            assert "--pair-only" in args
            assert "--pairing-code-stdin" in args
            data_dir = Path(args[args.index("--data-dir") + 1])
            token = data_dir / "runtime" / "device-token.json"
            token.parent.mkdir(parents=True)
            token.write_text('{"device_id":"one","token":"secret"}', encoding="utf-8")
        elif "bootout" in args:
            events.append("bootout")
            assert destination.read_bytes() == b"old-helper"
        elif "bootstrap" in args:
            events.append("bootstrap")
            assert destination.read_bytes() == b"new-helper"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    setup["install"]("https://video.example.com/a&b", "secret", home=tmp_path, helper=helper, runner=runner, uid=501)
    assert events == ["pair", "bootout", "bootstrap"]
    token_path = tmp_path / "Library" / "Application Support" / "VideoWorkbench Sync" / "runtime" / "device-token.json"
    assert token_path.read_text(encoding="utf-8") == '{"device_id":"one","token":"secret"}'
    if os.name != "nt":
        assert token_path.stat().st_mode & 0o777 == 0o600
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.video-workbench.sync.plist"
    with plist_path.open("rb") as stream:
        payload = plistlib.load(stream)
    assert payload["ProgramArguments"] == [
        str(destination),
        "--server-url",
        "https://video.example.com/a&b",
        "--data-dir",
        str(token_path.parents[1]),
        "--watch",
    ]


@pytest.mark.parametrize("failed_replace", [1, 2, 3])
def test_macos_setup_rolls_back_each_replace_boundary(tmp_path: Path, failed_replace: int) -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    helper = tmp_path / "bundled-helper"
    helper.write_bytes(b"new-helper")
    destination = tmp_path / "Applications" / "VideoWorkbenchSync"
    token = tmp_path / "Library" / "Application Support" / "VideoWorkbench Sync" / "runtime" / "device-token.json"
    plist = tmp_path / "Library" / "LaunchAgents" / "com.video-workbench.sync.plist"
    for path, content in ((destination, b"old-helper"), (token, b"old-token"), (plist, b"old-plist")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    calls = []
    replacements = 0

    def runner(args, **kwargs):
        if "--pair-only" in args:
            staged_data = Path(args[args.index("--data-dir") + 1])
            staged_token = staged_data / "runtime" / "device-token.json"
            staged_token.parent.mkdir(parents=True)
            staged_token.write_text('{"token":"new-token"}', encoding="utf-8")
        elif "bootout" in args:
            calls.append("bootout")
        elif "bootstrap" in args:
            calls.append("bootstrap-old")
            assert plist.read_bytes() == b"old-plist"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def replacer(source, target):
        nonlocal replacements
        replacements += 1
        if replacements == failed_replace:
            raise OSError("injected replace failure")
        os.replace(source, target)

    with pytest.raises(RuntimeError, match="已恢复之前的安装"):
        setup["install"]("https://video.example.com", "code", home=tmp_path, helper=helper, runner=runner, uid=501, replacer=replacer)
    assert destination.read_bytes() == b"old-helper"
    assert token.read_bytes() == b"old-token"
    assert plist.read_bytes() == b"old-plist"
    assert calls == ["bootout", "bootstrap-old"]
    if os.name != "nt":
        assert all(path.stat().st_mode & 0o777 == 0o640 for path in (destination, token, plist))


def test_macos_setup_rolls_back_when_new_agent_bootstrap_fails(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    helper = tmp_path / "helper"
    helper.write_bytes(b"new")
    destination = tmp_path / "Applications" / "VideoWorkbenchSync"
    token = tmp_path / "Library" / "Application Support" / "VideoWorkbench Sync" / "runtime" / "device-token.json"
    plist = tmp_path / "Library" / "LaunchAgents" / "com.video-workbench.sync.plist"
    for path, content in ((destination, b"old-helper"), (token, b"old-token"), (plist, b"old-plist")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    bootstraps = 0

    def runner(args, **kwargs):
        nonlocal bootstraps
        if "--pair-only" in args:
            staged_data = Path(args[args.index("--data-dir") + 1])
            staged_token = staged_data / "runtime" / "device-token.json"
            staged_token.parent.mkdir(parents=True)
            staged_token.write_text('{"token":"new"}', encoding="utf-8")
        elif "bootstrap" in args:
            bootstraps += 1
            if bootstraps == 1:
                return SimpleNamespace(returncode=5, stdout="", stderr="new agent rejected")
            assert plist.read_bytes() == b"old-plist"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="已恢复之前的安装"):
        setup["install"]("https://video.example.com", "code", home=tmp_path, helper=helper, runner=runner, uid=501)
    assert (destination.read_bytes(), token.read_bytes(), plist.read_bytes()) == (b"old-helper", b"old-token", b"old-plist")
    assert bootstraps == 2


def test_macos_setup_preserves_backup_and_reports_manual_recovery_if_rollback_fails(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    setup = runpy.run_path(str(root / "sync-helper" / "macos_setup.py"))
    helper = tmp_path / "helper"
    helper.write_bytes(b"new")
    destination = tmp_path / "Applications" / "VideoWorkbenchSync"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-helper")
    replacements = 0

    def runner(args, **kwargs):
        if "--pair-only" in args:
            staged_data = Path(args[args.index("--data-dir") + 1])
            staged_token = staged_data / "runtime" / "device-token.json"
            staged_token.parent.mkdir(parents=True)
            staged_token.write_text('{"token":"new"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def replacer(source, target):
        nonlocal replacements
        replacements += 1
        if replacements >= 2:
            raise OSError("replacement and rollback both failed")
        os.replace(source, target)

    with pytest.raises(RuntimeError, match="需要人工处理.*setup-backups"):
        setup["install"]("https://video.example.com", "code", home=tmp_path, helper=helper, runner=runner, uid=501, replacer=replacer)
    backups = list((tmp_path / "Library" / "Application Support" / "VideoWorkbench Sync" / "setup-backups").glob("*"))
    assert len(backups) == 1
    assert (backups[0] / "helper").read_bytes() == b"old-helper"


def test_sync_helper_pair_only_does_not_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    namespace = runpy.run_path(str(root / "scripts" / "sync-jianying-device.py"))
    monkeypatch.setattr(sys, "argv", ["sync", "--server-url", "https://video.example.com", "--data-dir", str(tmp_path), "--pair-only"])
    monkeypatch.setitem(namespace["main"].__globals__, "load_or_pair_token", lambda *args: "paired")
    monkeypatch.setitem(namespace["main"].__globals__, "prepare_runtime", lambda *args: pytest.fail("pair-only performed sync work"))
    assert namespace["main"]() == 0


def test_sync_helper_explicit_stdin_pairing_does_not_call_getpass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    namespace = runpy.run_path(str(root / "scripts" / "sync-jianying-device.py"))
    posted = {}

    class FakeHttp:
        def __init__(self, server_url):
            posted["server_url"] = server_url

        def post_json(self, route, payload):
            posted["route"] = route
            posted["payload"] = payload
            return {"device_id": "device-one", "token": "issued-token"}

    monkeypatch.setitem(namespace["load_or_pair_token"].__globals__, "UrlLibSyncHttp", FakeHttp)
    monkeypatch.setitem(namespace["load_or_pair_token"].__globals__, "getpass", SimpleNamespace(getpass=lambda *_: pytest.fail("getpass called")))
    monkeypatch.setattr(sys, "stdin", io.StringIO("one-time-code\n"))
    token = namespace["load_or_pair_token"](
        "https://video.example.com",
        tmp_path,
        "MacBook",
        pairing_code_stdin=True,
    )
    assert token == "issued-token"
    assert posted["payload"] == {"code": "one-time-code", "name": "MacBook"}
    assert namespace["read_stored_device_token"](tmp_path / "runtime" / "device-token.json") == "issued-token"


def test_sync_helper_protects_device_token_on_windows(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    namespace = runpy.run_path(str(root / "scripts" / "sync-jianying-device.py"))
    token_path = tmp_path / "runtime" / "device-token.json"
    token = "device-secret-for-storage-test"

    namespace["store_device_token"](token_path, device_id="device-1", token=token)

    assert namespace["read_stored_device_token"](token_path) == token
    if os.name == "nt":
        assert token not in token_path.read_text(encoding="utf-8")
        assert "windows-dpapi-v1" in token_path.read_text(encoding="utf-8")
