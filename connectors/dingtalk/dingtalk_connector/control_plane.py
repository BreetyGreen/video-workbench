from __future__ import annotations

import httpx

from dingtalk_connector.intake import DownloadedFile


class ControlPlaneClient:
    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=60, transport=transport)

    def create_task(
        self,
        *,
        title: str,
        content_type: str,
        rights_confirmed: bool,
        files: list[DownloadedFile],
        source_type: str,
        source_user: str,
        source_conversation: str,
        source_message_id: str,
        deduplication_key: str,
    ) -> str:
        response = self.client.post(
            "api/tasks",
            data={
                "title": title,
                "content_type": content_type,
                "rights_confirmed": str(rights_confirmed).lower(),
                "source_type": source_type,
                "source_user": source_user,
                "source_conversation": source_conversation,
                "source_message_id": source_message_id,
                "deduplication_key": deduplication_key,
            },
            files=[("files", (item.name, item.content, item.mime_type)) for item in files],
        )
        response.raise_for_status()
        return response.json()["id"]
