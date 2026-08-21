from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from app.models import CloudCredential, OfficialUsageSnapshot, UsageBudget, UsageEvent
from app.services.secret_store import SecretStore, mask_access_key


def test_secret_store_encrypts_without_plaintext_and_round_trips():
    store = SecretStore("test-master-secret-with-enough-entropy")

    encrypted = store.encrypt("AKLT-example-sensitive-value")

    assert "AKLT-example-sensitive-value" not in encrypted
    assert store.decrypt(encrypted) == "AKLT-example-sensitive-value"
    assert mask_access_key("TEST1234567890XYZ") == "TEST****0XYZ"


def test_cloud_usage_tables_are_created(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'usage.db').as_posix()}")
    SQLModel.metadata.create_all(engine)

    assert {
        "cloud_credentials",
        "usage_events",
        "usage_budgets",
        "official_usage_snapshots",
    }.issubset(set(inspect(engine).get_table_names()))

    with Session(engine) as session:
        session.add(CloudCredential(provider="volcengine", access_key_id_masked="AKLT****0XYZ"))
        session.add(UsageBudget(id="default"))
        session.add(
            UsageEvent(
                provider="volcengine",
                service="tts",
                metric="characters",
                quantity=40,
                unit="characters",
            )
        )
        session.add(OfficialUsageSnapshot(kind="balance", payload_json="{}"))
        session.commit()
