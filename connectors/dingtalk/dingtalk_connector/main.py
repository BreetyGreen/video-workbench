from __future__ import annotations

import logging
import mimetypes
import sys
from typing import Any

import dingtalk_stream
from dingtalk_stream import AckMessage

from dingtalk_connector.control_plane import ControlPlaneClient
from dingtalk_connector.downloader import DingTalkDownloader
from dingtalk_connector.intake import (
    ConnectorSettings,
    DedupStore,
    DingTalkEvent,
    DingTalkFile,
    DingTalkIntake,
)


def event_from_callback(data: dict[str, Any], settings: ConnectorSettings) -> DingTalkEvent:
    content = data.get("content") or {}
    message_type = str(data.get("msgtype") or data.get("msgType") or "file").lower()
    filename = str(content.get("fileName") or content.get("name") or f"dingtalk-{message_type}")
    guessed_mime = mimetypes.guess_type(filename)[0] or {
        "video": "video/mp4",
        "audio": "audio/mpeg",
        "picture": "image/jpeg",
        "image": "image/jpeg",
        "file": "application/octet-stream",
    }.get(message_type, "application/octet-stream")
    attachment = DingTalkFile(
        name=filename,
        mime_type=str(content.get("mimeType") or guessed_mime),
        size_bytes=int(content.get("fileSize") or 0),
        download_code=str(content.get("downloadCode") or ""),
        robot_code=str(data.get("robotCode") or settings.robot_code),
    )
    return DingTalkEvent(
        message_id=str(data.get("msgId") or data.get("messageId") or ""),
        sender_id=str(data.get("senderStaffId") or data.get("senderId") or "unknown"),
        conversation_id=str(data.get("conversationId") or "direct"),
        title=f"钉钉素材-{filename}",
        content_type="unclassified",
        rights_confirmed=False,
        files=[attachment],
    )


class VideoIntakeHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, intake: DingTalkIntake, settings: ConnectorSettings):
        super().__init__()
        self.intake = intake
        self.settings = settings

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        result = self.intake.handle(event_from_callback(callback.data, self.settings))
        return AckMessage.STATUS_OK, result.status


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = ConnectorSettings.from_env()
    status = settings.status()
    if status["status"] != "configured":
        logging.error("DingTalk connector not configured: %s", status["reason"])
        sys.exit(2)

    downloader = DingTalkDownloader(settings)
    intake = DingTalkIntake(
        downloader=downloader,
        control_plane=ControlPlaneClient(settings.control_plane_url),
        dedup=DedupStore(settings.dedup_database),
        max_file_bytes=settings.max_file_bytes,
    )
    credential = dingtalk_stream.Credential(settings.client_id, settings.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        VideoIntakeHandler(intake, settings),
    )
    client.start_forever()


if __name__ == "__main__":
    main()
