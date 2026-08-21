from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
}
ALLOWED_MIME_PREFIXES = ("video/", "audio/", "image/")


@dataclass(frozen=True)
class ConnectorSettings:
    client_id: str
    client_secret: str
    control_plane_url: str
    robot_code: str = ""
    max_file_bytes: int = 500 * 1024 * 1024
    dedup_database: Path = Path("data/dingtalk/dedup.db")

    @classmethod
    def from_env(cls) -> "ConnectorSettings":
        return cls(
            client_id=os.getenv("DINGTALK_CLIENT_ID", ""),
            client_secret=os.getenv("DINGTALK_CLIENT_SECRET", ""),
            robot_code=os.getenv("DINGTALK_ROBOT_CODE", ""),
            control_plane_url=os.getenv("CONTROL_PLANE_URL", "http://127.0.0.1:8130"),
            max_file_bytes=int(os.getenv("DINGTALK_MAX_FILE_BYTES", str(500 * 1024 * 1024))),
            dedup_database=Path(os.getenv("DINGTALK_DEDUP_DATABASE", "data/dingtalk/dedup.db")),
        )

    def status(self) -> dict[str, str]:
        missing = []
        if not self.client_id:
            missing.append("client_id")
        if not self.client_secret:
            missing.append("client_secret")
        if missing:
            return {
                "status": "not_configured",
                "reason": f"missing_{'_and_'.join(missing)}",
            }
        return {"status": "configured"}


@dataclass(frozen=True)
class DingTalkFile:
    name: str
    mime_type: str
    size_bytes: int
    download_code: str
    robot_code: str


@dataclass(frozen=True)
class DingTalkEvent:
    message_id: str
    sender_id: str
    conversation_id: str
    title: str
    content_type: str
    rights_confirmed: bool
    files: list[DingTalkFile] = field(default_factory=list)


@dataclass(frozen=True)
class DownloadedFile:
    name: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class IntakeResult:
    status: str
    reason: str = ""
    task_id: str = ""


class Downloader(Protocol):
    def download(self, attachment: DingTalkFile) -> DownloadedFile: ...


class ControlPlane(Protocol):
    def create_task(self, **kwargs) -> str: ...


class DedupStore:
    def __init__(self, database: str | Path):
        database_value = str(database)
        if database_value != ":memory:":
            Path(database_value).resolve().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_value, check_same_thread=False)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS processed_messages (message_id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.connection.commit()

    def seen(self, message_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM processed_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return row is not None

    def mark(self, message_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO processed_messages(message_id) VALUES (?)",
            (message_id,),
        )
        self.connection.commit()


def mime_allowed(mime_type: str) -> bool:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    return normalized in ALLOWED_MIME_TYPES or normalized.startswith(ALLOWED_MIME_PREFIXES)


class DingTalkIntake:
    def __init__(
        self,
        *,
        downloader: Downloader,
        control_plane: ControlPlane,
        dedup: DedupStore,
        max_file_bytes: int,
    ):
        self.downloader = downloader
        self.control_plane = control_plane
        self.dedup = dedup
        self.max_file_bytes = max_file_bytes

    def handle(self, event: DingTalkEvent) -> IntakeResult:
        if self.dedup.seen(event.message_id):
            return IntakeResult(status="duplicate", reason="message_already_processed")
        if not event.files:
            return IntakeResult(status="rejected", reason="no_supported_files")

        downloaded_files: list[DownloadedFile] = []
        for attachment in event.files:
            if not mime_allowed(attachment.mime_type):
                return IntakeResult(status="rejected", reason="unsupported_mime_type")
            if attachment.size_bytes > self.max_file_bytes:
                return IntakeResult(status="rejected", reason="file_too_large")
            downloaded = self.downloader.download(attachment)
            if not mime_allowed(downloaded.mime_type):
                return IntakeResult(status="rejected", reason="downloaded_mime_type_mismatch")
            if len(downloaded.content) > self.max_file_bytes:
                return IntakeResult(status="rejected", reason="downloaded_file_too_large")
            downloaded_files.append(downloaded)

        task_id = self.control_plane.create_task(
            title=event.title,
            content_type=event.content_type,
            rights_confirmed=event.rights_confirmed,
            files=downloaded_files,
            source_type="dingtalk",
            source_user=event.sender_id,
            source_conversation=event.conversation_id,
            source_message_id=event.message_id,
            deduplication_key=f"dingtalk:{event.message_id}",
        )
        self.dedup.mark(event.message_id)
        return IntakeResult(status="created", task_id=task_id)
