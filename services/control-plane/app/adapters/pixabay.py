from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx


PIXABAY_LICENSE_URL = "https://pixabay.com/service/license-summary/"


@dataclass(frozen=True)
class PixabayVideoAsset:
    provider_asset_id: str
    source_url: str
    preview_url: str
    creator_name: str
    creator_url: str
    duration_seconds: float
    width: int
    height: int
    download_url: str


class PixabayClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://pixabay.com",
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
        return (
            {"status": "configured", "provider": "pixabay_official_api"}
            if self.configured
            else {"status": "not_configured", "provider": "pixabay_official_api", "reason": "missing_api_key"}
        )

    @staticmethod
    def _score(item: dict[str, object]) -> tuple[int, int, int]:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        return (1 if height >= width and height else 0, 1 if min(width, height) >= 720 else 0, width * height)

    def search_videos(self, query: str, *, count: int = 6) -> list[PixabayVideoAsset]:
        if not self.configured:
            raise RuntimeError("pixabay_not_configured")
        normalized = query.strip()
        if not normalized:
            raise ValueError("query_required")
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.base_url}/api/videos/",
                params={"key": self.api_key, "q": normalized, "per_page": min(max(count, 3), 20), "safesearch": "true"},
            )
            response.raise_for_status()
            payload = response.json()
        results: list[PixabayVideoAsset] = []
        for hit in payload.get("hits", []):
            if not isinstance(hit, dict):
                continue
            videos = hit.get("videos") if isinstance(hit.get("videos"), dict) else {}
            candidates = [value for value in videos.values() if isinstance(value, dict) and str(value.get("url") or "").startswith("https://")]
            if not candidates:
                continue
            selected = max(candidates, key=self._score)
            creator = str(hit.get("user") or "")
            results.append(
                PixabayVideoAsset(
                    provider_asset_id=str(hit.get("id") or ""),
                    source_url=str(hit.get("pageURL") or ""),
                    preview_url=str(hit.get("picture_id") or hit.get("userImageURL") or ""),
                    creator_name=creator,
                    creator_url=f"https://pixabay.com/users/{creator}/" if creator else "",
                    duration_seconds=float(hit.get("duration") or 0),
                    width=int(selected.get("width") or 0),
                    height=int(selected.get("height") or 0),
                    download_url=str(selected.get("url") or ""),
                )
            )
        return results

    @staticmethod
    def _trusted_download_url(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "pixabay.com" or host.endswith(".pixabay.com") or host.endswith(".pixabay.com.cn"))

    def download(self, asset: PixabayVideoAsset, destination: Path) -> int:
        if not self._trusted_download_url(asset.download_url):
            raise ValueError("untrusted_pixabay_download_url")
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            with client.stream("GET", asset.download_url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and content_type not in {"video/mp4", "application/octet-stream"}:
                    raise ValueError("pixabay_download_not_video")
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max_download_bytes:
                            raise ValueError("pixabay_download_too_large")
                        output.write(chunk)
        return total
