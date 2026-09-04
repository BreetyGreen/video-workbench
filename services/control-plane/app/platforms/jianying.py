from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class JianyingLocation:
    installed: bool
    app_path: Path | None
    draft_root: Path | None
    candidates: tuple[Path, ...]
    needs_folder_picker: bool


def validate_draft_root(path: Path) -> bool:
    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            return False
        if candidate.name == "com.lveditor.draft":
            return True
        return any(
            child.is_dir() and not child.is_symlink() and (child / "draft_info.json").is_file()
            for child in candidate.iterdir()
        )
    except OSError:
        return False


def _bounded_draft_roots(root: Path, *, max_depth: int = 4) -> set[Path]:
    matches: set[Path] = set()
    if not root.is_dir() or root.is_symlink():
        return matches

    try:
        for current, dirnames, _filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            try:
                depth = len(current_path.relative_to(root).parts)
            except ValueError:
                continue
            dirnames[:] = [
                name for name in dirnames if not (current_path / name).is_symlink()
            ]
            if validate_draft_root(current_path):
                matches.add(current_path)
                dirnames[:] = []
                continue
            if depth >= max_depth:
                dirnames[:] = []
    except OSError:
        return matches
    return matches


def _application_candidates(home: Path, mdfind_output: str) -> tuple[Path, ...]:
    candidates = {
        Path(line.strip())
        for line in mdfind_output.splitlines()
        if line.strip().lower().endswith(".app")
    }
    candidates.update(
        {
            Path("/Applications/JianyingPro.app"),
            Path("/Applications/CapCut.app"),
            home / "Applications" / "JianyingPro.app",
            home / "Applications" / "CapCut.app",
        }
    )
    existing = [path for path in candidates if path.is_dir() and not path.is_symlink()]
    return tuple(
        sorted(
            existing,
            key=lambda path: (
                0 if "jianying" in path.name.lower() else 1,
                str(path).casefold(),
            ),
        )
    )


def _bounded_windows_applications(
    roots: tuple[Path, ...],
    *,
    max_depth: int = 3,
) -> tuple[Path, ...]:
    matches: set[Path] = set()
    executable_names = {"jianyingpro.exe", "capcut.exe"}
    for root in roots:
        candidate = Path(root)
        if candidate.is_file() and candidate.name.casefold() in executable_names:
            matches.add(candidate)
            continue
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        try:
            for current, dirnames, filenames in os.walk(candidate, followlinks=False):
                current_path = Path(current)
                try:
                    depth = len(current_path.relative_to(candidate).parts)
                except ValueError:
                    continue
                dirnames[:] = [
                    name for name in dirnames if not (current_path / name).is_symlink()
                ]
                for filename in filenames:
                    if filename.casefold() in executable_names:
                        matches.add(current_path / filename)
                if depth >= max_depth:
                    dirnames[:] = []
        except OSError:
            continue
    return tuple(
        sorted(
            matches,
            key=lambda path: (
                0 if path.name.casefold() == "jianyingpro.exe" else 1,
                str(path).casefold(),
            ),
        )
    )
def discover_jianying(
    *,
    home: Path,
    system: str,
    mdfind_output: str = "",
    windows_app_roots: tuple[Path, ...] | None = None,
    windows_draft_roots: tuple[Path, ...] | None = None,
) -> JianyingLocation:
    user_home = Path(home)
    if system == "Darwin":
        app_candidates = _application_candidates(user_home, mdfind_output)
        search_roots = (
            user_home / "Movies",
            user_home / "Documents",
            user_home / "Library" / "Application Support",
        )
    elif system == "Windows":
        local = user_home / "AppData" / "Local"
        app_roots = windows_app_roots or (
            Path(r"B:\Apps\JianyingPro"),
            local / "JianyingPro",
            local / "CapCut",
        )
        app_candidates = _bounded_windows_applications(tuple(Path(path) for path in app_roots))
        search_roots = windows_draft_roots or (
            Path(r"B:\JianyingData\Drafts\JianyingPro Drafts"),
            local / "JianyingPro" / "User Data" / "Projects",
            local / "CapCut" / "User Data" / "Projects",
            user_home / "Videos",
            user_home / "Documents",
        )
    else:
        app_candidates = ()
        search_roots = (
            user_home / "Movies",
            user_home / "Documents",
        )
    draft_candidates: set[Path] = set()
    for root in search_roots:
        draft_candidates.update(_bounded_draft_roots(root))
    candidates = tuple(sorted(draft_candidates, key=lambda path: str(path).casefold()))
    draft_root = candidates[0] if len(candidates) == 1 else None

    return JianyingLocation(
        installed=bool(app_candidates),
        app_path=app_candidates[0] if app_candidates else None,
        draft_root=draft_root,
        candidates=candidates,
        needs_folder_picker=draft_root is None,
    )
