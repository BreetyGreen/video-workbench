from pathlib import Path

from app import models  # Register application tables before migration.
from app.db import Database


def test_sqlite_bootstrap_creates_missing_parent(tmp_path: Path):
    database_path = tmp_path / "fresh user" / "runtime" / "control-plane.db"
    database = Database(f"sqlite:///{database_path.as_posix()}")
    try:
        database.create_all()
        assert database_path.is_file()
        assert database.is_healthy()
    finally:
        database.engine.dispose()


def test_memory_database_bootstrap_does_not_create_directories(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = Database("sqlite:///:memory:")
    try:
        database.create_all()
        assert database.is_healthy()
        assert list(tmp_path.iterdir()) == []
    finally:
        database.engine.dispose()
