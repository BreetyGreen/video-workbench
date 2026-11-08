"""Exact-input director cache. An unknown published revision always disables reuse."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from pydantic import ValidationError

from app.schemas.analysis import EditRecipe


CACHE_VERSION = 1
MAX_CACHE_BYTES = 1024 * 1024


def director_cache_key(
    inputs: dict, image_paths: list[Path], workflow_revision: str
) -> str | None:
    if not workflow_revision or not workflow_revision.strip():
        return None
    try:
        image_hashes = []
        for path in image_paths:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(128 * 1024), b""):
                    digest.update(chunk)
            image_hashes.append(digest.hexdigest())
        payload = json.dumps(
            {"version": CACHE_VERSION, "workflow_revision": workflow_revision,
             "inputs": inputs, "image_hashes": image_hashes},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (OSError, TypeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    if not isinstance(key, str) or re.fullmatch(r"[a-f0-9]{64}", key) is None:
        raise ValueError("invalid_cache_key")
    return cache_dir.resolve() / f"{key}.json"


def load_cached_recipe(cache_dir: Path, key: str) -> EditRecipe | None:
    target = _cache_path(cache_dir, key)
    try:
        if target.is_symlink():
            return None
        with target.open("rb") as source:
            content = source.read(MAX_CACHE_BYTES + 1)
        if len(content) > MAX_CACHE_BYTES:
            return None
        payload = json.loads(content)
        if (not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION
                or payload.get("key") != key):
            return None
        return EditRecipe.model_validate(payload.get("recipe"))
    except (OSError, ValueError, ValidationError):
        return None


def save_cached_recipe(cache_dir: Path, key: str, recipe: EditRecipe) -> None:
    target = _cache_path(cache_dir, key)
    # Validate again even when supplied a model_construct/model_copy instance.
    validated = EditRecipe.model_validate(recipe.model_dump(mode="json"))
    content = json.dumps(
        {"version": CACHE_VERSION, "key": key, "recipe": validated.model_dump(mode="json")},
        ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(content) > MAX_CACHE_BYTES:
        raise ValueError("cache_recipe_too_large")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("cache_target_is_symlink")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                         prefix=f".{key}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        # Only our freshly created temporary file is ever removed.
        if temporary is not None and temporary.exists():
            temporary.unlink()
