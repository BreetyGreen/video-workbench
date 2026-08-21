import httpx
from pathlib import Path

from sqlmodel import Session

from app.adapters.pixabay import PixabayClient, PixabayVideoAsset
from app.adapters.pexels import PexelsClient
from app.config import Settings
from app.db import Database
from app.services.material_library_service import MaterialLibraryService


def test_pixabay_search_uses_official_video_endpoint_and_prefers_vertical_large_video():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/videos/"
        assert request.url.params["key"] == "pixabay-key"
        assert request.url.params["q"] == "pet"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 42,
                        "pageURL": "https://pixabay.com/videos/id-42/",
                        "user": "Creator",
                        "userImageURL": "https://cdn.pixabay.com/user.jpg",
                        "duration": 7,
                        "videos": {
                            "medium": {"url": "https://cdn.pixabay.com/landscape.mp4", "width": 1280, "height": 720},
                            "large": {"url": "https://cdn.pixabay.com/portrait.mp4", "width": 1080, "height": 1920},
                        },
                    }
                ]
            },
        )

    client = PixabayClient(api_key="pixabay-key", transport=httpx.MockTransport(handler))
    result = client.search_videos("pet", count=1)[0]

    assert len(requests) == 1
    assert result.provider_asset_id == "42"
    assert result.download_url == "https://cdn.pixabay.com/portrait.mp4"
    assert result.width == 1080
    assert result.height == 1920


def test_pixabay_is_not_configured_without_key():
    assert PixabayClient(api_key="").configured is False


def test_material_library_falls_back_to_pixabay_when_pexels_is_not_configured(tmp_path: Path):
    class FakePixabay:
        configured = True

        def search_videos(self, query: str, *, count: int):
            return [
                PixabayVideoAsset(
                    provider_asset_id="42",
                    source_url="https://pixabay.com/videos/id-42/",
                    preview_url="",
                    creator_name="Creator",
                    creator_url="https://pixabay.com/users/Creator/",
                    duration_seconds=7,
                    width=1080,
                    height=1920,
                    download_url="https://cdn.pixabay.com/portrait.mp4",
                )
            ]

        def download(self, asset, destination: Path):
            destination.write_bytes(b"pixabay-video")
            return destination.stat().st_size

    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'pixabay.db').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    service = MaterialLibraryService(
        settings,
        PexelsClient(api_key=""),
        pixabay=FakePixabay(),
    )
    with Session(database.engine) as session:
        result = service.acquire(session, "pet", count=1)

    assert result.status == "pixabay_official"
    assert result.assets[0].provider == "pixabay"
    assert result.assets[0].rights_basis == "pixabay_content_license"
