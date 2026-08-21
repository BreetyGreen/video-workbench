from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx


PEXELS_LICENSE_URL = "https://www.pexels.com/license/"


@dataclass(frozen=True)
class PexelsVideoAsset:
    provider_asset_id: str
    source_url: str
    preview_url: str
    creator_name: str
    creator_url: str
    duration_seconds: float
    width: int
    height: int
    download_url: str


class PexelsClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.pexels.com",
        timeout_seconds: float = 60.0,
        max_download_bytes: int = 262_144_000,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, str]:
        if self.configured:
            return {"status": "configured", "provider": "pexels_official_api"}
        return {
            "status": "not_configured",
            "provider": "pexels_official_api",
            "reason": "missing_api_key",
        }

    @staticmethod
    def _file_score(item: dict[str, object]) -> tuple[int, int, int]:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        portrait = 1 if height >= width and height > 0 else 0
        full_hd = 1 if min(width, height) >= 720 else 0
        pixels = width * height
        return portrait, full_hd, pixels

    def search_videos(self, query: str, *, count: int = 6) -> list[PexelsVideoAsset]:
        if not self.configured:
            raise RuntimeError("pexels_not_configured")
        normalized = query.strip()
        if not normalized:
            raise ValueError("query_required")
        with httpx.Client(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = client.get(
                f"{self.base_url}/v1/videos/search",
                headers={"Authorization": self.api_key},
                params={
                    "query": normalized,
                    "orientation": "portrait",
                    "size": "medium",
                    "locale": "zh-CN",
                    "per_page": min(max(count, 1), 20),
                },
            )
            response.raise_for_status()
            payload = response.json()
        results: list[PexelsVideoAsset] = []
        for video in payload.get("videos", []):
            if not isinstance(video, dict):
                continue
            candidates = [
                item
                for item in video.get("video_files", [])
                if isinstance(item, dict)
                and item.get("file_type") == "video/mp4"
                and str(item.get("link") or "").startswith("https://")
            ]
            if not candidates:
                continue
            selected = max(candidates, key=self._file_score)
            user = video.get("user") if isinstance(video.get("user"), dict) else {}
            results.append(
                PexelsVideoAsset(
                    provider_asset_id=str(video.get("id") or ""),
                    source_url=str(video.get("url") or ""),
                    preview_url=str(video.get("image") or ""),
                    creator_name=str(user.get("name") or ""),
                    creator_url=str(user.get("url") or ""),
                    duration_seconds=float(video.get("duration") or 0),
                    width=int(selected.get("width") or video.get("width") or 0),
                    height=int(selected.get("height") or video.get("height") or 0),
                    download_url=str(selected.get("link") or ""),
                )
            )
        return results

    @staticmethod
    def _trusted_download_url(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            host == "pexels.com"
            or host.endswith(".pexels.com")
            or host == "vimeo.com"
            or host.endswith(".vimeo.com")
        )

    def download(self, asset: PexelsVideoAsset, destination: Path) -> int:
        if not self._trusted_download_url(asset.download_url):
            raise ValueError("untrusted_pexels_download_url")
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            with client.stream("GET", asset.download_url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and content_type not in {"video/mp4", "application/octet-stream"}:
                    raise ValueError("pexels_download_not_video")
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max_download_bytes:
                            raise ValueError("pexels_download_too_large")
                        output.write(chunk)
        return total
