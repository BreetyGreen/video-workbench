from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.adapters.pexels import PEXELS_LICENSE_URL, PexelsClient, PexelsVideoAsset
from app.adapters.pixabay import PIXABAY_LICENSE_URL, PixabayClient, PixabayVideoAsset
from app.config import Settings
from app.models import LicensedAsset, Material, VideoTask


@dataclass(frozen=True)
class LibrarySyncResult:
    imported: int
    skipped_duplicates: int


@dataclass(frozen=True)
class AcquisitionResult:
    assets: list[LicensedAsset]
    status: str
    warning: str = ""


class MaterialLibraryService:
    def __init__(
        self,
        settings: Settings,
        pexels: PexelsClient,
        *,
        pixabay: PixabayClient | None = None,
    ):
        self.settings = settings
        self.pexels = pexels
        self.pixabay = pixabay or PixabayClient(api_key="")
        self.library_root = settings.library_dir.resolve()

    @staticmethod
    def _merge_search_text(existing: str, *parts: str) -> str:
        tokens = [item.strip() for item in existing.split("\n") if item.strip()]
        for part in parts:
            normalized = part.strip()
            if normalized and normalized not in tokens:
                tokens.append(normalized)
        return "\n".join(tokens)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _safe_material_path(self, raw_path: str) -> Path:
        source = Path(raw_path).resolve()
        material_root = self.settings.material_dir.resolve()
        if material_root not in source.parents or not source.is_file():
            raise ValueError("material_path_outside_configured_root")
        return source

    def sync_confirmed_assets(self, session: Session) -> LibrarySyncResult:
        self.library_root.mkdir(parents=True, exist_ok=True)
        imported = 0
        skipped_duplicates = 0
        statement = (
            select(Material, VideoTask)
            .join(VideoTask, VideoTask.id == Material.task_id)
            .where(VideoTask.rights_confirmed.is_(True))
        )
        for material, task in session.exec(statement).all():
            if not material.mime_type.lower().startswith("video/"):
                continue
            existing = session.exec(
                select(LicensedAsset).where(LicensedAsset.sha256 == material.sha256)
            ).first()
            if existing is not None:
                existing.search_text = self._merge_search_text(
                    existing.search_text,
                    task.title,
                    task.content_type,
                    material.original_name,
                )
                session.add(existing)
                skipped_duplicates += 1
                continue
            source = self._safe_material_path(material.stored_path)
            suffix = source.suffix.lower() if source.suffix.lower() == ".mp4" else ".mp4"
            destination = (self.library_root / f"{material.sha256}{suffix}").resolve()
            if self.library_root not in destination.parents:
                raise ValueError("library_destination_outside_root")
            if not destination.is_file():
                shutil.copy2(source, destination)
            session.add(
                LicensedAsset(
                    sha256=material.sha256,
                    provider="user_confirmed",
                    provider_asset_id=material.id,
                    original_name=material.original_name,
                    stored_path=str(destination),
                    mime_type=material.mime_type,
                    size_bytes=destination.stat().st_size,
                    rights_basis="task_rights_confirmed",
                    attribution="用户已确认拥有该素材使用权",
                    search_text=self._merge_search_text(
                        "",
                        task.title,
                        task.content_type,
                        material.original_name,
                    ),
                )
            )
            imported += 1
        session.commit()
        return LibrarySyncResult(imported=imported, skipped_duplicates=skipped_duplicates)

    @staticmethod
    def _match_score(asset: LicensedAsset, query: str) -> tuple[int, int, datetime]:
        haystack = asset.search_text.casefold()
        normalized = query.strip().casefold()
        aliases = {
            "萌宠": "宠物",
            "猫咪": "猫",
            "狗狗": "狗",
            "毛孩子": "宠物",
        }
        variants = {normalized}
        for source, target in aliases.items():
            if source in normalized:
                variants.add(normalized.replace(source, target))
        exact = 1 if any(value and value in haystack for value in variants) else 0
        overlap = max(
            (sum(1 for character in set(value) if character.strip() and character in haystack) for value in variants),
            default=0,
        )
        return exact, overlap, asset.created_at

    def search_local(self, session: Session, query: str, *, limit: int) -> list[LicensedAsset]:
        now = datetime.now(UTC).replace(tzinfo=None)
        candidates = [
            asset
            for asset in session.exec(
                select(LicensedAsset).where(LicensedAsset.rights_status == "authorized")
            ).all()
            if asset.rights_expires_at is None
            or asset.rights_expires_at.replace(tzinfo=None) > now
        ]
        scored = [
            (self._match_score(asset, query), asset)
            for asset in candidates
            if Path(asset.stored_path).is_file()
        ]
        relevant = [item for item in scored if item[0][0] or item[0][1] >= 2]
        relevant.sort(key=lambda item: item[0], reverse=True)
        return [asset for _, asset in relevant[: max(1, limit)]]

    def _store_pexels_asset(
        self,
        session: Session,
        query: str,
        source: PexelsVideoAsset,
    ) -> LicensedAsset:
        by_provider = session.exec(
            select(LicensedAsset).where(
                LicensedAsset.provider == "pexels",
                LicensedAsset.provider_asset_id == source.provider_asset_id,
            )
        ).first()
        if by_provider is not None and Path(by_provider.stored_path).is_file():
            by_provider.search_text = self._merge_search_text(by_provider.search_text, query)
            session.add(by_provider)
            session.commit()
            session.refresh(by_provider)
            return by_provider

        self.library_root.mkdir(parents=True, exist_ok=True)
        temporary = (self.library_root / f".pexels-{source.provider_asset_id}-{uuid4()}.part").resolve()
        if self.library_root not in temporary.parents:
            raise ValueError("temporary_library_path_outside_root")
        try:
            self.pexels.download(source, temporary)
            digest = self._sha256(temporary)
            existing = session.exec(
                select(LicensedAsset).where(LicensedAsset.sha256 == digest)
            ).first()
            if existing is not None:
                existing.search_text = self._merge_search_text(existing.search_text, query)
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing
            destination = (self.library_root / f"{digest}.mp4").resolve()
            if self.library_root not in destination.parents:
                raise ValueError("pexels_destination_outside_root")
            temporary.replace(destination)
            asset = LicensedAsset(
                sha256=digest,
                provider="pexels",
                provider_asset_id=source.provider_asset_id,
                original_name=f"pexels-{source.provider_asset_id}.mp4",
                stored_path=str(destination),
                mime_type="video/mp4",
                size_bytes=destination.stat().st_size,
                width=source.width,
                height=source.height,
                duration_seconds=source.duration_seconds,
                source_url=source.source_url,
                preview_url=source.preview_url,
                creator_name=source.creator_name,
                creator_url=source.creator_url,
                license_url=PEXELS_LICENSE_URL,
                rights_basis="pexels_license",
                attribution=f"Video by {source.creator_name or 'Pexels creator'} on Pexels",
                search_text=query,
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
            return asset
        finally:
            if temporary.is_file():
                temporary.unlink()

    def _store_pixabay_asset(
        self,
        session: Session,
        query: str,
        source: PixabayVideoAsset,
    ) -> LicensedAsset:
        by_provider = session.exec(
            select(LicensedAsset).where(
                LicensedAsset.provider == "pixabay",
                LicensedAsset.provider_asset_id == source.provider_asset_id,
            )
        ).first()
        if by_provider is not None and Path(by_provider.stored_path).is_file():
            by_provider.search_text = self._merge_search_text(by_provider.search_text, query)
            session.add(by_provider)
            session.commit()
            session.refresh(by_provider)
            return by_provider

        self.library_root.mkdir(parents=True, exist_ok=True)
        temporary = (self.library_root / f".pixabay-{source.provider_asset_id}-{uuid4()}.part").resolve()
        if self.library_root not in temporary.parents:
            raise ValueError("temporary_library_path_outside_root")
        try:
            self.pixabay.download(source, temporary)
            digest = self._sha256(temporary)
            existing = session.exec(select(LicensedAsset).where(LicensedAsset.sha256 == digest)).first()
            if existing is not None:
                existing.search_text = self._merge_search_text(existing.search_text, query)
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing
            destination = (self.library_root / f"{digest}.mp4").resolve()
            if self.library_root not in destination.parents:
                raise ValueError("pixabay_destination_outside_root")
            temporary.replace(destination)
            asset = LicensedAsset(
                sha256=digest,
                provider="pixabay",
                provider_asset_id=source.provider_asset_id,
                original_name=f"pixabay-{source.provider_asset_id}.mp4",
                stored_path=str(destination),
                mime_type="video/mp4",
                size_bytes=destination.stat().st_size,
                width=source.width,
                height=source.height,
                duration_seconds=source.duration_seconds,
                source_url=source.source_url,
                preview_url=source.preview_url,
                creator_name=source.creator_name,
                creator_url=source.creator_url,
                license_url=PIXABAY_LICENSE_URL,
                rights_status="authorized",
                rights_basis="pixabay_content_license",
                allowed_platforms_json='["douyin", "xiaohongshu"]',
                attribution=f"Video by {source.creator_name or 'Pixabay creator'} on Pixabay",
                search_text=query,
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
            return asset
        finally:
            if temporary.is_file():
                temporary.unlink()

    def acquire(self, session: Session, query: str, *, count: int) -> AcquisitionResult:
        self.sync_confirmed_assets(session)
        warning = ""
        if self.pexels.configured:
            try:
                results = self.pexels.search_videos(query, count=max(count, 3))
                acquired: list[LicensedAsset] = []
                seen: set[str] = set()
                for source in results:
                    asset = self._store_pexels_asset(session, query, source)
                    if asset.id not in seen:
                        acquired.append(asset)
                        seen.add(asset.id)
                    if len(acquired) >= count:
                        break
                if acquired:
                    return AcquisitionResult(assets=acquired, status="pexels_official")
            except Exception as error:
                warning = f"pexels_acquisition_failed:{type(error).__name__}"
        if self.pixabay.configured:
            try:
                results = self.pixabay.search_videos(query, count=max(count, 3))
                acquired = []
                seen: set[str] = set()
                for source in results:
                    asset = self._store_pixabay_asset(session, query, source)
                    if asset.id not in seen:
                        acquired.append(asset)
                        seen.add(asset.id)
                    if len(acquired) >= count:
                        break
                if acquired:
                    return AcquisitionResult(assets=acquired, status="pixabay_official", warning=warning)
            except Exception as error:
                suffix = f"pixabay_acquisition_failed:{type(error).__name__}"
                warning = f"{warning};{suffix}" if warning else suffix
        local = self.search_local(session, query, limit=count)
        status = "local_catalog" if local else "no_licensed_assets"
        return AcquisitionResult(assets=local, status=status, warning=warning)

    @staticmethod
    def mark_used(session: Session, assets: list[LicensedAsset]) -> None:
        now = datetime.now(UTC)
        for asset in assets:
            asset.use_count += 1
            asset.last_used_at = now
            session.add(asset)
        session.commit()

    @staticmethod
    def as_dict(asset: LicensedAsset) -> dict[str, object]:
        return {
            "id": asset.id,
            "provider": asset.provider,
            "provider_asset_id": asset.provider_asset_id,
            "original_name": asset.original_name,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "width": asset.width,
            "height": asset.height,
            "duration_seconds": asset.duration_seconds,
            "source_url": asset.source_url,
            "preview_url": asset.preview_url,
            "creator_name": asset.creator_name,
            "creator_url": asset.creator_url,
            "license_url": asset.license_url,
            "rights_status": asset.rights_status,
            "rights_basis": asset.rights_basis,
            "product_id": asset.product_id,
            "allowed_platforms": json.loads(asset.allowed_platforms_json or "[]"),
            "rights_expires_at": asset.rights_expires_at,
            "attribution": asset.attribution,
            "search_text": asset.search_text,
            "use_count": asset.use_count,
            "created_at": asset.created_at,
            "last_used_at": asset.last_used_at,
        }

    @staticmethod
    def provider_counts(session: Session) -> dict[str, int]:
        counts: dict[str, int] = {}
        for asset in session.exec(select(LicensedAsset)).all():
            counts[asset.provider] = counts.get(asset.provider, 0) + 1
        return counts
