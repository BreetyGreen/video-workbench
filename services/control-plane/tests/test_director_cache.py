import importlib
import importlib.util
import re

import pytest

from app.schemas.analysis import EditRecipe


def service():
    name = "app.services.director_cache_service"
    assert importlib.util.find_spec(name) is not None, "director cache is not implemented"
    return importlib.import_module(name)


def recipe():
    return EditRecipe.model_validate(dict(
        hook_rules=["展示主体"], target_duration_seconds=6,
        pacing=[dict(from_second=0, to_second=6, instruction="切镜")],
        track_layout=["video"], caption_style="白字", audio_rules=[],
        prohibited_elements=[], qa_thresholds=dict(max_silence_seconds=1, max_black_seconds=.1)))


def test_blank_revision_disables_cache_without_reading_images(tmp_path):
    assert service().director_cache_key({}, [tmp_path / "missing"], "  ") is None


def test_canonical_inputs_and_content_not_path_determine_key(tmp_path):
    a, b = tmp_path / "first.png", tmp_path / "other.png"
    a.write_bytes(b"identical image content")
    b.write_bytes(a.read_bytes())
    key = service().director_cache_key({"b": 2, "a": "中文"}, [a], "rev1")
    assert re.fullmatch(r"[a-f0-9]{64}", key)
    assert key == service().director_cache_key({"a": "中文", "b": 2}, [b], "rev1")


def test_changed_text_image_order_content_or_revision_invalidates_key(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    make = service().director_cache_key
    key = make({"text": "原文"}, [a, b], "1")
    assert key != make({"text": "新文"}, [a, b], "1")
    assert key != make({"text": "原文"}, [b, a], "1")
    assert key != make({"text": "原文"}, [a, b], "2")
    a.write_bytes(b"changed")
    assert key != make({"text": "原文"}, [a, b], "1")


def test_unreadable_image_disables_cache(tmp_path):
    assert service().director_cache_key({}, [tmp_path / "missing"], "1") is None


def test_noncanonical_input_disables_cache():
    assert service().director_cache_key({"number": float("nan")}, [], "1") is None


def test_recipe_round_trip_and_atomic_replace(tmp_path, monkeypatch):
    module = service()
    calls = []
    replace = module.os.replace
    def observed(source, target):
        calls.append((source, target))
        return replace(source, target)
    monkeypatch.setattr(module.os, "replace", observed)
    key = "a" * 64
    module.save_cached_recipe(tmp_path, key, recipe())
    assert module.load_cached_recipe(tmp_path, key) == recipe()
    assert len(calls) == 1
    assert len(list(tmp_path.iterdir())) == 1
    assert "hook_rules" in (tmp_path / f"{key}.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["../outside", "", "A" * 64, "a" * 63, "a" * 65])
def test_invalid_key_never_accesses_paths(tmp_path, key):
    with pytest.raises(ValueError, match="invalid_cache_key"):
        service().save_cached_recipe(tmp_path, key, recipe())
    with pytest.raises(ValueError, match="invalid_cache_key"):
        service().load_cached_recipe(tmp_path, key)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("payload", ["not json", "{}", '{"recipe":{}}'])
def test_corruption_or_invalid_schema_is_cache_miss(tmp_path, payload):
    key = "a" * 64
    (tmp_path / f"{key}.json").write_text(payload, encoding="utf-8")
    assert service().load_cached_recipe(tmp_path, key) is None


def test_missing_cache_is_miss(tmp_path):
    assert service().load_cached_recipe(tmp_path, "a" * 64) is None


def test_failed_atomic_replace_keeps_previous_valid_recipe(tmp_path, monkeypatch):
    module = service()
    key = "a" * 64
    module.save_cached_recipe(tmp_path, key, recipe())
    def failed(source, target):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(module.os, "replace", failed)
    with pytest.raises(OSError):
        module.save_cached_recipe(tmp_path, key, recipe().model_copy(update={"caption_style": "new"}))
    assert module.load_cached_recipe(tmp_path, key) == recipe()
    assert len(list(tmp_path.iterdir())) == 1
