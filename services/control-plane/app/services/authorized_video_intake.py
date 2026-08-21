from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import Session, select

from app.config import Settings
from app.models import LicensedAsset


@dataclass(frozen=True)
class IntakeResult:
    asset: LicensedAsset
    created: bool


class AuthorizedVideoIntake:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.library_root = settings.library_dir.resolve()

    def ingest(
        self,
        session: Session,
        *,
        upload: UploadFile,
        source_type: str,
        rights_basis: str,
        product_id: str,
        allowed_platforms: list[str],
        search_text: str,
        rights_expires_at: datetime | None,
    ) -> IntakeResult:
        mime_type = (upload.content_type or "").split(";", 1)[0].lower()
        if not mime_type.startswith("video/"):
            raise ValueError("authorized_material_must_be_video")
        basis = rights_basis.strip()
        if not basis:
            raise ValueError("rights_basis_required")
        platforms = list(dict.fromkeys(item.strip().lower() for item in allowed_platforms if item.strip()))
        if not platforms:
            raise ValueError("allowed_platform_required")
        if rights_expires_at is not None:
            comparable = rights_expires_at
            if comparable.tzinfo is None:
                comparable = comparable.replace(tzinfo=UTC)
            if comparable <= datetime.now(UTC):
                raise ValueError("rights_expired")

        payload = upload.file.read()
        if not payload:
            raise ValueError("video_file_empty")
        if len(payload) > self.settings.pexels_max_download_bytes:
            raise ValueError("video_file_too_large")
        digest = hashlib.sha256(payload).hexdigest()
        existing = session.exec(
            select(LicensedAsset).where(LicensedAsset.sha256 == digest)
        ).first()
        if existing is not None:
            existing.rights_status = "authorized"
            existing.rights_basis = basis
            existing.product_id = product_id.strip()
            existing.allowed_platforms_json = json.dumps(platforms, ensure_ascii=False)
            existing.rights_expires_at = rights_expires_at
            existing.search_text = "\n".join(
                dict.fromkeys(filter(None, [existing.search_text, search_text.strip()]))
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return IntakeResult(existing, False)

        self.library_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename or "video.mp4").suffix.lower()
        if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
            suffix = ".mp4"
        destination = (self.library_root / f"{digest}-{uuid4().hex[:8]}{suffix}").resolve()
        if self.library_root not in destination.parents:
            raise ValueError("library_destination_outside_root")
        destination.write_bytes(payload)
        asset = LicensedAsset(
            sha256=digest,
            provider=source_type.strip() or "user_confirmed",
            provider_asset_id=product_id.strip() or digest,
            original_name=Path(upload.filename or "authorized-video.mp4").name,
            stored_path=str(destination),
            mime_type=mime_type,
            size_bytes=len(payload),
            rights_status="authorized",
            rights_basis=basis,
            product_id=product_id.strip(),
            allowed_platforms_json=json.dumps(platforms, ensure_ascii=False),
            rights_expires_at=rights_expires_at,
            attribution=basis,
            search_text=search_text.strip(),
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return IntakeResult(asset, True)
