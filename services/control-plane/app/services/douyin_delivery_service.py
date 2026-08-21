from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from app.adapters.douyin_publish import DouyinCreateResult, DouyinPublishClient
from app.models import DeliveryState, TaskStatus, VideoTask


class DouyinDeliveryService:
    def __init__(self, client: DouyinPublishClient, artifact_root: Path):
        self.client = client
        self.artifact_root = artifact_root.resolve()

    def deliver(
        self,
        session: Session,
        task: VideoTask,
        *,
        title: str,
        visibility: str,
        open_id: str,
        access_token: str,
    ) -> tuple[VideoTask, DouyinCreateResult]:
        if task.status != TaskStatus.APPROVED:
            raise ValueError("task_must_be_approved")
        preview = (self.artifact_root / task.id / "preview.mp4").resolve()
        if self.artifact_root not in preview.parents or not preview.is_file():
            raise ValueError("preview_not_found")
        video_id = self.client.upload_video(preview, open_id=open_id, access_token=access_token)
        result = self.client.create_video(
            video_id=video_id,
            title=title,
            visibility=visibility,
            open_id=open_id,
            access_token=access_token,
        )
        task.delivery_state = (
            DeliveryState.DOUYIN_SELF_VISIBLE
            if visibility == "self"
            else DeliveryState.DOUYIN_PUBLISHED
        )
        task.delivery_provider_id = result.item_id
        task.delivered_at = datetime.now(UTC)
        task.status = TaskStatus.DELIVERED
        task.updated_at = datetime.now(UTC)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task, result
