from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import Settings


@dataclass(frozen=True)
class DouyinVideo:
    item_id: str
    title: str
    cover_url: str
    published_at: datetime | None
    author: str
    digg_count: int
    url: str
    high_quality_text: str


class DouyinSearchClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.client = httpx.Client(
            base_url="https://open.douyin.com/",
            timeout=30,
            transport=transport,
        )
        self._token = ""
        self._token_expires_at = 0.0

    def status(self) -> dict[str, str]:
        missing = []
        if not self.settings.douyin_client_key:
            missing.append("client_key")
        if not self.settings.douyin_client_secret:
            missing.append("client_secret")
        if not self.settings.douyin_device_id:
            missing.append("device_id")
        if missing:
            return {"status": "not_configured", "reason": f"missing_{'_and_'.join(missing)}"}
        return {"status": "configured"}

    def _client_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        if self.status()["status"] != "configured":
            raise RuntimeError(f"Douyin search is not configured: {self.status()['reason']}")
        response = self.client.post(
            "oauth/client_token/",
            json={
                "grant_type": "client_credential",
                "client_key": self.settings.douyin_client_key,
                "client_secret": self.settings.douyin_client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json().get("data", {})
        if int(payload.get("error_code", -1)) != 0:
            raise RuntimeError(f"Douyin token error {payload.get('error_code')}: {payload.get('description', '')}")
        self._token = str(payload["access_token"])
        self._token_expires_at = time.monotonic() + max(60, int(payload.get("expires_in", 7200)) - 300)
        return self._token

    def search(
        self,
        keyword: str,
        *,
        count: int = 10,
        publish_time: int = 7,
        sort_type: int = 1,
    ) -> list[DouyinVideo]:
        response = self.client.get(
            "dy_open_api/v1/search/video/",
            headers={"access-token": self._client_token(), "content-type": "application/json"},
            params={
                "device_id": self.settings.douyin_device_id,
                "keyword": keyword,
                "publish_time": publish_time,
                "sort_type": sort_type,
                "cursor": 0,
                "count": min(max(count, 1), 20),
            },
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("err_no", -1)) != 0:
            raise RuntimeError(f"Douyin search error {payload.get('err_no')}: {payload.get('err_msg', '')}")
        data = payload.get("data", {}).get("data", {})
        videos = []
        for item in data.get("video_list", []):
            created = item.get("create_time")
            videos.append(
                DouyinVideo(
                    item_id=str(item.get("item_id", "")),
                    title=str(item.get("title", "")),
                    cover_url=str(item.get("cover", "")),
                    published_at=datetime.fromtimestamp(int(created), tz=UTC) if created else None,
                    author=str(item.get("nickname", "")),
                    digg_count=int(item.get("statistics", {}).get("digg_count", 0)),
                    url=str(item.get("link", "")),
                    high_quality_text=str(item.get("high_quality_text", "")),
                )
            )
        return videos
