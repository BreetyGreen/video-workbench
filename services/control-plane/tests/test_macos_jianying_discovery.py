from pathlib import Path

import pytest

from app.platforms.jianying import discover_jianying, validate_draft_root


def test_macos_discovers_app_and_valid_draft_root(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    app = home / "Applications" / "JianyingPro.app"
    draft = home / "Movies" / "JianyingPro" / "com.lveditor.draft"
    app.mkdir(parents=True)
    (draft / "sample").mkdir(parents=True)
    (draft / "sample" / "draft_info.json").write_text("{}", encoding="utf-8")

    result = discover_jianying(home=home, system="Darwin", mdfind_output=str(app))

    assert result.installed is True
    assert result.app_path == app
    assert result.draft_root == draft
    assert result.needs_folder_picker is False


def test_windows_discovers_custom_app_and_draft_root(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    app_root = tmp_path / "Apps" / "JianyingPro"
    app = app_root / "11.3.0" / "JianyingPro.exe"
    draft = tmp_path / "JianyingData" / "Drafts" / "JianyingPro Drafts"
    app.parent.mkdir(parents=True)
    app.write_bytes(b"MZ")
    (draft / "sample").mkdir(parents=True)
    (draft / "sample" / "draft_info.json").write_text("{}", encoding="utf-8")

    result = discover_jianying(
        home=home,
        system="Windows",
        windows_app_roots=(app_root,),
        windows_draft_roots=(draft,),
    )

    assert result.installed is True
    assert result.app_path == app
    assert result.draft_root == draft
    assert result.needs_folder_picker is False


def test_ambiguous_roots_require_one_picker(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    for parent in (home / "Movies" / "A", home / "Documents" / "B"):
        draft = parent / "com.lveditor.draft"
        (draft / "sample").mkdir(parents=True)
        (draft / "sample" / "draft_info.json").write_text("{}", encoding="utf-8")

    result = discover_jianying(home=home, system="Darwin")

    assert result.draft_root is None
    assert result.candidates == tuple(sorted(result.candidates, key=str))
    assert len(result.candidates) == 2
    assert result.needs_folder_picker is True


def test_discovery_does_not_descend_beyond_four_levels(tmp_path: Path):
    home = tmp_path / "Users" / "alice"
    too_deep = home / "Movies" / "one" / "two" / "three" / "four" / "five" / "com.lveditor.draft"
    (too_deep / "sample").mkdir(parents=True)
    (too_deep / "sample" / "draft_info.json").write_text("{}", encoding="utf-8")

    result = discover_jianying(home=home, system="Darwin")

    assert result.draft_root is None
    assert result.candidates == ()


def test_symlink_is_not_a_valid_draft_root(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this Windows host")

    assert validate_draft_root(link) is False
