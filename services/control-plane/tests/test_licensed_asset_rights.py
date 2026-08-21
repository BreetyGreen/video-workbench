from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from app.adapters.pexels import PexelsClient
from app.config import Settings
from app.db import Database
from app.models import LicensedAsset
from app.services.material_library_service import MaterialLibraryService


def _asset(path: Path, *, sha256: str, rights_status: str, expires=None) -> LicensedAsset:
    path.write_bytes(sha256.encode())
    return LicensedAsset(
        sha256=sha256,
        provider="merchant_authorized",
        provider_asset_id=sha256,
        original_name=f"{sha256}.mp4",
        stored_path=str(path),
        rights_status=rights_status,
        rights_basis="merchant_contract",
        allowed_platforms_json='["douyin"]',
        rights_expires_at=expires,
        search_text="宠物 商品介绍",
    )


def test_material_selector_returns_only_currently_authorized_assets(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'rights.db').as_posix()}",
    )
    database = Database(settings.database_url)
    database.create_all()
    settings.library_dir.mkdir(parents=True, exist_ok=True)
    with Session(database.engine) as session:
        authorized = _asset(settings.library_dir / "authorized.mp4", sha256="authorized", rights_status="authorized")
        pending = _asset(settings.library_dir / "pending.mp4", sha256="pending", rights_status="pending")
        expired = _asset(
            settings.library_dir / "expired.mp4",
            sha256="expired",
            rights_status="authorized",
            expires=datetime.now(UTC) - timedelta(days=1),
        )
        session.add_all([authorized, pending, expired])
        session.commit()

        service = MaterialLibraryService(settings, PexelsClient(api_key=""))
        selected = service.search_local(session, "宠物", limit=10)

    assert [item.id for item in selected] == [authorized.id]
