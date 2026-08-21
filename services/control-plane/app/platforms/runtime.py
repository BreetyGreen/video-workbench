from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    cache_dir: Path
    inbox_dir: Path

    @property
    def database_url(self) -> str:
        database_path = (self.data_dir / "control-plane.db").as_posix()
        return f"sqlite:///{database_path}"


def resolve_runtime_paths(
    *,
    system: str | None = None,
    home: Path | None = None,
) -> RuntimePaths:
    detected = system or platform.system()
    user_home = Path(home) if home is not None else Path.home().expanduser().resolve()

    if detected == "Darwin":
        return RuntimePaths(
            data_dir=user_home / "Library" / "Application Support" / "VideoWorkbench",
            cache_dir=user_home / "Library" / "Caches" / "VideoWorkbench",
            inbox_dir=user_home / "Movies" / "VideoWorkbench Inbox",
        )
    if detected == "Windows":
        data_dir = user_home / "AppData" / "Local" / "VideoWorkbench"
        return RuntimePaths(
            data_dir=data_dir,
            cache_dir=data_dir / "cache",
            inbox_dir=user_home / "Videos" / "VideoWorkbench Inbox",
        )
    return RuntimePaths(
        data_dir=user_home / ".local" / "share" / "VideoWorkbench",
        cache_dir=user_home / ".cache" / "VideoWorkbench",
        inbox_dir=user_home / "Videos" / "VideoWorkbench Inbox",
    )
