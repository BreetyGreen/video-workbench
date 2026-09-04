from __future__ import annotations

import logging
import mimetypes
import re
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
    message_text = str(
        content.get("text")
        or (data.get("text") or {}).get("content")
        or data.get("contentText")
        or ""
    ).strip()
    role = "material"
    if "#教程" in message_text:
        role = "tutorial"
    elif "#案例" in message_text or "#参考" in message_text:
        role = "reference"
    rights_status = "unknown"
    if "#商用授权" in message_text:
        rights_status = "commercial_authorized"
    elif "#个人学习" in message_text:
        rights_status = "personal_learning"
    clean_title = re.sub(r"#(?:教程|案例|参考|素材|商用授权|个人学习)\s*", "", message_text).strip()
    attachment = DingTalkFile(
        name=filename,
        mime_type=str(content.get("mimeType") or guessed_mime),
        size_bytes=int(content.get("fileSize") or 0),
        download_code=str(content.get("downloadCode") or ""),
        robot_code=str(data.get("robotCode") or settings.robot_code),
        role=role,
        rights_status=rights_status,
    )
    return DingTalkEvent(
        message_id=str(data.get("msgId") or data.get("messageId") or ""),
        sender_id=str(data.get("senderStaffId") or data.get("senderId") or "unknown"),
        conversation_id=str(data.get("conversationId") or "direct"),
        title=clean_title or f"钉钉课程-{filename}",
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
