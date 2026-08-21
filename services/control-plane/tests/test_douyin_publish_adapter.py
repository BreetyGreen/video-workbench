import json
from pathlib import Path

import httpx

from app.adapters.douyin_publish import DouyinPublishClient


def test_douyin_upload_and_self_visible_create_use_official_contract(tmp_path: Path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/upload_video/"):
            return httpx.Response(200, json={"data": {"error_code": 0, "video": {"video_id": "encrypted-video"}}})
        return httpx.Response(200, json={"data": {"error_code": 0, "item_id": "item-1", "video_id": "video-1"}})

    media = tmp_path / "preview.mp4"
    media.write_bytes(b"mp4")
    client = DouyinPublishClient(transport=httpx.MockTransport(handler))

    video_id = client.upload_video(media, open_id="open-1", access_token="token-1")
    result = client.create_video(
        video_id=video_id,
        title="宠物梳毛 #萌宠",
        visibility="self",
        open_id="open-1",
        access_token="token-1",
    )

    assert result.item_id == "item-1"
    assert requests[0].url.path == "/api/douyin/v1/video/upload_video/"
    assert requests[0].headers["access-token"] == "token-1"
    assert requests[1].url.path == "/api/douyin/v1/video/create_video/"
    payload = json.loads(requests[1].content)
    assert payload["video_id"] == "encrypted-video"
    assert payload["private_status"] == 1
    assert payload["text"] == "宠物梳毛 #萌宠"


def test_douyin_public_visibility_maps_to_zero():
    client = DouyinPublishClient()
    assert client.private_status("public") == 0
