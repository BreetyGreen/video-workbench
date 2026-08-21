from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx


class DouyinApiError(RuntimeError):
    def __init__(self, code: int, description: str):
        super().__init__(f"douyin_api_error:{code}:{description}")
        self.code = code
        self.description = description


@dataclass(frozen=True)
class DouyinCreateResult:
    item_id: str
    video_id: str
    visibility: str


class DouyinPublishClient:
    def __init__(
        self,
        *,
        base_url: str = "https://open.douyin.com",
        timeout_seconds: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @staticmethod
    def private_status(visibility: str) -> int:
        mapping = {"public": 0, "self": 1, "friends": 2}
        if visibility not in mapping:
            raise ValueError("unsupported_douyin_visibility")
        return mapping[visibility]

    @staticmethod
    def _data(payload: dict[str, object]) -> dict[str, object]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        code = int(data.get("error_code") or 0)
        if code:
            raise DouyinApiError(code, str(data.get("description") or "unknown_error"))
        return data

    def upload_video(self, path: Path, *, open_id: str, access_token: str) -> str:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if not open_id.strip() or not access_token.strip():
            raise ValueError("douyin_oauth_required")
        with resolved.open("rb") as source:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/api/douyin/v1/video/upload_video/",
                    params={"open_id": open_id},
                    headers={"access-token": access_token},
                    files={"video": (resolved.name, source, "video/mp4")},
                )
                response.raise_for_status()
                data = self._data(response.json())
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        video_id = str(video.get("video_id") or "")
        if not video_id:
            raise DouyinApiError(0, "missing_video_id")
        return video_id

    def create_video(
        self,
        *,
        video_id: str,
        title: str,
        visibility: str,
        open_id: str,
        access_token: str,
    ) -> DouyinCreateResult:
        if not video_id.strip() or not open_id.strip() or not access_token.strip():
            raise ValueError("douyin_oauth_required")
        text = title.strip()
        if not text:
            raise ValueError("douyin_title_required")
        if len(text) > 1000:
            raise ValueError("douyin_title_too_long")
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/api/douyin/v1/video/create_video/",
                params={"open_id": open_id},
                headers={"access-token": access_token, "content-type": "application/json"},
                json={
                    "video_id": video_id,
                    "text": text,
                    "private_status": self.private_status(visibility),
                },
            )
            response.raise_for_status()
            data = self._data(response.json())
        return DouyinCreateResult(
            item_id=str(data.get("item_id") or ""),
            video_id=str(data.get("video_id") or video_id),
            visibility=visibility,
        )
