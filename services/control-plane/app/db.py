from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)

    def create_all(self) -> None:
        SQLModel.metadata.create_all(self.engine)
        if self.engine.url.get_backend_name() == "sqlite":
            self._migrate_sqlite()

    def _migrate_sqlite(self) -> None:
        """Apply additive columns needed by existing local databases."""
        with self.engine.begin() as connection:
            existing = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(video_tasks)"))
            }
            additions = {
                "archived_at": "ALTER TABLE video_tasks ADD COLUMN archived_at DATETIME",
                "archive_reason": "ALTER TABLE video_tasks ADD COLUMN archive_reason VARCHAR",
                "delivery_state": "ALTER TABLE video_tasks ADD COLUMN delivery_state VARCHAR",
                "delivery_provider_id": "ALTER TABLE video_tasks ADD COLUMN delivery_provider_id VARCHAR",
                "delivered_at": "ALTER TABLE video_tasks ADD COLUMN delivered_at DATETIME",
            }
            for column, statement in additions.items():
                if column not in existing:
                    connection.execute(text(statement))
            licensed_existing = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(licensed_assets)"))
            }
            licensed_additions = {
                "rights_status": "ALTER TABLE licensed_assets ADD COLUMN rights_status VARCHAR NOT NULL DEFAULT 'authorized'",
                "product_id": "ALTER TABLE licensed_assets ADD COLUMN product_id VARCHAR NOT NULL DEFAULT ''",
                "allowed_platforms_json": "ALTER TABLE licensed_assets ADD COLUMN allowed_platforms_json VARCHAR NOT NULL DEFAULT '[]'",
                "rights_expires_at": "ALTER TABLE licensed_assets ADD COLUMN rights_expires_at DATETIME",
            }
            for column, statement in licensed_additions.items():
                if column not in licensed_existing:
                    connection.execute(text(statement))

    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def is_healthy(self) -> bool:
        with Session(self.engine) as session:
            session.exec(text("SELECT 1"))
        return True
