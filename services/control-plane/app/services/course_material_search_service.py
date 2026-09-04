from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import CourseAsset, CourseAssetRole, MaterialShot, RightsStatus


@dataclass(frozen=True)
class ShotSearchResult:
    shot_id: str
    asset_id: str
    original_name: str
    start_ms: int
    end_ms: int
    thumbnail_path: str
    rights_status: str
    text_score: float
    semantic_score: float
    duplicate_score: float
    combined_score: float


def _tokens(query: str) -> list[str]:
    return [item for item in re.split(r"[\s,，。;；]+", query.lower().strip()) if item]


class CourseMaterialSearchService:
    def search(
        self,
        session: Session,
        course_id: str,
        query: str,
        *,
        commercial: bool,
        limit: int = 20,
    ) -> list[ShotSearchResult]:
        assets = list(
            session.exec(
                select(CourseAsset)
                .where(CourseAsset.course_id == course_id)
                .where(CourseAsset.role == CourseAssetRole.MATERIAL)
            ).all()
        )
        if commercial:
            assets = [asset for asset in assets if asset.rights_status == RightsStatus.COMMERCIAL_AUTHORIZED]
        by_id = {asset.id: asset for asset in assets}
        if not by_id:
            return []
        shots = list(session.exec(select(MaterialShot).where(MaterialShot.asset_id.in_(by_id))).all())
        query_tokens = _tokens(query)
        results: list[ShotSearchResult] = []
        for shot in shots:
            asset = by_id[shot.asset_id]
            tags = " ".join(json.loads(shot.tags_json or "[]"))
            haystack = f"{asset.original_name} {shot.ocr_text} {tags}".lower()
            matched = sum(token in haystack for token in query_tokens)
            text_score = matched / len(query_tokens) if query_tokens else 0.0
            results.append(
                ShotSearchResult(
                    shot_id=shot.id,
                    asset_id=asset.id,
                    original_name=asset.original_name,
                    start_ms=shot.start_ms,
                    end_ms=shot.end_ms,
                    thumbnail_path=shot.thumbnail_path,
                    rights_status=asset.rights_status.value,
                    text_score=text_score,
                    semantic_score=0.0,
                    duplicate_score=0.0,
                    combined_score=text_score,
                )
            )
        return sorted(results, key=lambda item: (-item.combined_score, item.shot_id))[: max(1, min(limit, 100))]
