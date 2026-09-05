#!/usr/bin/env python3
"""Native-dialog installer for the macOS VideoWorkbench sync helper."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit


LABEL = "com.video-workbench.sync"


class SetupCancelled(Exception):
    """The user cancelled a native setup dialog."""


def validate_server_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请输入以 https:// 开头的有效服务器地址（不要包含用户名或密码）。")
    if parsed.query or parsed.fragment:
        raise ValueError("服务器地址不能包含查询参数或 # 片段。")
    return value


def run_osascript(script: str, *, runner=subprocess.run) -> str:
    result = runner(
        ["/usr/bin/osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 and ("User canceled" in result.stderr or "-128" in result.stderr):
        raise SetupCancelled
    if result.returncode != 0:
        raise RuntimeError("无法打开 macOS 设置对话框。请从安装包重新运行设置程序。")
    return result.stdout.rstrip("\n")


def ask_text(prompt: str, *, hidden: bool = False, runner=subprocess.run) -> str:
    hidden_clause = " with hidden answer" if hidden else ""
    script = (
        'text returned of (display dialog "'
        + prompt.replace("\\", "\\\\").replace('"', '\\"')
        + '" default answer "" buttons {"取消", "继续"} default button "继续"'
        + hidden_clause
        + ")"
    )
    return run_osascript(script, runner=runner).strip()


def show_message(message: str, *, is_error: bool = False, runner=subprocess.run) -> None:
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    icon = "critical" if is_error else "informational"
    run_osascript(f'display alert "VideoWorkbench" message "{escaped}" as {icon}', runner=runner)


def launch_agent_payload(executable: Path, server_url: str, data_dir: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(executable), "--server-url", server_url, "--data-dir", str(data_dir), "--watch"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(data_dir / "sync.log"),
        "StandardErrorPath": str(data_dir / "sync-error.log"),
    }


def bundled_helper() -> Path:
    bundle = Path(sys.executable).resolve().parents[1]
    candidate = bundle / "Resources" / "VideoWorkbenchSync"
    if candidate.is_file():
        return candidate
    development = Path(__file__).resolve().parent / "dist" / "VideoWorkbenchSync"
    if development.is_file():
        return development
    raise FileNotFoundError("安装包中缺少 VideoWorkbenchSync 助手，请重新下载安装包。")


def install(
    server_url: str,
    pairing_code: str,
    *,
    home: Path,
    helper: Path,
    runner=subprocess.run,
    uid: int | None = None,
    replacer=os.replace,
) -> None:
    applications = home / "Applications"
    destination = applications / "VideoWorkbenchSync"
    data_dir = home / "Library" / "Application Support" / "VideoWorkbench Sync"
    agents = home / "Library" / "LaunchAgents"
    plist_path = agents / f"{LABEL}.plist"
    applications.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    agents.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="VideoWorkbenchSetup-") as temporary:
        temporary_path = Path(temporary)
        staged_helper = temporary_path / "VideoWorkbenchSync"
        staged_data = temporary_path / "pairing-data"
        shutil.copy2(helper, staged_helper)
        staged_helper.chmod(0o755)
        paired = runner(
            [
                str(staged_helper),
                "--server-url",
                server_url,
                "--data-dir",
                str(staged_data),
                "--pair-only",
                "--pairing-code-stdin",
            ],
            input=pairing_code + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if paired.returncode != 0:
            raise RuntimeError("配对或连接服务器失败。请确认 HTTPS 地址、一次性码仍有效，并检查网络后重试。")
        token = staged_data / "runtime" / "device-token.json"
        if not token.is_file():
            raise RuntimeError("服务器未返回有效的设备凭据，请生成新的配对码后重试。")

        staged_plist = temporary_path / f"{LABEL}.plist"
        with staged_plist.open("wb") as stream:
            plistlib.dump(launch_agent_payload(destination, server_url, data_dir), stream, sort_keys=False)
        staged_destination = applications / ".VideoWorkbenchSync.new"
        shutil.copy2(staged_helper, staged_destination)
        staged_destination.chmod(0o755)
        staged_token = data_dir / "runtime" / ".device-token.json.new"
        staged_token.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(token, staged_token)
        os.chmod(staged_token, 0o600)
        staged_plist_destination = agents / f".{LABEL}.plist.new"
        shutil.copy2(staged_plist, staged_plist_destination)

        token_path = data_dir / "runtime" / "device-token.json"
        targets = (
            ("helper", destination, staged_destination),
            ("token", token_path, staged_token),
            ("launch-agent.plist", plist_path, staged_plist_destination),
        )
        backup_dir = data_dir / "setup-backups" / uuid.uuid4().hex
        backup_dir.mkdir(parents=True, mode=0o700)
        os.chmod(backup_dir, 0o700)
        existed: dict[Path, Path | None] = {}
        for name, target, _staged in targets:
            if target.is_symlink():
                raise RuntimeError(f"拒绝替换符号链接：{target}")
            if target.is_file():
                backup = backup_dir / name
                shutil.copy2(target, backup)
                existed[target] = backup
            else:
                existed[target] = None

        domain = f"gui/{os.getuid() if uid is None else uid}"
        old_agent_existed = existed[plist_path] is not None
        try:
            runner(["/bin/launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True, check=False)
            for _name, target, staged in targets:
                replacer(staged, target)
            loaded = runner(
                ["/bin/launchctl", "bootstrap", domain, str(plist_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            if loaded.returncode != 0:
                raise OSError("new LaunchAgent bootstrap failed")
        except Exception as install_error:
            rollback_errors = []
            for name, target, _staged in targets:
                backup = existed[target]
                try:
                    if backup is None:
                        if target.exists() or target.is_symlink():
                            target.unlink()
                    else:
                        restore = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}")
                        shutil.copy2(backup, restore)
                        replacer(restore, target)
                except Exception as rollback_error:
                    rollback_errors.append(f"{name}: {type(rollback_error).__name__}")
            if not rollback_errors and old_agent_existed:
                restored = runner(
                    ["/bin/launchctl", "bootstrap", domain, str(plist_path)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if restored.returncode != 0:
                    rollback_errors.append("old LaunchAgent bootstrap failed")
            if rollback_errors:
                details = ", ".join(rollback_errors)
                raise RuntimeError(f"安装和自动回滚均失败，需要人工处理。备份保留在 {backup_dir}（{details}）。") from install_error
            if any(backup is not None for backup in existed.values()):
                raise RuntimeError("设置未完成，已恢复之前的安装和自动启动状态；请检查服务器地址、权限或系统日志后重试。") from install_error
            raise RuntimeError("设置未完成，已移除本次产生的文件；未创建自动启动项。请检查权限或系统日志后重试。") from install_error


def main() -> int:
    try:
        server_url = validate_server_url(ask_text("请输入 VideoWorkbench 服务器 HTTPS 地址"))
        pairing_code = ask_text("请输入服务器生成的一次性配对码", hidden=True)
        if not pairing_code:
            raise ValueError("配对码不能为空。")
        install(server_url, pairing_code, home=Path.home(), helper=bundled_helper())
        show_message("设置完成。同步助手已安装，并会在您登录后自动运行。")
        return 0
    except SetupCancelled:
        return 0
    except Exception as error:
        try:
            show_message(str(error), is_error=True)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
