from __future__ import annotations

from dataclasses import dataclass
import json

import httpx

from dingtalk_connector.downloader import DingTalkDownloader
from dingtalk_connector.intake import (
    ConnectorSettings,
    DedupStore,
    DingTalkEvent,
    DingTalkFile,
    DingTalkIntake,
    DownloadedFile,
)
from dingtalk_connector.main import event_from_callback


@dataclass
class FakeDownloader:
    payload: bytes = b"video"
    mime_type: str = "video/mp4"

    def download(self, attachment: DingTalkFile) -> DownloadedFile:
        return DownloadedFile(
            name=attachment.name,
            mime_type=self.mime_type,
            content=self.payload,
        )


class FakeControlPlane:
    def __init__(self):
        self.created_courses: list[dict[str, object]] = []

    def create_course(self, **kwargs) -> str:
        self.created_courses.append(kwargs)
        return "course-1"


def event(message_id: str = "m-1", *, mime_type: str = "video/mp4", size_bytes: int = 5) -> DingTalkEvent:
    return DingTalkEvent(
        message_id=message_id,
        sender_id="user-1",
        conversation_id="conversation-1",
        title="钉钉素材",
        content_type="pet",
        rights_confirmed=True,
        files=[
            DingTalkFile(
                name="raw.mp4",
                mime_type=mime_type,
                size_bytes=size_bytes,
                download_code="download-1",
                robot_code="robot-1",
                role="material",
                rights_status="commercial_authorized",
            )
        ],
    )


def connector(*, max_file_bytes: int = 100):
    control_plane = FakeControlPlane()
    intake = DingTalkIntake(
        downloader=FakeDownloader(),
        control_plane=control_plane,
        dedup=DedupStore(":memory:"),
        max_file_bytes=max_file_bytes,
    )
    return intake, control_plane


def test_duplicate_message_creates_one_course():
    intake, control_plane = connector()

    first = intake.handle(event())
    second = intake.handle(event())

    assert first.status == "created"
    assert second.status == "duplicate"
    assert len(control_plane.created_courses) == 1
    assert control_plane.created_courses[0]["source_message_id"] == "m-1"
    assert control_plane.created_courses[0]["files"][0].role == "material"


def test_rejects_unapproved_mime_type_before_download():
    intake, control_plane = connector()

    result = intake.handle(event(mime_type="application/x-msdownload"))

    assert result.status == "rejected"
    assert result.reason == "unsupported_mime_type"
    assert control_plane.created_courses == []


def test_rejects_declared_file_over_size_limit():
    intake, control_plane = connector(max_file_bytes=4)

    result = intake.handle(event(size_bytes=5))

    assert result.status == "rejected"
    assert result.reason == "file_too_large"
    assert control_plane.created_courses == []


def test_rejects_downloaded_file_over_size_limit():
    control_plane = FakeControlPlane()
    intake = DingTalkIntake(
        downloader=FakeDownloader(payload=b"oversize"),
        control_plane=control_plane,
        dedup=DedupStore(":memory:"),
        max_file_bytes=4,
    )

    result = intake.handle(event(size_bytes=0))

    assert result.status == "rejected"
    assert result.reason == "downloaded_file_too_large"


def test_missing_credentials_report_not_configured():
    settings = ConnectorSettings(
        client_id="",
        client_secret="",
        control_plane_url="http://127.0.0.1:8130",
    )

    assert settings.status() == {
        "status": "not_configured",
        "reason": "missing_client_id_and_client_secret",
    }


def test_official_download_flow_uses_token_and_message_file_endpoint():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth2/accessToken"):
            assert json.loads(request.content) == {"appKey": "client", "appSecret": "secret"}
            return httpx.Response(200, json={"accessToken": "token"})
        if request.url.path.endswith("/robot/messageFiles/download"):
            assert request.headers["x-acs-dingtalk-access-token"] == "token"
            return httpx.Response(200, json={"downloadUrl": "https://download.test/raw.mp4"})
        return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})

    settings = ConnectorSettings(
        client_id="client",
        client_secret="secret",
        robot_code="robot",
        control_plane_url="http://127.0.0.1:8130",
    )
    downloader = DingTalkDownloader(settings, transport=httpx.MockTransport(handler))

    downloaded = downloader.download(event().files[0])

    assert downloaded.content == b"video"
    assert downloaded.mime_type == "video/mp4"
    assert [request.url.path for request in requests] == [
        "/v1.0/oauth2/accessToken",
        "/v1.0/robot/messageFiles/download",
        "/raw.mp4",
    ]


def test_stream_callback_mapping_never_assumes_rights():
    settings = ConnectorSettings(
        client_id="client",
        client_secret="secret",
        robot_code="robot",
        control_plane_url="http://127.0.0.1:8130",
    )

    mapped = event_from_callback(
        {
            "msgId": "m-2",
            "senderStaffId": "staff-1",
            "conversationId": "conversation-2",
            "robotCode": "robot",
            "msgtype": "video",
            "content": {"downloadCode": "download", "fileName": "clip.mp4", "fileSize": 42},
        },
        settings,
    )

    assert mapped.message_id == "m-2"
    assert mapped.files[0].mime_type == "video/mp4"
    assert mapped.files[0].rights_status == "unknown"


def test_stream_callback_maps_course_tags_to_role_and_rights():
    settings = ConnectorSettings(
        client_id="client",
        client_secret="secret",
        robot_code="robot",
        control_plane_url="http://127.0.0.1:8130",
    )

    mapped = event_from_callback(
        {
            "msgId": "m-3",
            "senderStaffId": "staff-1",
            "conversationId": "conversation-2",
            "robotCode": "robot",
            "msgtype": "video",
            "content": {
                "downloadCode": "download",
                "fileName": "lesson.mp4",
                "fileSize": 42,
                "text": "#教程 #个人学习 宠物剪辑课",
            },
        },
        settings,
    )

    assert mapped.title == "宠物剪辑课"
    assert mapped.files[0].role == "tutorial"
    assert mapped.files[0].rights_status == "personal_learning"


def test_stream_callback_defaults_untagged_file_to_material_unknown_rights():
    settings = ConnectorSettings(
        client_id="client",
        client_secret="secret",
        robot_code="robot",
        control_plane_url="http://127.0.0.1:8130",
    )

    mapped = event_from_callback(
        {
            "msgId": "m-4",
            "conversationId": "conversation-2",
            "msgtype": "video",
            "content": {"downloadCode": "download", "fileName": "clip.mp4", "fileSize": 42},
        },
        settings,
    )

    assert mapped.files[0].role == "material"
    assert mapped.files[0].rights_status == "unknown"
